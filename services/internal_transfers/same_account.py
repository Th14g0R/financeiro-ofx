from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from django.db import transaction as db_transaction
from django.db.models import Q

from finance.models import InternalTransfer
from finance.models import Transaction


_POCKET_MARKERS = (
    "COFRINHO",
    "COFRINHOS",
    "COFRE",
    "DINHEIRO GUARDADO",
    "GUARDAR DINHEIRO",
    "RESERVAR DINHEIRO",
    "DINHEIRO RESERVADO",
    "RESERVA AUTOMATICA",
    "TRANSFERENCIA PARA COFRINHO",
    "TRANSFERENCIA PRO COFRINHO",
    "TRANSFERENCIA DO COFRINHO",
    "TRANSFERENCIA DE COFRINHO",
    "DEPOSITO NO COFRINHO",
    "RETIRADA DO COFRINHO",
    "RETIRAR DO COFRINHO",
    "RESGATE DO COFRINHO",
    "RESGATE DE COFRINHO",
)

_YIELD_MARKERS = (
    "RENDIMENTO",
    "RENDIMENTOS",
    "RENTABILIDADE",
    "JUROS",
    "INTEREST",
    " CDI ",
)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " " + re.sub(r"[^A-Za-z0-9]+", " ", ascii_text).upper().strip() + " "


def _payload_text(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    payment_data = payload.get("paymentData")
    payment_reason = payment_data.get("reason") if isinstance(payment_data, dict) else ""
    values = (
        payload.get("description"),
        payload.get("descriptionRaw"),
        payload.get("category"),
        payload.get("operationType"),
        payload.get("operationTypeAdditionalInfo"),
        payment_reason,
    )
    return " ".join(str(value or "") for value in values)


def _has_reserved_balance_evidence(transaction: Transaction, pluggy_account=None) -> bool:
    account = pluggy_account
    if account is None:
        try:
            from integrations.models import PluggyTransactionLink

            link = (
                PluggyTransactionLink.objects.filter(transaction=transaction)
                .select_related("pluggy_account")
                .first()
            )
            account = link.pluggy_account if link else None
        except Exception:
            account = None

    bank_data = getattr(account, "bank_data", None) if account is not None else None
    if not isinstance(bank_data, dict):
        return False
    return bool(bank_data.get("hasReservedBalance") or bank_data.get("reservedBalances"))


def classify_internal_balance_movement(
    transaction: Transaction,
    *,
    pluggy_account=None,
    payload: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Identify movements between available balance and an internal pocket/reserve.

    A yield/interest credit is deliberately *not* classified as an internal movement:
    it increases the user's wealth and should remain in external income totals.
    """
    source_payload = payload
    if source_payload is None:
        raw_data = transaction.raw_data if isinstance(transaction.raw_data, dict) else {}
        source_payload = raw_data.get("pluggy") if isinstance(raw_data.get("pluggy"), dict) else {}

    text = _normalize(
        " ".join(
            [
                transaction.raw_description or "",
                transaction.normalized_description or "",
                _payload_text(source_payload),
            ]
        )
    )

    if any(marker in text for marker in _YIELD_MARKERS):
        return False, ""

    marker = next((item for item in _POCKET_MARKERS if item in text), "")
    if marker:
        return True, f"Movimentação entre saldo disponível e reserva/cofrinho ({marker.title()})."

    # Some institutions expose the reserve capability but use a compact generic
    # label such as "Reserva". Only accept that weak label when the account itself
    # confirms reserved balances, reducing false positives with merchant names.
    if _has_reserved_balance_evidence(transaction, pluggy_account=pluggy_account):
        if " RESERVA " in text and any(
            token in text
            for token in (" TRANSFERENCIA ", " SALDO ", " APLICACAO ", " RESGATE ", " RETIRADA ", " DEPOSITO ")
        ):
            return True, "Movimentação entre saldo disponível e reserva interna da própria conta."

    return False, ""


@db_transaction.atomic
def apply_internal_balance_classification(
    transaction: Transaction,
    *,
    pluggy_account=None,
    payload: dict[str, Any] | None = None,
) -> bool:
    detected, reason = classify_internal_balance_movement(
        transaction,
        pluggy_account=pluggy_account,
        payload=payload,
    )
    changed = (
        transaction.is_internal_balance_movement != detected
        or transaction.internal_balance_reason != reason
    )
    if changed:
        transaction.is_internal_balance_movement = detected
        transaction.internal_balance_reason = reason[:255]
        transaction.save(
            update_fields=[
                "is_internal_balance_movement",
                "internal_balance_reason",
                "updated_at",
            ]
        )

    if detected:
        # A movement inside the same account balance (e.g. available balance ↔
        # Cofrinho) cannot simultaneously be a transfer between two local own
        # accounts. Remove stale/previous cross-account suggestions safely.
        InternalTransfer.objects.filter(
            Q(debit_transaction_id=transaction.pk)
            | Q(credit_transaction_id=transaction.pk)
        ).delete()

    return detected


def analyze_internal_balance_movements(
    *,
    transaction_ids: Iterable[int] | None = None,
) -> dict[str, int]:
    queryset = Transaction.objects.filter(source_type=Transaction.SourceType.API)
    if transaction_ids is not None:
        queryset = queryset.filter(pk__in=list(transaction_ids))

    analyzed = 0
    detected = 0
    cleared = 0
    for transaction in queryset.iterator():
        analyzed += 1
        was_internal = transaction.is_internal_balance_movement
        is_internal = apply_internal_balance_classification(transaction)
        if is_internal:
            detected += 1
        elif was_internal:
            cleared += 1
    return {"analyzed": analyzed, "detected": detected, "cleared": cleared}
