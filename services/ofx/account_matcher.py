from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q

from finance.models import Account
from finance.models import Bank

from .models import ParsedStatement


@dataclass(frozen=True, slots=True)
class OfxAccountMatch:
    bank: Bank | None
    account: Account | None
    bank_match_reason: str
    account_match_reason: str

    @property
    def is_complete(self) -> bool:
        return self.bank is not None and self.account is not None


def match_statement(statement: ParsedStatement) -> OfxAccountMatch:
    bank = None
    bank_reason = ""

    bank_id = statement.bank_id.strip()

    if bank_id:
        bank = (
            Bank.objects.filter(
                Q(ofx_bank_id=bank_id) | Q(code=bank_id)
            )
            .order_by("-is_active", "name")
            .first()
        )

        if bank:
            if bank.ofx_bank_id == bank_id:
                bank_reason = "BANKID"
            elif bank.code == bank_id:
                bank_reason = "COMPE"

    if bank is None and statement.bank_name.strip():
        bank = (
            Bank.objects.filter(
                name__iexact=statement.bank_name.strip()
            )
            .order_by("-is_active", "name")
            .first()
        )

        if bank:
            bank_reason = "Nome do banco"

    account = None
    account_reason = ""

    account_id = statement.account_id.strip()

    if bank and account_id:
        account = (
            Account.objects.filter(bank=bank)
            .filter(
                Q(ofx_account_id=account_id)
                | Q(number=account_id)
            )
            .order_by("-is_active", "nickname")
            .first()
        )

        if account:
            if account.ofx_account_id == account_id:
                account_reason = "ACCTID"
            elif account.number == account_id:
                account_reason = "Número da conta"

    return OfxAccountMatch(
        bank=bank,
        account=account,
        bank_match_reason=bank_reason,
        account_match_reason=account_reason,
    )
