from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class ParsedTransaction:
    fitid: str
    posted_at: datetime
    amount: Decimal
    transaction_type: str
    memo: str
    payee: str
    checknum: str
    reference: str
    raw: dict[str, Any]
    posted_at_raw: str = ""
    posted_at_has_time: bool = True
    user_at_raw: str = ""

    @property
    def is_credit(self) -> bool:
        return self.amount > 0

    @property
    def is_debit(self) -> bool:
        return self.amount < 0

    @property
    def direction(self) -> str:
        if self.is_credit:
            return "CREDIT"
        if self.is_debit:
            return "DEBIT"
        return "ZERO"

    @property
    def absolute_amount(self) -> Decimal:
        return abs(self.amount)

    @property
    def description(self) -> str:
        parts = [
            self.payee.strip(),
            self.memo.strip(),
        ]
        return " - ".join(part for part in parts if part)


@dataclass(frozen=True, slots=True)
class ParsedStatement:
    bank_id: str
    bank_name: str
    branch_id: str
    account_id: str
    account_type: str
    currency: str
    start: datetime | None
    end: datetime | None
    ledger_balance: Decimal | None
    transactions: tuple[ParsedTransaction, ...]

    @property
    def transaction_count(self) -> int:
        return len(self.transactions)

    @property
    def total_credits(self) -> Decimal:
        return sum(
            (
                transaction.amount
                for transaction in self.transactions
                if transaction.amount > 0
            ),
            Decimal("0.00"),
        )

    @property
    def total_debits(self) -> Decimal:
        return sum(
            (
                abs(transaction.amount)
                for transaction in self.transactions
                if transaction.amount < 0
            ),
            Decimal("0.00"),
        )


@dataclass(frozen=True, slots=True)
class ParsedOfxFile:
    version: int | str | None
    encoding: str
    statements: tuple[ParsedStatement, ...]

    @property
    def transaction_count(self) -> int:
        return sum(
            statement.transaction_count
            for statement in self.statements
        )

    @property
    def all_transactions(self) -> tuple[ParsedTransaction, ...]:
        return tuple(
            transaction
            for statement in self.statements
            for transaction in statement.transactions
        )
