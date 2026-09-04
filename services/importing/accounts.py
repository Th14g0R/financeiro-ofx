from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.db.models import Q

from finance.models import Account
from finance.models import Bank
from imports.models import ImportStatement
from services.importing.staging import reclassify_statement


def map_ofx_account_type(value: str) -> str:
    normalized = (value or "").strip().upper()

    mapping = {
        "CHECKING": Account.AccountType.CHECKING,
        "CHECK": Account.AccountType.CHECKING,
        "SAVINGS": Account.AccountType.SAVINGS,
        "SAVING": Account.AccountType.SAVINGS,
        "PAYMENT": Account.AccountType.PAYMENT,
        "PAYMENT_ACCOUNT": Account.AccountType.PAYMENT,
        "DIGITAL_WALLET": Account.AccountType.PAYMENT,
        "MONEYMRKT": Account.AccountType.INVESTMENT,
        "CD": Account.AccountType.INVESTMENT,
    }

    return mapping.get(
        normalized,
        Account.AccountType.OTHER,
    )


def suggested_account_values(
    statement: ImportStatement,
) -> dict:
    bank_name = (
        statement.matched_bank.name
        if statement.matched_bank
        else (
            statement.bank_name.strip()
            or (
                f"Banco OFX {statement.bank_id}"
                if statement.bank_id
                else "Banco OFX"
            )
        )
    )

    account_suffix = (
        statement.account_id[-4:]
        if statement.account_id
        else ""
    )

    nickname = (
        f"Conta {account_suffix}"
        if account_suffix
        else "Conta principal"
    )

    bank_code = (
        statement.matched_bank.code
        if statement.matched_bank
        else (
            statement.bank_id
            if statement.bank_id.isdigit()
            and len(statement.bank_id) <= 3
            else ""
        )
    )

    return {
        "bank_name": bank_name,
        "bank_code": bank_code,
        "bank_ofx_id": (
            statement.matched_bank.ofx_bank_id
            if statement.matched_bank
            else statement.bank_id
        ),
        "nickname": nickname,
        "branch": statement.branch_id,
        "number": statement.account_id,
        "account_type": map_ofx_account_type(
            statement.account_type
        ),
        "currency": statement.currency or "BRL",
        "commit_after_create": True,
    }


@db_transaction.atomic
def create_and_assign_account_from_ofx(
    *,
    statement: ImportStatement,
    cleaned_data: dict,
) -> Account:
    bank = statement.matched_bank

    bank_name = cleaned_data["bank_name"].strip()
    bank_code = cleaned_data["bank_code"].strip()
    bank_ofx_id = cleaned_data["bank_ofx_id"].strip()

    if bank is None:
        bank = (
            Bank.objects.filter(
                Q(ofx_bank_id=bank_ofx_id)
                if bank_ofx_id
                else Q(pk__isnull=True)
            )
            .order_by("-is_active", "name")
            .first()
        )

    if bank is None and bank_code:
        bank = Bank.objects.filter(
            code=bank_code
        ).first()

    if bank is None:
        bank = Bank.objects.filter(
            name__iexact=bank_name
        ).first()

    if bank is None:
        bank = Bank(
            name=bank_name,
            code=bank_code,
            ofx_bank_id=bank_ofx_id,
            is_active=True,
        )
        bank.full_clean()
        bank.save()
    else:
        changed_fields = []

        if not bank.ofx_bank_id and bank_ofx_id:
            conflict = Bank.objects.filter(
                ofx_bank_id=bank_ofx_id
            ).exclude(pk=bank.pk).exists()

            if not conflict:
                bank.ofx_bank_id = bank_ofx_id
                changed_fields.append("ofx_bank_id")

        if not bank.code and bank_code:
            conflict = Bank.objects.filter(
                code=bank_code
            ).exclude(pk=bank.pk).exists()

            if not conflict:
                bank.code = bank_code
                changed_fields.append("code")

        if changed_fields:
            bank.full_clean()
            bank.save(
                update_fields=[
                    *changed_fields,
                    "updated_at",
                ]
            )

    account = None

    if statement.account_id:
        account = Account.objects.filter(
            bank=bank,
            ofx_account_id=statement.account_id,
        ).first()

    if account is None:
        account = Account.objects.filter(
            bank=bank,
            branch=cleaned_data["branch"].strip(),
            number=cleaned_data["number"].strip(),
            digit="",
        ).first()

    if account is None:
        account = Account(
            bank=bank,
            nickname=cleaned_data["nickname"].strip(),
            branch=cleaned_data["branch"].strip(),
            number=cleaned_data["number"].strip(),
            digit="",
            account_type=cleaned_data["account_type"],
            currency=cleaned_data["currency"],
            ofx_account_id=statement.account_id,
            is_active=True,
        )

        try:
            account.full_clean()
        except ValidationError:
            raise

        account.save()
    elif statement.account_id and not account.ofx_account_id:
        conflict = Account.objects.filter(
            bank=bank,
            ofx_account_id=statement.account_id,
        ).exclude(pk=account.pk).exists()

        if not conflict:
            account.ofx_account_id = statement.account_id
            account.full_clean()
            account.save(
                update_fields=[
                    "ofx_account_id",
                    "updated_at",
                ]
            )

    statement.matched_bank = bank
    statement.matched_account = account
    statement.match_method = ImportStatement.MatchMethod.MANUAL
    statement.save(
        update_fields=[
            "matched_bank",
            "matched_account",
            "match_method",
        ]
    )

    reclassify_statement(statement)

    return account
