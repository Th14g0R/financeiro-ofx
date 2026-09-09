from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any

from django.db import transaction as db_transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from finance.models import Account, Bank, InternalTransfer, Transaction, TransactionDuplicateReview
from services.counterparties.resolver import resolve_transaction_counterparty
from services.counterparties.resolver import resolve_transaction_counterparty_from_hint
from services.importing.staging import build_fingerprint
from services.internal_transfers.matcher import analyze_internal_transfers
from services.duplicates import analyze_duplicates

from .models import PluggyAccount, PluggyConfiguration, PluggyItem, PluggyTransactionLink
from .pluggy import (
    MEU_PLUGGY_CONNECTOR_ID,
    PluggyApiError,
    list_accounts,
    list_all_transactions,
    retrieve_identity,
    retrieve_item,
)


@dataclass(frozen=True, slots=True)
class SyncResult:
    items: int = 0
    accounts: int = 0
    accounts_created: int = 0
    banks_created: int = 0
    accounts_reclassified: int = 0
    legacy_banks_removed: int = 0
    transactions_seen: int = 0
    transactions_created: int = 0
    transactions_existing: int = 0
    pending_skipped: int = 0
    conflicts: int = 0
    account_reviews_pending: int = 0
    duplicate_reviews_pending: int = 0
    duplicates_quarantined: int = 0


@dataclass(frozen=True, slots=True)
class AccountSyncResult:
    accounts: tuple[PluggyAccount, ...]
    local_accounts_created: int = 0
    local_banks_created: int = 0
    local_accounts_reclassified: int = 0
    legacy_banks_removed: int = 0
    reviews_pending: int = 0


@dataclass(frozen=True, slots=True)
class LocalAccountResolution:
    account: Account | None
    account_created: bool = False
    bank_created: bool = False
    account_reclassified: bool = False
    legacy_bank_removed: bool = False
    review_pending: bool = False


def _dt(value: Any):
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = parse_datetime(value.strip())
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _connector_metadata(item_payload: dict[str, Any]) -> tuple[int | None, str]:
    connector = item_payload.get("connector")
    connector_id = item_payload.get("connectorId")
    connector_name = item_payload.get("connectorName") or ""
    if isinstance(connector, dict):
        connector_id = connector.get("id", connector_id)
        connector_name = (
            connector.get("name")
            or connector.get("institutionName")
            or connector_name
        )
    try:
        connector_id = int(connector_id) if connector_id is not None else None
    except (TypeError, ValueError):
        connector_id = None
    return connector_id, str(connector_name or "")[:180]


def upsert_item(
    configuration: PluggyConfiguration,
    payload: dict[str, Any],
    *,
    user=None,
) -> PluggyItem:
    item_id = str(payload.get("id") or "").strip()
    if not item_id:
        raise ValueError("Item Pluggy sem id.")

    connector_id, connector_name = _connector_metadata(payload)
    error = payload.get("error")
    if isinstance(error, dict):
        error_text = str(error.get("message") or error.get("code") or "")
    else:
        error_text = str(error or "")

    # Preserve Pluggy's product-level status information.  In previous
    # revisions we replaced statusDetail with only the top-level error, which
    # hid the reason for PARTIAL_SUCCESS executions from the UI.
    raw_status_detail = payload.get("statusDetail")
    status_detail = (
        dict(raw_status_detail)
        if isinstance(raw_status_detail, dict)
        else {}
    )

    execution_report = payload.get("executionReport")
    if execution_report not in (None, {}, []):
        status_detail["_executionReport"] = execution_report

    if error not in (None, {}, []):
        status_detail["_error"] = error

    next_auto_sync_at = payload.get("nextAutoSyncAt")
    if next_auto_sync_at:
        status_detail["_nextAutoSyncAt"] = next_auto_sync_at

    defaults = {
        "configuration": configuration,
        "connector_id": connector_id,
        "connector_name": connector_name,
        "client_user_id": str(payload.get("clientUserId") or "")[:120],
        "status": str(payload.get("status") or "")[:40],
        "execution_status": str(payload.get("executionStatus") or "")[:60],
        "status_detail": status_detail,
        "last_updated_at": _dt(payload.get("lastUpdatedAt")),
        "last_error": error_text[:1000],
        "is_active": True,
    }
    item, created = PluggyItem.objects.update_or_create(
        item_id=item_id,
        defaults=defaults,
    )
    if created and user is not None:
        item.created_by = user
        item.save(update_fields=["created_by", "updated_at"])
    return item


def refresh_item(item: PluggyItem) -> PluggyItem:
    try:
        payload = retrieve_item(item.configuration, item.item_id)
    except PluggyApiError as exc:
        if exc.status_code == 404:
            raise PluggyApiError(
                (
                    f"A Pluggy não encontrou o Item remoto {item.item_id}. "
                    "Os dados já copiados no Financeiro OFX permanecem preservados. "
                    "Confirme no Pluggy Dashboard se este Item ainda pertence à mesma "
                    "aplicação/credenciais configuradas e, se necessário, gere um novo Item ID."
                ),
                status_code=404,
            ) from exc
        raise PluggyApiError(
            f"Falha ao consultar o Item {item.item_id} na Pluggy: {exc}",
            status_code=exc.status_code,
        ) from exc
    return upsert_item(item.configuration, payload, user=item.created_by)


def _parse_transfer_number(value: str) -> tuple[str, str, str, str]:
    value = " ".join((value or "").split()).strip()
    if not value:
        return "", "", "", ""
    parts = [x.strip() for x in value.split("/") if x.strip()]
    bank_code = branch = number = digit = ""
    if len(parts) >= 3:
        bank_code, branch, account_piece = parts[-3], parts[-2], parts[-1]
    elif len(parts) == 2:
        branch, account_piece = parts
    else:
        account_piece = parts[0]
    if "-" in account_piece:
        number, digit = account_piece.rsplit("-", 1)
    else:
        number = account_piece
    return bank_code[-3:], branch, number, digit


def _account_type(subtype: str) -> str:
    normalized = (subtype or "").upper()
    if "SAVING" in normalized:
        return Account.AccountType.SAVINGS
    if "PAYMENT" in normalized:
        return Account.AccountType.PAYMENT
    if "INVEST" in normalized:
        return Account.AccountType.INVESTMENT
    if "CHECK" in normalized:
        return Account.AccountType.CHECKING
    return Account.AccountType.OTHER


def _normalized_bank_code(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    code = digits[-3:].zfill(3)
    # Meu Pluggy can expose 000 when the underlying institution does not
    # provide a COMPE code. 000 is not useful as a bank identity and caused
    # the old implementation to create a fake "MeuPluggy / 000" bank.
    return "" if code == "000" else code


def _clean_proxy_institution_name(value: str) -> str:
    raw = " ".join(str(value or "").split()).strip()
    if not raw:
        return ""

    # Account labels returned through Meu Pluggy commonly carry the product
    # subtype in parentheses, e.g. "RecargaPay (Conta Pré-paga)".
    raw = re.sub(
        r"\s*\((?:[^()]*(?:conta|cart[aã]o|poupan[cç]a|pré[- ]?paga|pre[- ]?paga)[^()]*)\)\s*$",
        "",
        raw,
        flags=re.IGNORECASE,
    ).strip()

    # Keep the user-facing institution/brand and drop legal descriptions that
    # are not useful in dashboard filters.
    raw = re.sub(
        r"\s+INSTITUI[CÇ][AÃ]O\s+DE\s+PAGAMENTO(?:\s+S\.?\s*A\.?)?.*$",
        "",
        raw,
        flags=re.IGNORECASE,
    ).strip()

    normalized = re.sub(r"[^A-Z0-9]+", " ", raw.upper()).strip()
    aliases = {
        "PICPAY": "PicPay",
        "RECARGAPAY": "RecargaPay",
        "MERCADO PAGO": "Mercado Pago",
        "NUBANK": "Nubank",
    }
    if normalized in aliases:
        return aliases[normalized]

    return raw[:120]


def _bank_identity(item: PluggyItem, payload: dict[str, Any]) -> tuple[str, str]:
    bank_code, _branch, _number, _digit = _account_coordinates(payload)
    bank_code = _normalized_bank_code(bank_code)

    connector_name = " ".join(str(item.connector_name or "").split()).strip()
    connector_upper = connector_name.upper()
    is_proxy_connector = (
        item.connector_id == MEU_PLUGGY_CONNECTOR_ID
        or "SANDBOX OPEN FINANCE" in connector_upper
    )

    if is_proxy_connector:
        account_label = str(
            payload.get("marketingName")
            or payload.get("name")
            or ""
        )
        bank_name = _clean_proxy_institution_name(account_label)
    else:
        bank_name = connector_name

    if not bank_name:
        bank_name = _clean_proxy_institution_name(
            str(payload.get("marketingName") or payload.get("name") or "")
        )
    if not bank_name:
        bank_name = "Pluggy / Open Finance"

    return bank_name[:120], bank_code


def _legacy_account_was_created_by_pluggy(
    pluggy_account: PluggyAccount,
    local_account: Account,
) -> bool:
    expected_ofx_id = f"PLUGGY:{pluggy_account.pluggy_account_id}"
    try:
        created_near = abs(local_account.created_at - pluggy_account.created_at).total_seconds() <= 600
    except (TypeError, AttributeError):
        created_near = False
    return local_account.ofx_account_id == expected_ofx_id and created_near


def _bank_known_as_pluggy_created(bank: Bank) -> bool:
    return PluggyAccount.objects.filter(
        local_account__bank=bank,
        local_bank_created_by_pluggy=True,
    ).exists()


def _get_or_create_bank(*, name: str, code: str) -> tuple[Bank, bool]:
    bank = None
    if code:
        bank = Bank.objects.filter(code=code).first()
    if bank is None:
        bank = Bank.objects.filter(name__iexact=name).first()

    created = False
    if bank is None:
        kwargs = {"name": name[:120], "is_active": True}
        if code and not Bank.objects.filter(code=code).exists():
            kwargs["code"] = code
        bank = Bank.objects.create(**kwargs)
        created = True
    elif not bank.is_active:
        bank.is_active = True
        bank.save(update_fields=["is_active", "updated_at"])

    return bank, created


def _delete_empty_owned_legacy_bank(bank: Bank, *, owned: bool) -> bool:
    if not owned:
        return False
    if bank.accounts.exists() or bank.import_statements.exists():
        return False
    try:
        bank.delete()
    except ProtectedError:
        return False
    return True


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _normalized_account_identity(branch: str, number: str, digit: str) -> tuple[str, str]:
    normalized_branch = _digits_only(branch).lstrip("0") or "0"
    normalized_number = (_digits_only(number) + _digits_only(digit)).lstrip("0")
    return normalized_branch, normalized_number


def _account_coordinates(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    """Retorna COMPE/agência/número/dígito usando o dado mais rico disponível.

    A Pluggy expõe ``bankData.transferNumber`` em parte dos conectores, mas o
    campo ``number`` da Account é obrigatório e pode ser a única identificação
    disponível. O fallback evita criar uma segunda conta só porque
    ``transferNumber`` veio vazio no Meu Pluggy/Open Finance.
    """
    bank_data = payload.get("bankData") if isinstance(payload.get("bankData"), dict) else {}
    transfer_number = str(bank_data.get("transferNumber") or "").strip()
    bank_code, branch, number, digit = _parse_transfer_number(transfer_number)

    if not number:
        account_number = str(payload.get("number") or "").strip()
        if account_number:
            _unused_code, _unused_branch, number, digit = _parse_transfer_number(account_number)

    return bank_code, branch, number, digit


def _similar_local_accounts(
    *,
    bank: Bank,
    branch: str,
    number: str,
    digit: str,
    exclude_account_id: int | None = None,
) -> list[tuple[Account, int, str]]:
    remote_branch, remote_number = _normalized_account_identity(branch, number, digit)
    if not remote_number:
        return []

    results: list[tuple[Account, int, str]] = []
    queryset = Account.objects.filter(bank=bank).order_by("-is_active", "id")
    if exclude_account_id:
        queryset = queryset.exclude(pk=exclude_account_id)

    for candidate in queryset:
        local_branch, local_number = _normalized_account_identity(
            candidate.branch,
            candidate.number,
            candidate.digit,
        )
        if not local_number:
            continue

        score = 0
        reasons: list[str] = []
        if local_number == remote_number:
            score += 75
            reasons.append("mesmo número de conta após normalizar zeros e dígito")
        elif len(local_number) >= 6 and len(remote_number) >= 6 and local_number[-6:] == remote_number[-6:]:
            score += 50
            reasons.append("mesmos 6 dígitos finais da conta")
        else:
            continue

        if local_branch == remote_branch:
            score += 20
            reasons.append("mesma agência")
        elif remote_branch == "0" or local_branch == "0":
            # Ausência de agência em uma das fontes é informação faltante, não
            # evidência de divergência. Quando banco + número/dígito normalizados
            # coincidem exatamente, a conta deve ir para revisão em vez de uma
            # segunda conta ser criada automaticamente.
            score += 15
            reasons.append("agência ausente em uma das fontes")

        if candidate.is_active:
            score += 5
        results.append((candidate, min(score, 100), "; ".join(reasons)))

    return sorted(results, key=lambda row: (-row[1], row[0].pk))


def _apply_holder_to_local_account(
    local_account: Account | None,
    *,
    owner_name: str,
    owner_tax_number: str,
) -> None:
    if local_account is None:
        return
    changed: list[str] = []
    if owner_name and not local_account.holder_name:
        local_account.holder_name = owner_name[:200]
        changed.append("holder_name")
    if owner_tax_number and not local_account.holder_tax_id:
        local_account.holder_tax_id = owner_tax_number[:32]
        changed.append("holder_tax_id")
    if changed:
        local_account.save(update_fields=[*changed, "updated_at"])


def _create_local_account(
    pluggy_account: PluggyAccount,
    payload: dict[str, Any],
    *,
    target_bank: Bank,
    branch: str,
    number: str,
    digit: str,
) -> Account:
    remote_id = pluggy_account.pluggy_account_id
    ofx_id = f"PLUGGY:{remote_id}"
    bank_name = pluggy_account.detected_bank_name or target_bank.name
    account_number = number or f"PLUGGY-{remote_id[:12]}"
    nickname = (
        str(payload.get("marketingName") or payload.get("name") or bank_name)
        .strip()[:120]
        or bank_name[:120]
    )
    return Account.objects.create(
        bank=target_bank,
        nickname=nickname,
        branch=branch,
        number=account_number[:40],
        digit=digit[:10],
        account_type=_account_type(str(payload.get("subtype") or "")),
        currency=str(payload.get("currencyCode") or "BRL")[:3].upper(),
        ofx_account_id=ofx_id,
        holder_name=pluggy_account.owner_name[:200],
        holder_tax_id=pluggy_account.owner_tax_number[:32],
        is_own_account=True,
        is_active=True,
    )


def _resolve_local_account(
    pluggy_account: PluggyAccount,
    payload: dict[str, Any],
) -> LocalAccountResolution:
    remote_id = pluggy_account.pluggy_account_id
    ofx_id = f"PLUGGY:{remote_id}"
    bank_name, bank_code = _bank_identity(pluggy_account.item, payload)
    pluggy_account.detected_bank_name = bank_name
    pluggy_account.detected_bank_code = bank_code

    _raw_code, branch, number, digit = _account_coordinates(payload)

    owner_name = str(payload.get("owner") or "").strip()
    owner_tax_number = str(payload.get("taxNumber") or "").strip()
    pluggy_account.owner_name = owner_name[:200]
    pluggy_account.owner_tax_number = owner_tax_number[:32]

    current = pluggy_account.local_account
    if current is None:
        current = Account.objects.filter(ofx_account_id=ofx_id).select_related("bank").first()

    target_bank, target_bank_created = _get_or_create_bank(name=bank_name, code=bank_code)

    if current is not None:
        owned_account = (
            pluggy_account.local_account_created_by_pluggy
            or _legacy_account_was_created_by_pluggy(pluggy_account, current)
        )
        old_bank = current.bank
        old_bank_owned = (
            pluggy_account.local_bank_created_by_pluggy
            or _bank_known_as_pluggy_created(old_bank)
        )

        reclassified = False
        legacy_bank_removed = False
        if owned_account and current.bank_id != target_bank.pk:
            current.bank = target_bank
            current.is_active = True
            current.save(update_fields=["bank", "is_active", "updated_at"])
            reclassified = True
            legacy_bank_removed = _delete_empty_owned_legacy_bank(old_bank, owned=old_bank_owned)
        elif not current.is_active:
            current.is_active = True
            current.save(update_fields=["is_active", "updated_at"])

        _apply_holder_to_local_account(
            current,
            owner_name=owner_name,
            owner_tax_number=owner_tax_number,
        )

        # A versão anterior podia criar uma conta PLUGGY paralela a uma conta
        # OFX/PDF equivalente (ex.: 00530540-6 x 530540-6). Não fundimos
        # silenciosamente: apresentamos a similaridade para decisão do usuário.
        similar = _similar_local_accounts(
            bank=target_bank,
            branch=branch,
            number=number,
            digit=digit,
            exclude_account_id=current.pk,
        )
        strong = [row for row in similar if row[1] >= 90]
        if owned_account and len(strong) == 1:
            suggestion, score, reason = strong[0]
            pluggy_account.suggested_account = suggestion
            pluggy_account.match_status = PluggyAccount.MatchStatus.REVIEW
            pluggy_account.match_score = score
            pluggy_account.match_reason = reason[:255]
        elif pluggy_account.match_status != PluggyAccount.MatchStatus.MANUAL:
            pluggy_account.suggested_account = None
            pluggy_account.match_score = 0
            pluggy_account.match_reason = ""
            pluggy_account.match_status = (
                PluggyAccount.MatchStatus.AUTO_CREATED
                if owned_account
                else PluggyAccount.MatchStatus.AUTO_LINKED
            )

        if owned_account:
            pluggy_account.local_account_created_by_pluggy = True
            pluggy_account.local_bank_created_by_pluggy = (
                target_bank_created
                or _bank_known_as_pluggy_created(target_bank)
                or (current.bank_id == old_bank.pk and old_bank_owned)
            )

        return LocalAccountResolution(
            account=current,
            bank_created=target_bank_created,
            account_reclassified=reclassified,
            legacy_bank_removed=legacy_bank_removed,
            review_pending=(pluggy_account.match_status == PluggyAccount.MatchStatus.REVIEW),
        )

    # Correspondência literal continua segura para vínculo automático.
    exact = list(
        Account.objects.filter(
            bank=target_bank,
            branch=branch,
            number=number,
            digit=digit,
        )[:2]
    ) if number else []
    if len(exact) == 1:
        account = exact[0]
        if not account.ofx_account_id:
            account.ofx_account_id = ofx_id
            account.save(update_fields=["ofx_account_id", "updated_at"])
        _apply_holder_to_local_account(account, owner_name=owner_name, owner_tax_number=owner_tax_number)
        pluggy_account.match_status = PluggyAccount.MatchStatus.AUTO_LINKED
        pluggy_account.suggested_account = None
        pluggy_account.match_score = 100
        pluggy_account.match_reason = "agência, número e dígito idênticos"
        return LocalAccountResolution(account=account, bank_created=target_bank_created)

    similar = _similar_local_accounts(
        bank=target_bank,
        branch=branch,
        number=number,
        digit=digit,
    )
    strong = [row for row in similar if row[1] >= 90]
    if len(strong) == 1:
        suggestion, score, reason = strong[0]
        pluggy_account.suggested_account = suggestion
        pluggy_account.match_status = PluggyAccount.MatchStatus.REVIEW
        pluggy_account.match_score = score
        pluggy_account.match_reason = reason[:255]
        # Não cria conta duplicada e não importa transações até o usuário
        # decidir entre usar a conta existente ou criar uma separada.
        return LocalAccountResolution(
            account=None,
            bank_created=target_bank_created,
            review_pending=True,
        )

    account = _create_local_account(
        pluggy_account,
        payload,
        target_bank=target_bank,
        branch=branch,
        number=number,
        digit=digit,
    )
    pluggy_account.local_account_created_by_pluggy = True
    pluggy_account.local_bank_created_by_pluggy = (
        target_bank_created or _bank_known_as_pluggy_created(target_bank)
    )
    pluggy_account.match_status = PluggyAccount.MatchStatus.AUTO_CREATED
    pluggy_account.suggested_account = None
    pluggy_account.match_score = 0
    pluggy_account.match_reason = ""
    return LocalAccountResolution(
        account=account,
        account_created=True,
        bank_created=target_bank_created,
    )


def sync_accounts(item: PluggyItem) -> AccountSyncResult:
    try:
        payloads = list_accounts(item.configuration, item.item_id)
    except PluggyApiError as exc:
        if exc.status_code == 404:
            raise PluggyApiError(
                (
                    f"A Pluggy não encontrou as contas do Item {item.item_id}. "
                    "O Item pode ter sido removido, recriado ou não pertencer às "
                    "credenciais atualmente configuradas. Os dados locais foram preservados."
                ),
                status_code=404,
            ) from exc
        raise PluggyApiError(
            f"Falha ao listar as contas do Item {item.item_id}: {exc}",
            status_code=exc.status_code,
        ) from exc
    now = timezone.now()
    result: list[PluggyAccount] = []
    created_local = 0
    created_banks = 0
    reclassified_accounts = 0
    legacy_banks_removed = 0
    reviews_pending = 0
    seen_ids: set[str] = set()

    with db_transaction.atomic():
        for payload in payloads:
            remote_id = str(payload.get("id") or "").strip()
            if not remote_id:
                continue
            seen_ids.add(remote_id)
            bank_data = payload.get("bankData") if isinstance(payload.get("bankData"), dict) else {}
            account, _ = PluggyAccount.objects.update_or_create(
                pluggy_account_id=remote_id,
                defaults={
                    "item": item,
                    "remote_type": str(payload.get("type") or "")[:20],
                    "subtype": str(payload.get("subtype") or "")[:60],
                    "name": str(payload.get("marketingName") or payload.get("name") or "")[:180],
                    "masked_number": str(payload.get("number") or "")[:120],
                    "currency": str(payload.get("currencyCode") or "BRL")[:3].upper(),
                    "balance": _decimal(payload.get("balance")),
                    "bank_data": bank_data,
                    "owner_name": str(payload.get("owner") or "")[:200],
                    "owner_tax_number": str(payload.get("taxNumber") or "")[:32],
                    "is_active": True,
                    "last_seen_at": now,
                },
            )
            if account.remote_type == "BANK":
                resolution = _resolve_local_account(account, payload)
                account.local_account = resolution.account
                account.save(
                    update_fields=[
                        "local_account",
                        "detected_bank_name",
                        "detected_bank_code",
                        "owner_name",
                        "owner_tax_number",
                        "match_status",
                        "suggested_account",
                        "match_score",
                        "match_reason",
                        "local_account_created_by_pluggy",
                        "local_bank_created_by_pluggy",
                        "updated_at",
                    ]
                )
                created_local += int(resolution.account_created)
                created_banks += int(resolution.bank_created)
                reclassified_accounts += int(resolution.account_reclassified)
                legacy_banks_removed += int(resolution.legacy_bank_removed)
                reviews_pending += int(resolution.review_pending)
            result.append(account)

        if seen_ids:
            item.accounts.exclude(pluggy_account_id__in=seen_ids).update(is_active=False)

    return AccountSyncResult(
        accounts=tuple(result),
        local_accounts_created=created_local,
        local_banks_created=created_banks,
        local_accounts_reclassified=reclassified_accounts,
        legacy_banks_removed=legacy_banks_removed,
        reviews_pending=reviews_pending,
    )


def resolve_account_similarity(
    pluggy_account: PluggyAccount,
    *,
    action: str,
) -> Account:
    """Aplica a decisão explícita do usuário sobre uma conta semelhante."""
    pluggy_account = PluggyAccount.objects.select_related(
        "local_account", "local_account__bank", "suggested_account", "suggested_account__bank"
    ).get(pk=pluggy_account.pk)

    with db_transaction.atomic():
        if action == "use_existing":
            target = pluggy_account.suggested_account
            if target is None:
                raise ValueError("Não há conta existente sugerida para este vínculo.")
            source = pluggy_account.local_account
            moved_ids: list[int] = []
            if source is not None and source.pk != target.pk and pluggy_account.local_account_created_by_pluggy:
                linked_ids = list(
                    pluggy_account.transaction_links.exclude(transaction=None).values_list("transaction_id", flat=True)
                )
                for tx in Transaction.objects.filter(pk__in=linked_ids):
                    tx.account = target
                    tx.save(update_fields=["account", "updated_at"])
                    moved_ids.append(tx.pk)
                InternalTransfer.objects.filter(
                    Q(debit_transaction_id__in=moved_ids) | Q(credit_transaction_id__in=moved_ids)
                ).delete()

            _apply_holder_to_local_account(
                target,
                owner_name=pluggy_account.owner_name,
                owner_tax_number=pluggy_account.owner_tax_number,
            )
            pluggy_account.local_account = target
            pluggy_account.suggested_account = None
            pluggy_account.match_status = PluggyAccount.MatchStatus.MANUAL
            pluggy_account.match_score = 100
            pluggy_account.match_reason = "conta existente escolhida pelo usuário"
            pluggy_account.local_account_created_by_pluggy = False
            pluggy_account.local_bank_created_by_pluggy = False
            pluggy_account.save(update_fields=[
                "local_account", "suggested_account", "match_status", "match_score",
                "match_reason", "local_account_created_by_pluggy", "local_bank_created_by_pluggy", "updated_at"
            ])

            if source is not None and source.pk != target.pk and not source.transactions.exists() and not source.import_statements.exists():
                try:
                    source.delete()
                except ProtectedError:
                    pass

            if moved_ids:
                db_transaction.on_commit(lambda: analyze_duplicates(transaction_ids=moved_ids), robust=True)
                db_transaction.on_commit(lambda: analyze_internal_transfers(transaction_ids=moved_ids), robust=True)
            return target

        if action == "keep_separate":
            if pluggy_account.local_account_id:
                pluggy_account.suggested_account = None
                pluggy_account.match_status = PluggyAccount.MatchStatus.KEPT_NEW
                pluggy_account.match_score = 0
                pluggy_account.match_reason = "conta separada confirmada pelo usuário"
                pluggy_account.save(update_fields=[
                    "suggested_account", "match_status", "match_score", "match_reason", "updated_at"
                ])
                return pluggy_account.local_account

            bank = None
            if pluggy_account.detected_bank_code:
                bank = Bank.objects.filter(code=pluggy_account.detected_bank_code).first()
            if bank is None:
                bank = Bank.objects.filter(name__iexact=pluggy_account.detected_bank_name).first()
            if bank is None:
                bank, created = _get_or_create_bank(
                    name=pluggy_account.detected_bank_name or "Pluggy / Open Finance",
                    code=pluggy_account.detected_bank_code,
                )
                pluggy_account.local_bank_created_by_pluggy = created

            payload = {
                "marketingName": pluggy_account.name,
                "name": pluggy_account.name,
                "number": pluggy_account.masked_number,
                "subtype": pluggy_account.subtype,
                "currencyCode": pluggy_account.currency,
                "bankData": pluggy_account.bank_data or {},
            }
            _code, branch, number, digit = _account_coordinates(payload)
            account = _create_local_account(
                pluggy_account,
                payload,
                target_bank=bank,
                branch=branch,
                number=number,
                digit=digit,
            )
            pluggy_account.local_account = account
            pluggy_account.local_account_created_by_pluggy = True
            pluggy_account.suggested_account = None
            pluggy_account.match_status = PluggyAccount.MatchStatus.KEPT_NEW
            pluggy_account.match_score = 0
            pluggy_account.match_reason = "nova conta confirmada pelo usuário"
            pluggy_account.save(update_fields=[
                "local_account", "local_account_created_by_pluggy", "local_bank_created_by_pluggy",
                "suggested_account", "match_status", "match_score", "match_reason", "updated_at"
            ])
            return account

    raise ValueError("Decisão de similaridade inválida.")


def upsert_accounts(item: PluggyItem) -> tuple[list[PluggyAccount], int]:
    """Backward-compatible wrapper used by existing tests and callers."""
    result = sync_accounts(item)
    return list(result.accounts), result.local_accounts_created


def _transaction_type(description: str, category: str = "") -> str:
    text = f"{description} {category}".upper()
    if "PIX" in text:
        return Transaction.TransactionType.PIX
    if "TED" in text:
        return Transaction.TransactionType.TED
    if "DOC" in text:
        return Transaction.TransactionType.DOC
    if "TARIF" in text or "FEE" in text:
        return Transaction.TransactionType.FEE
    if "JURO" in text or "INTEREST" in text:
        return Transaction.TransactionType.INTEREST
    if "SAQUE" in text or "WITHDRAW" in text:
        return Transaction.TransactionType.CASH_WITHDRAWAL
    if "DEPOS" in text:
        return Transaction.TransactionType.CASH_DEPOSIT
    if "ESTORNO" in text or "REFUND" in text:
        return Transaction.TransactionType.REFUND
    if "PAGAMENTO" in text or "PAYMENT" in text:
        return Transaction.TransactionType.PAYMENT
    if "TRANSFER" in text:
        return Transaction.TransactionType.TRANSFER
    return Transaction.TransactionType.OTHER


def _remote_canonical(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": payload.get("id"),
        "providerId": payload.get("providerId"),
        "date": payload.get("date"),
        "description": payload.get("description"),
        "descriptionRaw": payload.get("descriptionRaw"),
        "amount": payload.get("amount"),
        "type": payload.get("type"),
        "status": payload.get("status"),
        "currencyCode": payload.get("currencyCode"),
        "balance": payload.get("balance"),
        "category": payload.get("category"),
        "categoryId": payload.get("categoryId"),
        "providerCode": payload.get("providerCode"),
        "paymentData": payload.get("paymentData"),
        "creditCardMetadata": payload.get("creditCardMetadata"),
        "operationType": payload.get("operationType"),
        "operationTypeAdditionalInfo": payload.get("operationTypeAdditionalInfo"),
        "merchant": payload.get("merchant"),
    }


def _remote_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(_remote_canonical(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _expected_values(payload: dict[str, Any]):
    posted_at = _dt(payload.get("date"))
    amount_signed = _decimal(payload.get("amount"))
    if posted_at is None or amount_signed is None or amount_signed == 0:
        return None
    tx_type = str(payload.get("type") or "").upper()
    if tx_type == "CREDIT":
        direction = Transaction.Direction.CREDIT
    elif tx_type == "DEBIT":
        direction = Transaction.Direction.DEBIT
    else:
        direction = Transaction.Direction.CREDIT if amount_signed > 0 else Transaction.Direction.DEBIT
    description = str(payload.get("descriptionRaw") or payload.get("description") or "").strip()
    return posted_at, abs(amount_signed), direction, description


def _payment_counterparty_hint(
    payload: dict[str, Any],
    direction: str,
) -> tuple[str, str, str]:
    payment_data = payload.get("paymentData")
    if not isinstance(payment_data, dict):
        return "", "", ""

    # Para saída, a outra parte é o recebedor. Para entrada, é o pagador.
    participant_key = "receiver" if direction == Transaction.Direction.DEBIT else "payer"
    participant = payment_data.get(participant_key)
    if not isinstance(participant, dict):
        return "", "", ""

    name = str(participant.get("name") or "").strip()
    document = participant.get("documentNumber")
    if isinstance(document, dict):
        tax_id = str(document.get("value") or "").strip()
    else:
        tax_id = str(document or "").strip()
    bank_identifier = str(
        participant.get("routingNumberISPB")
        or participant.get("routingNumber")
        or ""
    ).strip()
    return name[:255], tax_id[:32], bank_identifier[:64]


def _resolve_pluggy_counterparty(transaction: Transaction, payload: dict[str, Any]) -> None:
    name, tax_id, bank_identifier = _payment_counterparty_hint(payload, transaction.direction)
    if name:
        resolve_transaction_counterparty_from_hint(
            transaction,
            name=name,
            tax_id=tax_id,
            bank_identifier=bank_identifier,
            source="Pluggy paymentData",
        )
    else:
        resolve_transaction_counterparty(transaction)


def _conflict_fields(transaction: Transaction, expected) -> list[str]:
    posted_at, amount, direction, description = expected
    fields = []
    if transaction.posted_at.replace(microsecond=0) != posted_at.replace(microsecond=0):
        fields.append("data")
    if transaction.amount != amount:
        fields.append("valor")
    if transaction.direction != direction:
        fields.append("natureza")
    if " ".join(transaction.raw_description.split()) != " ".join(description.split()):
        fields.append("descrição")
    return fields


def sync_account_transactions(
    pluggy_account: PluggyAccount,
    *,
    user=None,
) -> dict[str, int]:
    if pluggy_account.remote_type != "BANK" or not pluggy_account.local_account_id:
        return {
            "seen": 0,
            "created": 0,
            "existing": 0,
            "pending": 0,
            "conflicts": 0,
            "duplicate_reviews": 0,
            "duplicates_quarantined": 0,
        }

    try:
        payloads = list_all_transactions(
            pluggy_account.item.configuration,
            pluggy_account.pluggy_account_id,
        )
    except PluggyApiError as exc:
        account_label = pluggy_account.name or pluggy_account.pluggy_account_id
        if exc.status_code == 404:
            raise PluggyApiError(
                (
                    f"A Pluggy não encontrou as transações da conta {account_label} "
                    f"(Account ID {pluggy_account.pluggy_account_id}). "
                    "Os movimentos já copiados no Financeiro OFX permanecem preservados."
                ),
                status_code=404,
            ) from exc
        raise PluggyApiError(
            f"Falha ao listar transações da conta {account_label}: {exc}",
            status_code=exc.status_code,
        ) from exc
    now = timezone.now()
    stats = {
        "seen": 0,
        "created": 0,
        "existing": 0,
        "pending": 0,
        "conflicts": 0,
        "duplicate_reviews": 0,
        "duplicates_quarantined": 0,
    }
    created_ids: list[int] = []

    for payload in payloads:
        remote_id = str(payload.get("id") or "").strip()
        if not remote_id:
            continue
        stats["seen"] += 1
        status = str(payload.get("status") or "POSTED").upper()
        if status != "POSTED":
            stats["pending"] += 1
            continue

        expected = _expected_values(payload)
        if expected is None:
            continue
        provider_id = str(payload.get("providerId") or "").strip()[:255]
        link = PluggyTransactionLink.objects.filter(
            pluggy_account=pluggy_account,
            remote_transaction_id=remote_id,
        ).select_related("transaction").first()
        if link is None and provider_id:
            link = PluggyTransactionLink.objects.filter(
                pluggy_account=pluggy_account,
                provider_id=provider_id,
            ).select_related("transaction").first()

        remote_hash = _remote_hash(payload)
        if link and link.transaction_id:
            conflicts = _conflict_fields(link.transaction, expected)
            link.remote_transaction_id = remote_id
            link.provider_id = provider_id
            link.remote_hash = remote_hash
            link.has_conflict = bool(conflicts)
            link.conflict_fields = conflicts
            link.last_seen_at = now
            link.save()
            if conflicts:
                stats["conflicts"] += 1
            else:
                stats["existing"] += 1
            if not link.transaction.counterparty_id:
                _resolve_pluggy_counterparty(link.transaction, payload)
            continue

        posted_at, amount, direction, description = expected
        fitid = (
            f"PLUGGY-PROVIDER:{provider_id}"
            if provider_id
            else f"PLUGGY:{remote_id}"
        )[:255]
        transaction = Transaction.objects.filter(
            account=pluggy_account.local_account,
            fitid=fitid,
        ).first()
        if transaction is not None:
            stats["existing"] += 1
        else:
            tx_type = _transaction_type(description, str(payload.get("category") or ""))
            signed_amount = amount if direction == Transaction.Direction.CREDIT else -amount
            fingerprint = build_fingerprint(
                account_id=pluggy_account.local_account_id,
                posted_at=posted_at,
                signed_amount=signed_amount,
                transaction_type=tx_type,
                description=description,
                document=str(payload.get("providerCode") or "")[:120],
                reference=provider_id or remote_id,
            )
            transaction = Transaction.objects.create(
                account=pluggy_account.local_account,
                posted_at=posted_at,
                competence_date=timezone.localtime(posted_at).date(),
                amount=amount,
                direction=direction,
                transaction_type=tx_type,
                source_type=Transaction.SourceType.API,
                fitid=fitid,
                raw_description=description or str(payload.get("description") or "Pluggy"),
                normalized_description=" ".join(str(payload.get("description") or description).split()),
                document=str(payload.get("providerCode") or "")[:120],
                reference=(provider_id or remote_id)[:255],
                fingerprint=fingerprint,
                fingerprint_version=1,
                raw_data={"provider": "PLUGGY", "pluggy": _remote_canonical(payload)},
                notes="Importado automaticamente via Pluggy / Open Finance.",
                created_by=user,
            )
            _resolve_pluggy_counterparty(transaction, payload)
            created_ids.append(transaction.pk)
            stats["created"] += 1

        if link is not None:
            link.remote_transaction_id = remote_id
            link.provider_id = provider_id
            link.transaction = transaction
            link.remote_hash = remote_hash
            link.has_conflict = False
            link.conflict_fields = []
            link.last_seen_at = now
            link.save()
        else:
            PluggyTransactionLink.objects.create(
                pluggy_account=pluggy_account,
                remote_transaction_id=remote_id,
                provider_id=provider_id,
                transaction=transaction,
                remote_hash=remote_hash,
                has_conflict=False,
                conflict_fields=[],
                last_seen_at=now,
            )

    if created_ids:
        analyze_duplicates(transaction_ids=created_ids, quarantine_new=True)
        stats["duplicate_reviews"] = (
            TransactionDuplicateReview.objects.filter(
                status=TransactionDuplicateReview.Status.PENDING,
            )
            .filter(
                Q(first_transaction_id__in=created_ids)
                | Q(second_transaction_id__in=created_ids)
            )
            .count()
        )
        stats["duplicates_quarantined"] = Transaction.objects.filter(
            pk__in=created_ids,
            is_financially_ignored=True,
        ).count()
        analyze_internal_transfers(transaction_ids=created_ids)
    return stats


def sync_item(item: PluggyItem, *, user=None) -> SyncResult:
    item = refresh_item(item)
    identity_data = retrieve_identity(item.configuration, item.item_id)
    item.identity_data = identity_data
    item.save(update_fields=["identity_data", "updated_at"])

    account_result = sync_accounts(item)

    identity_name = str(
        identity_data.get("fullName")
        or identity_data.get("companyName")
        or ""
    ).strip()
    identity_tax = str(
        identity_data.get("document")
        or identity_data.get("taxNumber")
        or ""
    ).strip()
    if identity_name or identity_tax:
        for remote_account in account_result.accounts:
            if remote_account.local_account_id:
                _apply_holder_to_local_account(
                    remote_account.local_account,
                    owner_name=remote_account.owner_name or identity_name,
                    owner_tax_number=remote_account.owner_tax_number or identity_tax,
                )

    totals = {
        "seen": 0,
        "created": 0,
        "existing": 0,
        "pending": 0,
        "conflicts": 0,
        "duplicate_reviews": 0,
        "duplicates_quarantined": 0,
    }
    for account in account_result.accounts:
        stats = sync_account_transactions(account, user=user)
        for key in totals:
            totals[key] += stats[key]

    item.last_sync_at = timezone.now()
    item.last_error = ""
    item.last_sync_summary = {
        "accounts": len(account_result.accounts),
        "accounts_created": account_result.local_accounts_created,
        "banks_created": account_result.local_banks_created,
        "accounts_reclassified": account_result.local_accounts_reclassified,
        "account_reviews_pending": account_result.reviews_pending,
        "transactions_seen": totals["seen"],
        "transactions_created": totals["created"],
        "transactions_existing": totals["existing"],
        "pending_skipped": totals["pending"],
        "conflicts": totals["conflicts"],
        "duplicate_reviews_pending": totals["duplicate_reviews"],
        "duplicates_quarantined": totals["duplicates_quarantined"],
    }
    item.save(update_fields=["last_sync_at", "last_error", "last_sync_summary", "updated_at"])
    return SyncResult(
        items=1,
        accounts=len(account_result.accounts),
        accounts_created=account_result.local_accounts_created,
        banks_created=account_result.local_banks_created,
        accounts_reclassified=account_result.local_accounts_reclassified,
        legacy_banks_removed=account_result.legacy_banks_removed,
        transactions_seen=totals["seen"],
        transactions_created=totals["created"],
        transactions_existing=totals["existing"],
        pending_skipped=totals["pending"],
        conflicts=totals["conflicts"],
        account_reviews_pending=account_result.reviews_pending,
        duplicate_reviews_pending=totals["duplicate_reviews"],
        duplicates_quarantined=totals["duplicates_quarantined"],
    )

