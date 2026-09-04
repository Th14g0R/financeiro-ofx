from __future__ import annotations

from django.db.models import IntegerField
from django.db.models import Case
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Value
from django.db.models import When

from finance.models import InternalTransfer


def confirmed_internal_q(
    *,
    prefix: str = "",
):
    debit = (
        f"{prefix}"
        "internal_transfer_debit_matches__status"
    )
    credit = (
        f"{prefix}"
        "internal_transfer_credit_matches__status"
    )

    return (
        Q(
            **{
                debit: (
                    InternalTransfer.Status.CONFIRMED
                )
            }
        )
        | Q(
            **{
                credit: (
                    InternalTransfer.Status.CONFIRMED
                )
            }
        )
    )


def possible_internal_q(
    *,
    prefix: str = "",
):
    debit = (
        f"{prefix}"
        "internal_transfer_debit_matches__status"
    )
    credit = (
        f"{prefix}"
        "internal_transfer_credit_matches__status"
    )

    return (
        Q(
            **{
                debit: (
                    InternalTransfer.Status.POSSIBLE
                )
            }
        )
        | Q(
            **{
                credit: (
                    InternalTransfer.Status.POSSIBLE
                )
            }
        )
    )


def annotate_financial_scope(
    queryset,
):
    confirmed = (
        InternalTransfer.objects.filter(
            status=(
                InternalTransfer.Status.CONFIRMED
            ),
            debit_transaction__account__is_own_account=True,
            credit_transaction__account__is_own_account=True,
        )
        .filter(
            Q(
                debit_transaction_id=OuterRef(
                    "pk"
                )
            )
            | Q(
                credit_transaction_id=OuterRef(
                    "pk"
                )
            )
        )
    )

    possible = (
        InternalTransfer.objects.filter(
            status=(
                InternalTransfer.Status.POSSIBLE
            ),
            debit_transaction__account__is_own_account=True,
            credit_transaction__account__is_own_account=True,
        )
        .filter(
            Q(
                debit_transaction_id=OuterRef(
                    "pk"
                )
            )
            | Q(
                credit_transaction_id=OuterRef(
                    "pk"
                )
            )
        )
    )

    queryset = queryset.annotate(
        is_internal_transfer=Exists(
            confirmed
        ),
        is_possible_internal_transfer=Exists(
            possible
        ),
    )

    return queryset.annotate(
        financial_scope_rank=Case(
            When(
                is_internal_transfer=True,
                then=Value(2),
            ),
            When(
                is_possible_internal_transfer=True,
                then=Value(1),
            ),
            default=Value(0),
            output_field=IntegerField(),
        ),
    )
