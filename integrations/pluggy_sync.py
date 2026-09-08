from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from finance.models import Account, Bank, Transaction
from services.counterparties.resolver import resolve_transaction_counterparty
from services.importing.staging import build_fingerprint
from services.internal_transfers.matcher import analyze_internal_transfers

from .models import PluggyAccount, PluggyConfiguration, PluggyItem, PluggyTransactionLink
from .pluggy import list_accounts, list_all_transactions, retrieve_item


@dataclass(frozen=True, slots=True)
class SyncResult:
    items: int = 0
    accounts: int = 0
    accounts_created: int = 0
    transactions_seen: int = 0
    transactions_created: int = 0
    transactions_existing: int = 0
    pending_skipped: int = 0
    conflicts: int = 0


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


def _find_or_create_local_account(
    pluggy_account: PluggyAccount,
    payload: dict[str, Any],
) -> tuple[Account, bool]:
    remote_id = pluggy_account.pluggy_account_id
    ofx_id = f"PLUGGY:{remote_id}"
    existing = Account.objects.filter(ofx_account_id=ofx_id).first()
    if existing:
        return existing, False

    bank_name = pluggy_account.item.connector_name or "Pluggy / Open Finance"
    bank_data = payload.get("bankData") if isinstance(payload.get("bankData"), dict) else {}
    transfer_number = str(bank_data.get("transferNumber") or "")
    bank_code, branch, number, digit = _parse_transfer_number(transfer_number)

    bank = None
    if bank_code and bank_code.isdigit():
        bank = Bank.objects.filter(code=bank_code.zfill(3)).first()
    if bank is None:
        bank = Bank.objects.filter(name__iexact=bank_name).first()
    if bank is None:
        kwargs = {"name": bank_name[:120], "is_active": True}
        if bank_code and bank_code.isdigit() and not Bank.objects.filter(code=bank_code.zfill(3)).exists():
            kwargs["code"] = bank_code.zfill(3)
        bank = Bank.objects.create(**kwargs)

    if number:
        matched = list(
            Account.objects.filter(
                bank=bank,
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
            return account, False

    account_number = number or f"PLUGGY-{remote_id[:12]}"
    nickname = (
        str(payload.get("marketingName") or payload.get("name") or bank_name)
        .strip()[:120]
        or bank_name[:120]
    )
    account = Account.objects.create(
        bank=bank,
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
    return account, True


def upsert_accounts(item: PluggyItem) -> tuple[list[PluggyAccount], int]:
    payloads = list_accounts(item.configuration, item.item_id)
    now = timezone.now()
    result = []
    created_local = 0
    seen_ids = set()
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
        if account.remote_type == "BANK" and account.local_account_id is None:
            local_account, was_created = _find_or_create_local_account(account, payload)
            account.local_account = local_account
            account.save(update_fields=["local_account", "updated_at"])
            created_local += int(was_created)
        result.append(account)

    if seen_ids:
        item.accounts.exclude(pluggy_account_id__in=seen_ids).update(is_active=False)
    return result, created_local


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
    accounts, created_local = upsert_accounts(item)
    totals = {"seen": 0, "created": 0, "existing": 0, "pending": 0, "conflicts": 0}
    for account in accounts:
        stats = sync_account_transactions(account, user=user)
        for key in totals:
            totals[key] += stats[key]
    item.last_sync_at = timezone.now()
    item.last_error = ""
    item.save(update_fields=["last_sync_at", "last_error", "updated_at"])
    return SyncResult(
        items=1,
        accounts=len(accounts),
        accounts_created=created_local,
        transactions_seen=totals["seen"],
        transactions_created=totals["created"],
        transactions_existing=totals["existing"],
        pending_skipped=totals["pending"],
        conflicts=totals["conflicts"],
    )
