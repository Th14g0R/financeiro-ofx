from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any

from django.db import transaction as db_transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from finance.models import Account, Bank, Transaction
from services.counterparties.resolver import resolve_transaction_counterparty
from services.importing.staging import build_fingerprint
from services.internal_transfers.matcher import analyze_internal_transfers

from .models import PluggyAccount, PluggyConfiguration, PluggyItem, PluggyTransactionLink
from .pluggy import MEU_PLUGGY_CONNECTOR_ID, list_accounts, list_all_transactions, retrieve_item


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


@dataclass(frozen=True, slots=True)
class AccountSyncResult:
    accounts: tuple[PluggyAccount, ...]
    local_accounts_created: int = 0
    local_banks_created: int = 0
    local_accounts_reclassified: int = 0
    legacy_banks_removed: int = 0


@dataclass(frozen=True, slots=True)
class LocalAccountResolution:
    account: Account
    account_created: bool = False
    bank_created: bool = False
    account_reclassified: bool = False
    legacy_bank_removed: bool = False


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
    payload = retrieve_item(item.configuration, item.item_id)
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
    bank_data = payload.get("bankData") if isinstance(payload.get("bankData"), dict) else {}
    transfer_number = str(bank_data.get("transferNumber") or "")
    bank_code, _branch, _number, _digit = _parse_transfer_number(transfer_number)
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


def _resolve_local_account(
    pluggy_account: PluggyAccount,
    payload: dict[str, Any],
) -> LocalAccountResolution:
    remote_id = pluggy_account.pluggy_account_id
    ofx_id = f"PLUGGY:{remote_id}"
    bank_name, bank_code = _bank_identity(pluggy_account.item, payload)
    pluggy_account.detected_bank_name = bank_name
    pluggy_account.detected_bank_code = bank_code

    bank_data = payload.get("bankData") if isinstance(payload.get("bankData"), dict) else {}
    transfer_number = str(bank_data.get("transferNumber") or "")
    _raw_code, branch, number, digit = _parse_transfer_number(transfer_number)

    current = pluggy_account.local_account
    if current is None:
        current = Account.objects.filter(ofx_account_id=ofx_id).select_related("bank").first()

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
        bank_created = False
        legacy_bank_removed = False
        if owned_account:
            target_bank, bank_created = _get_or_create_bank(name=bank_name, code=bank_code)
            if current.bank_id != target_bank.pk:
                current.bank = target_bank
                current.is_active = True
                current.save(update_fields=["bank", "is_active", "updated_at"])
                reclassified = True
                legacy_bank_removed = _delete_empty_owned_legacy_bank(
                    old_bank,
                    owned=old_bank_owned,
                )
            elif not current.is_active:
                current.is_active = True
                current.save(update_fields=["is_active", "updated_at"])

            pluggy_account.local_account_created_by_pluggy = True
            pluggy_account.local_bank_created_by_pluggy = (
                bank_created
                or _bank_known_as_pluggy_created(target_bank)
                or (current.bank_id == old_bank.pk and old_bank_owned)
            )

        return LocalAccountResolution(
            account=current,
            account_created=False,
            bank_created=bank_created,
            account_reclassified=reclassified,
            legacy_bank_removed=legacy_bank_removed,
        )

    target_bank, bank_created = _get_or_create_bank(name=bank_name, code=bank_code)

    if number:
        matched = list(
            Account.objects.filter(
                bank=target_bank,
                branch=branch,
                number=number,
                digit=digit,
            )[:2]
        )
        if len(matched) == 1:
            account = matched[0]
            if not account.ofx_account_id:
                account.ofx_account_id = ofx_id
                account.save(update_fields=["ofx_account_id", "updated_at"])
            # This is a pre-existing account recognized by banking coordinates;
            # it is linked but not marked as integration-owned.
            return LocalAccountResolution(
                account=account,
                bank_created=bank_created,
            )

    account_number = number or f"PLUGGY-{remote_id[:12]}"
    nickname = (
        str(payload.get("marketingName") or payload.get("name") or bank_name)
        .strip()[:120]
        or bank_name[:120]
    )
    account = Account.objects.create(
        bank=target_bank,
        nickname=nickname,
        branch=branch,
        number=account_number[:40],
        digit=digit[:10],
        account_type=_account_type(str(payload.get("subtype") or "")),
        currency=str(payload.get("currencyCode") or "BRL")[:3].upper(),
        ofx_account_id=ofx_id,
        is_own_account=True,
        is_active=True,
    )
    pluggy_account.local_account_created_by_pluggy = True
    pluggy_account.local_bank_created_by_pluggy = (
        bank_created or _bank_known_as_pluggy_created(target_bank)
    )
    return LocalAccountResolution(
        account=account,
        account_created=True,
        bank_created=bank_created,
    )


def sync_accounts(item: PluggyItem) -> AccountSyncResult:
    payloads = list_accounts(item.configuration, item.item_id)
    now = timezone.now()
    result: list[PluggyAccount] = []
    created_local = 0
    created_banks = 0
    reclassified_accounts = 0
    legacy_banks_removed = 0
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
                        "local_account_created_by_pluggy",
                        "local_bank_created_by_pluggy",
                        "updated_at",
                    ]
                )
                created_local += int(resolution.account_created)
                created_banks += int(resolution.bank_created)
                reclassified_accounts += int(resolution.account_reclassified)
                legacy_banks_removed += int(resolution.legacy_bank_removed)
            result.append(account)

        if seen_ids:
            item.accounts.exclude(pluggy_account_id__in=seen_ids).update(is_active=False)

    return AccountSyncResult(
        accounts=tuple(result),
        local_accounts_created=created_local,
        local_banks_created=created_banks,
        local_accounts_reclassified=reclassified_accounts,
        legacy_banks_removed=legacy_banks_removed,
    )


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
        return {"seen": 0, "created": 0, "existing": 0, "pending": 0, "conflicts": 0}

    payloads = list_all_transactions(
        pluggy_account.item.configuration,
        pluggy_account.pluggy_account_id,
    )
    now = timezone.now()
    stats = {"seen": 0, "created": 0, "existing": 0, "pending": 0, "conflicts": 0}
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
            resolve_transaction_counterparty(transaction)
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
        analyze_internal_transfers(transaction_ids=created_ids)
    return stats


def sync_item(item: PluggyItem, *, user=None) -> SyncResult:
    item = refresh_item(item)
    account_result = sync_accounts(item)
    totals = {"seen": 0, "created": 0, "existing": 0, "pending": 0, "conflicts": 0}
    for account in account_result.accounts:
        stats = sync_account_transactions(account, user=user)
        for key in totals:
            totals[key] += stats[key]
    item.last_sync_at = timezone.now()
    item.last_error = ""
    item.save(update_fields=["last_sync_at", "last_error", "updated_at"])
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
    )
