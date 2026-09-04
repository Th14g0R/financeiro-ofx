from __future__ import annotations

from finance.models import Transaction

from .models import ParsedTransaction


OFX_TRANSACTION_TYPE_MAP: dict[str, str] = {
    "CREDIT": Transaction.TransactionType.OTHER,
    "DEBIT": Transaction.TransactionType.OTHER,
    "INT": Transaction.TransactionType.INTEREST,
    "FEE": Transaction.TransactionType.FEE,
    "SRVCHG": Transaction.TransactionType.FEE,
    "DEP": Transaction.TransactionType.CASH_DEPOSIT,
    "ATM": Transaction.TransactionType.CASH_WITHDRAWAL,
    "CASH": Transaction.TransactionType.CASH_WITHDRAWAL,
    "XFER": Transaction.TransactionType.TRANSFER,
    "PAYMENT": Transaction.TransactionType.PAYMENT,
}


def map_direction(transaction: ParsedTransaction) -> str:
    if transaction.amount > 0:
        return Transaction.Direction.CREDIT

    return Transaction.Direction.DEBIT


def map_transaction_type(transaction: ParsedTransaction) -> str:
    source_type = transaction.transaction_type.strip().upper()

    description = transaction.description.upper()

    if "PIX" in description:
        return Transaction.TransactionType.PIX

    if "TED" in description:
        return Transaction.TransactionType.TED

    if " DOC " in f" {description} ":
        return Transaction.TransactionType.DOC

    return OFX_TRANSACTION_TYPE_MAP.get(
        source_type,
        Transaction.TransactionType.OTHER,
    )
