from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
import re
import unicodedata

from django.db import transaction as db_transaction
from django.db.models import Q
from django.utils import timezone

from finance.models import InternalTransfer
from finance.models import Transaction


TRANSFER_TYPES = {
    Transaction.TransactionType.PIX,
    Transaction.TransactionType.TED,
    Transaction.TransactionType.DOC,
    Transaction.TransactionType.TRANSFER,
}

TRANSFER_TEXT_MARKERS = (
    " PIX ",
    "TRANSFER",
    " TED ",
    " DOC ",
)

AUTO_CONFIRM_SCORE = 90
POSSIBLE_SCORE = 70
MIN_SCORE_MARGIN = 10
DATE_WINDOW_DAYS = 2


@dataclass(frozen=True, slots=True)
class Candidate:
    debit_id: int
    credit_id: int
    score: int
    reasons: tuple[str, ...]
    auto_confirmable: bool


def _normalize(
    value: str,
) -> str:
    decomposed = unicodedata.normalize(
        "NFKD",
        value or "",
    )

    ascii_text = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(
            character
        )
    )

    return (
        " "
        + re.sub(
            r"[^A-Za-z0-9]+",
            " ",
            ascii_text,
        ).upper().strip()
        + " "
    )


def _looks_like_transfer(
    transaction: Transaction,
) -> bool:
    if (
        transaction.transaction_type
        in TRANSFER_TYPES
    ):
        return True

    text = _normalize(
        transaction.description
    )

    return any(
        marker in text
        for marker in TRANSFER_TEXT_MARKERS
    )


def _has_precise_time(
    transaction: Transaction,
) -> bool:
    if (
        transaction.source_type
        == Transaction.SourceType.PDF
    ):
        return False

    if (
        transaction.source_type
        == Transaction.SourceType.OFX
    ):
        return (
            transaction.ofx_time_was_supplied
        )

    return True


def _same_nonempty(
    left: str,
    right: str,
) -> bool:
    return bool(
        left
        and right
        and _normalize(left)
        == _normalize(right)
    )


def _bank_name_in_description(
    transaction: Transaction,
    bank_name: str,
) -> bool:
    bank = _normalize(
        bank_name
    ).strip()

    if len(bank) < 3:
        return False

    description = _normalize(
        transaction.description
    )

    return (
        f" {bank} "
        in description
    )


def _score_pair(
    debit: Transaction,
    credit: Transaction,
) -> tuple[int, list[str], bool] | None:
    if (
        debit.direction
        != Transaction.Direction.DEBIT
        or credit.direction
        != Transaction.Direction.CREDIT
    ):
        return None

    if (
        debit.account_id
        == credit.account_id
    ):
        return None

    if (
        not debit.account.is_own_account
        or not credit.account.is_own_account
    ):
        return None

    if debit.amount != credit.amount:
        return None

    debit_transfer = _looks_like_transfer(
        debit
    )
    credit_transfer = _looks_like_transfer(
        credit
    )

    # Evita relacionar compra, salário, estorno etc. somente pelo valor.
    if not (
        debit_transfer
        or credit_transfer
    ):
        return None

    debit_date = timezone.localtime(
        debit.posted_at
    ).date()
    credit_date = timezone.localtime(
        credit.posted_at
    ).date()

    day_gap = abs(
        (
            credit_date
            - debit_date
        ).days
    )

    if day_gap > DATE_WINDOW_DAYS:
        return None

    score = 40
    strong_identity_evidence = False
    reasons = [
        "Mesmo valor",
        "Débito e crédito em contas próprias diferentes",
    ]

    if debit_transfer:
        score += 10
        reasons.append(
            "Saída identificada como PIX/TED/DOC/transferência"
        )

    if credit_transfer:
        score += 10
        reasons.append(
            "Entrada identificada como PIX/TED/DOC/transferência"
        )

    if day_gap == 0:
        score += 15
        reasons.append(
            "Mesma data bancária"
        )
    elif day_gap == 1:
        score += 5
        reasons.append(
            "Datas bancárias com diferença de 1 dia"
        )

    debit_precise = _has_precise_time(
        debit
    )
    credit_precise = _has_precise_time(
        credit
    )

    if (
        debit_precise
        and credit_precise
    ):
        seconds = abs(
            (
                credit.posted_at
                - debit.posted_at
            ).total_seconds()
        )

        if seconds <= 5 * 60:
            score += 20
            reasons.append(
                "Horários com diferença de até 5 minutos"
            )

            if seconds <= 60:
                strong_identity_evidence = True
                reasons.append(
                    "Horários com diferença de até 1 minuto"
                )
        elif seconds <= 2 * 60 * 60:
            score += 15
            reasons.append(
                "Horários com diferença de até 2 horas"
            )
        elif seconds <= 24 * 60 * 60:
            score += 5
            reasons.append(
                "Horários no intervalo de 24 horas"
            )
        else:
            score -= 10
            reasons.append(
                "Horários distantes"
            )
    elif day_gap == 0:
        score += 5
        reasons.append(
            "Um dos extratos não informou horário"
        )

    if (
        debit.counterparty_id
        and credit.counterparty_id
        and (
            debit.counterparty_id
            == credit.counterparty_id
        )
    ):
        score += 15
        strong_identity_evidence = True
        reasons.append(
            "Mesma contraparte identificada"
        )
    elif _same_nonempty(
        debit.counterparty_raw_name,
        credit.counterparty_raw_name,
    ):
        score += 10
        strong_identity_evidence = True
        reasons.append(
            "Mesmo nome de contraparte no histórico"
        )

    if (
        _same_nonempty(
            debit.document,
            credit.document,
        )
        or _same_nonempty(
            debit.reference,
            credit.reference,
        )
    ):
        score += 15
        strong_identity_evidence = True
        reasons.append(
            "Documento/referência correspondente"
        )

    bank_evidence = False

    if _bank_name_in_description(
        debit,
        credit.account.bank.name,
    ):
        bank_evidence = True

    if _bank_name_in_description(
        credit,
        debit.account.bank.name,
    ):
        bank_evidence = True

    if bank_evidence:
        score += 10
        strong_identity_evidence = True
        reasons.append(
            "Histórico menciona o banco da outra conta"
        )

    return (
        min(
            max(score, 0),
            100,
        ),
        reasons,
        strong_identity_evidence,
    )


def _active_transaction_ids():
    active = (
        InternalTransfer.objects.filter(
            status__in=[
                InternalTransfer.Status.POSSIBLE,
                InternalTransfer.Status.CONFIRMED,
            ]
        )
        .values_list(
            "debit_transaction_id",
            "credit_transaction_id",
        )
    )

    result = set()

    for debit_id, credit_id in active:
        result.add(
            debit_id
        )
        result.add(
            credit_id
        )

    return result


def _rejected_pairs():
    return set(
        InternalTransfer.objects.filter(
            status=(
                InternalTransfer.Status.REJECTED
            )
        )
        .values_list(
            "debit_transaction_id",
            "credit_transaction_id",
        )
    )


def _top_unique_candidate(
    candidates: list[Candidate],
    *,
    key,
) -> dict[int, Candidate]:
    grouped = defaultdict(
        list
    )

    for candidate in candidates:
        grouped[
            key(candidate)
        ].append(
            candidate
        )

    winners = {}

    for identifier, items in grouped.items():
        ordered = sorted(
            items,
            key=lambda item: (
                item.score,
                -item.debit_id,
                -item.credit_id,
            ),
            reverse=True,
        )

        top = ordered[0]

        if (
            len(ordered) > 1
            and (
                top.score
                - ordered[1].score
            )
            < MIN_SCORE_MARGIN
        ):
            continue

        winners[
            identifier
        ] = top

    return winners


@db_transaction.atomic
def analyze_internal_transfers(
    *,
    transaction_ids: list[int] | tuple[int, ...] | None = None,
) -> dict[str, int]:
    own_transactions = (
        Transaction.objects.select_related(
            "account",
            "account__bank",
            "counterparty",
        )
        .filter(
            account__is_own_account=True,
            is_financially_ignored=False,
            is_internal_balance_movement=False,
        )
        .order_by(
            "posted_at",
            "id",
        )
    )

    active_ids = (
        _active_transaction_ids()
    )
    rejected_pairs = (
        _rejected_pairs()
    )

    base_debits = own_transactions.filter(
        direction=Transaction.Direction.DEBIT
    ).exclude(
        pk__in=active_ids
    )

    if transaction_ids:
        ids = {
            int(value)
            for value in transaction_ids
        }

        # Analisar novas/alteradas e também movimentos que possam ser
        # contrapartida deles.
        touched = list(
            own_transactions.filter(
                pk__in=ids
            )
        )

        if not touched:
            return {
                "confirmed": 0,
                "possible": 0,
                "skipped_ambiguous": 0,
            }

        min_date = min(
            item.posted_at
            for item in touched
        ) - timedelta(
            days=DATE_WINDOW_DAYS
        )
        max_date = max(
            item.posted_at
            for item in touched
        ) + timedelta(
            days=DATE_WINDOW_DAYS
        )

        base_debits = base_debits.filter(
            posted_at__gte=min_date,
            posted_at__lte=max_date,
        )

    edges: list[Candidate] = []

    for debit in base_debits.iterator(
        chunk_size=250
    ):
        debit_date = timezone.localtime(
            debit.posted_at
        ).date()

        start_date = (
            debit_date
            - timedelta(
                days=DATE_WINDOW_DAYS
            )
        )
        end_date = (
            debit_date
            + timedelta(
                days=DATE_WINDOW_DAYS
            )
        )

        credits = (
            own_transactions.filter(
                direction=(
                    Transaction.Direction.CREDIT
                ),
                amount=debit.amount,
                posted_at__date__gte=(
                    start_date
                ),
                posted_at__date__lte=(
                    end_date
                ),
            )
            .exclude(
                account_id=debit.account_id
            )
            .exclude(
                pk__in=active_ids
            )
        )

        for credit in credits:
            pair = (
                debit.pk,
                credit.pk,
            )

            if pair in rejected_pairs:
                continue

            if transaction_ids:
                if (
                    debit.pk
                    not in ids
                    and credit.pk
                    not in ids
                ):
                    continue

            result = _score_pair(
                debit,
                credit,
            )

            if result is None:
                continue

            (
                score,
                reasons,
                auto_confirmable,
            ) = result

            if score < POSSIBLE_SCORE:
                continue

            edges.append(
                Candidate(
                    debit_id=debit.pk,
                    credit_id=credit.pk,
                    score=score,
                    reasons=tuple(
                        reasons
                    ),
                    auto_confirmable=(
                        auto_confirmable
                    ),
                )
            )

    best_debit = (
        _top_unique_candidate(
            edges,
            key=lambda item: (
                item.debit_id
            ),
        )
    )
    best_credit = (
        _top_unique_candidate(
            edges,
            key=lambda item: (
                item.credit_id
            ),
        )
    )

    mutual = []

    for candidate in edges:
        if (
            best_debit.get(
                candidate.debit_id
            )
            == candidate
            and best_credit.get(
                candidate.credit_id
            )
            == candidate
        ):
            mutual.append(
                candidate
            )

    mutual.sort(
        key=lambda item: (
            item.score,
            -item.debit_id,
            -item.credit_id,
        ),
        reverse=True,
    )

    counters = {
        "confirmed": 0,
        "possible": 0,
        "skipped_ambiguous": (
            max(
                len(edges)
                - len(mutual),
                0,
            )
        ),
    }

    used = set(
        active_ids
    )

    for candidate in mutual:
        if (
            candidate.debit_id
            in used
            or candidate.credit_id
            in used
        ):
            continue

        status = (
            InternalTransfer.Status.CONFIRMED
            if (
                candidate.score
                >= AUTO_CONFIRM_SCORE
                and candidate.auto_confirmable
            )
            else InternalTransfer.Status.POSSIBLE
        )

        link = InternalTransfer(
            debit_transaction_id=(
                candidate.debit_id
            ),
            credit_transaction_id=(
                candidate.credit_id
            ),
            status=status,
            match_method=(
                InternalTransfer.MatchMethod.AUTOMATIC
            ),
            confidence=(
                candidate.score
            ),
            match_reasons=list(
                candidate.reasons
            ),
        )

        link.full_clean()
        link.save()

        used.add(
            candidate.debit_id
        )
        used.add(
            candidate.credit_id
        )

        if (
            status
            == InternalTransfer.Status.CONFIRMED
        ):
            counters[
                "confirmed"
            ] += 1
        else:
            counters[
                "possible"
            ] += 1

    return counters


@db_transaction.atomic
def confirm_internal_transfer(
    *,
    transfer: InternalTransfer,
    user,
):
    transfer.status = (
        InternalTransfer.Status.CONFIRMED
    )
    transfer.reviewed_by = user
    transfer.reviewed_at = (
        timezone.now()
    )
    transfer.full_clean()
    transfer.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )

    return transfer


@db_transaction.atomic
def reject_internal_transfer(
    *,
    transfer: InternalTransfer,
    user,
):
    transfer.status = (
        InternalTransfer.Status.REJECTED
    )
    transfer.reviewed_by = user
    transfer.reviewed_at = (
        timezone.now()
    )
    transfer.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )

    return transfer


@db_transaction.atomic
def reopen_internal_transfer(
    *,
    transfer: InternalTransfer,
    user,
):
    # "Desfazer" um vínculo confirmado significa registrar que aquele
    # par não deve voltar a ser confirmado automaticamente.
    transfer.status = (
        InternalTransfer.Status.REJECTED
    )
    transfer.reviewed_by = user
    transfer.reviewed_at = (
        timezone.now()
    )
    transfer.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )

    return transfer



@db_transaction.atomic
def deactivate_account_internal_links(
    *,
    account_id: int,
    user,
) -> int:
    now = timezone.now()

    links = (
        InternalTransfer.objects.filter(
            status__in=[
                InternalTransfer.Status.POSSIBLE,
                InternalTransfer.Status.CONFIRMED,
            ]
        )
        .filter(
            Q(
                debit_transaction__account_id=account_id
            )
            | Q(
                credit_transaction__account_id=account_id
            )
        )
    )

    return links.update(
        status=(
            InternalTransfer.Status.REJECTED
        ),
        reviewed_by=user,
        reviewed_at=now,
        updated_at=now,
    )
