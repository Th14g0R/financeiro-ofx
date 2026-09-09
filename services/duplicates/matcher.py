from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from datetime import timedelta
from typing import Iterable

from django.db import transaction as db_transaction
from django.db.models import Q
from django.utils import timezone

from finance.models import InternalTransfer
from finance.models import Transaction
from finance.models import TransactionDuplicateReview


def _normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = re.sub(r"\b(?:PIX|TED|DOC|TRANSFERENCIA|ENVIADA|RECEBIDA|COMPRA|DEBITO|CREDITO|PAGAMENTO)\b", " ", ascii_text.upper())
    ascii_text = re.sub(r"[^A-Z0-9]+", " ", ascii_text)
    return " ".join(ascii_text.split())


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _description_similarity(first: Transaction, second: Transaction) -> float:
    a = _normalize_text(first.raw_description or first.normalized_description)
    b = _normalize_text(second.raw_description or second.normalized_description)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        shorter = min(len(a), len(b))
        longer = max(len(a), len(b))
        return max(0.88, shorter / longer if longer else 0.0)
    return SequenceMatcher(None, a, b).ratio()


def _counterparty_similarity(first: Transaction, second: Transaction) -> bool:
    if first.counterparty_id and first.counterparty_id == second.counterparty_id:
        return True
    names = [
        _normalize_text(first.counterparty_raw_name),
        _normalize_text(second.counterparty_raw_name),
        _normalize_text(first.counterparty.display_name if first.counterparty_id else ""),
        _normalize_text(second.counterparty.display_name if second.counterparty_id else ""),
    ]
    a_candidates = {x for x in (names[0], names[2]) if x}
    b_candidates = {x for x in (names[1], names[3]) if x}
    return bool(a_candidates & b_candidates)


def _same_account_identity(first: Transaction, second: Transaction) -> bool:
    if first.account_id == second.account_id:
        return True
    if first.account.bank_id != second.account.bank_id:
        return False

    def key(tx: Transaction) -> tuple[str, str]:
        branch = _digits(tx.account.branch).lstrip("0") or "0"
        number = (_digits(tx.account.number) + _digits(tx.account.digit)).lstrip("0")
        return branch, number

    a_branch, a_number = key(first)
    b_branch, b_number = key(second)
    return bool(a_number and a_number == b_number and a_branch == b_branch)


def score_pair(first: Transaction, second: Transaction) -> tuple[int, list[str]]:
    if first.pk == second.pk:
        return 0, []
    if first.direction != second.direction or first.amount != second.amount:
        return 0, []
    if first.account.bank_id != second.account.bank_id:
        return 0, []

    score = 40
    reasons = ["Mesmo banco, natureza e valor"]

    date_delta = abs((first.posted_at.date() - second.posted_at.date()).days)
    if date_delta == 0:
        score += 25
        reasons.append("Mesma data")
    elif date_delta == 1:
        score += 10
        reasons.append("Datas com diferença de 1 dia")
    else:
        return 0, []

    if _same_account_identity(first, second):
        score += 10
        reasons.append("Mesma conta ou conta equivalente")

    similarity = _description_similarity(first, second)
    if similarity >= 0.96:
        score += 20
        reasons.append("Descrição praticamente idêntica")
    elif similarity >= 0.82:
        score += 15
        reasons.append("Descrição muito semelhante")
    elif similarity >= 0.68:
        score += 8
        reasons.append("Descrição semelhante")

    if first.transaction_type == second.transaction_type:
        score += 3
        reasons.append("Mesmo tipo")

    if _counterparty_similarity(first, second):
        score += 7
        reasons.append("Mesma contraparte")

    if first.source_type != second.source_type:
        score += 3
        reasons.append("Mesma operação em origens diferentes")

    # A identidade de cada fonte continua útil para auditoria, mas FITIDs
    # diferentes não impedem que duas fontes representem a mesma operação.
    if first.fitid and second.fitid and first.fitid != second.fitid:
        reasons.append("FITIDs distintos entre as fontes")

    return min(score, 100), reasons


def _ordered(first: Transaction, second: Transaction) -> tuple[Transaction, Transaction]:
    return (first, second) if first.pk < second.pk else (second, first)


def analyze_duplicates(
    *,
    transaction_ids: Iterable[int] | None = None,
    quarantine_new: bool = False,
) -> int:
    base = Transaction.objects.filter(is_financially_ignored=False).select_related(
        "account", "account__bank", "counterparty"
    )
    seed_ids = set(transaction_ids or [])
    if transaction_ids is not None:
        seeds = list(base.filter(pk__in=seed_ids))
    else:
        seeds = list(base.order_by("-posted_at", "-id"))

    created_or_updated = 0
    seen_pairs: set[tuple[int, int]] = set()

    for tx in seeds:
        candidates = (
            base.filter(
                account__bank_id=tx.account.bank_id,
                direction=tx.direction,
                amount=tx.amount,
                posted_at__gte=tx.posted_at - timedelta(days=1, hours=23, minutes=59),
                posted_at__lte=tx.posted_at + timedelta(days=1, hours=23, minutes=59),
            )
            .exclude(pk=tx.pk)
            .order_by("id")
        )
        for other in candidates:
            first, second = _ordered(tx, other)
            pair = (first.pk, second.pk)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            score, reasons = score_pair(first, second)
            if score < 72:
                continue
            classification = (
                TransactionDuplicateReview.Classification.EXACT
                if score >= 90
                else TransactionDuplicateReview.Classification.POSSIBLE
            )
            review, created = TransactionDuplicateReview.objects.get_or_create(
                first_transaction=first,
                second_transaction=second,
                defaults={
                    "classification": classification,
                    "confidence": score,
                    "match_reasons": reasons,
                },
            )
            # Nunca reabra uma decisão manual automaticamente.
            if not created and review.status == TransactionDuplicateReview.Status.PENDING:
                review.classification = classification
                review.confidence = score
                review.match_reasons = reasons
                review.save(update_fields=["classification", "confidence", "match_reasons", "updated_at"])

            # Novas importações com duplicidade MUITO provável ficam em
            # quarentena contábil até a decisão do usuário. O registro não é
            # apagado e continua auditável. Possíveis duplicidades (<90%)
            # permanecem contabilizadas até revisão.
            if (
                quarantine_new
                and classification == TransactionDuplicateReview.Classification.EXACT
                and review.status == TransactionDuplicateReview.Status.PENDING
            ):
                new_tx = None
                old_tx = None
                if first.pk in seed_ids and second.pk not in seed_ids:
                    new_tx, old_tx = first, second
                elif second.pk in seed_ids and first.pk not in seed_ids:
                    new_tx, old_tx = second, first
                if (
                    new_tx is not None
                    and old_tx is not None
                    and new_tx.source_type != old_tx.source_type
                    and not new_tx.is_financially_ignored
                ):
                    new_tx.is_financially_ignored = True
                    new_tx.ignored_reason = (
                        f"Aguardando revisão de duplicidade provável com movimentação #{old_tx.pk}."
                    )
                    new_tx.canonical_transaction = old_tx
                    new_tx.save(
                        update_fields=[
                            "is_financially_ignored",
                            "ignored_reason",
                            "canonical_transaction",
                            "updated_at",
                        ]
                    )
            created_or_updated += 1

    return created_or_updated


def _snapshot(tx: Transaction) -> dict:
    return {
        "id": tx.pk,
        "source_type": tx.source_type,
        "fitid": tx.fitid,
        "posted_at": tx.posted_at.isoformat(),
        "amount": str(tx.amount),
        "direction": tx.direction,
        "transaction_type": tx.transaction_type,
        "raw_description": tx.raw_description,
        "document": tx.document,
        "reference": tx.reference,
        "counterparty_id": tx.counterparty_id,
        "raw_data": tx.raw_data,
    }


def _merge_missing_metadata(winner: Transaction, loser: Transaction) -> None:
    changed: list[str] = []
    if not winner.counterparty_id and loser.counterparty_id:
        winner.counterparty = loser.counterparty
        changed.append("counterparty")
    if not winner.counterparty_raw_name and loser.counterparty_raw_name:
        winner.counterparty_raw_name = loser.counterparty_raw_name
        changed.append("counterparty_raw_name")
    if not winner.document and loser.document:
        winner.document = loser.document
        changed.append("document")
    if not winner.reference and loser.reference:
        winner.reference = loser.reference
        changed.append("reference")
    if not winner.category_id and loser.category_id:
        winner.category = loser.category
        changed.append("category")

    # Prefere a descrição mais rica, sem mudar valor/data/natureza.
    if len((loser.raw_description or "").strip()) > len((winner.raw_description or "").strip()):
        winner.raw_description = loser.raw_description
        changed.append("raw_description")
    if len((loser.normalized_description or "").strip()) > len((winner.normalized_description or "").strip()):
        winner.normalized_description = loser.normalized_description
        changed.append("normalized_description")

    raw_data = dict(winner.raw_data or {})
    merged_sources = list(raw_data.get("_merged_sources") or [])
    merged_sources.append(_snapshot(loser))
    raw_data["_merged_sources"] = merged_sources[-20:]
    winner.raw_data = raw_data
    changed.append("raw_data")

    if changed:
        winner.save(update_fields=[*dict.fromkeys(changed), "updated_at"])


def _ignore_transaction(loser: Transaction, winner: Transaction, *, reason: str) -> None:
    loser.is_financially_ignored = True
    loser.ignored_reason = reason[:255]
    loser.canonical_transaction = winner
    loser.save(update_fields=["is_financially_ignored", "ignored_reason", "canonical_transaction", "updated_at"])


def _repoint_pluggy_links(loser: Transaction, winner: Transaction) -> None:
    from integrations.models import PluggyTransactionLink
    PluggyTransactionLink.objects.filter(transaction=loser).update(transaction=winner)


def _remove_invalid_internal_links(transaction_ids: list[int]) -> None:
    InternalTransfer.objects.filter(
        Q(debit_transaction_id__in=transaction_ids)
        | Q(credit_transaction_id__in=transaction_ids)
    ).delete()


@db_transaction.atomic
def review_duplicate_pair(
    review: TransactionDuplicateReview,
    *,
    action: str,
    user,
) -> TransactionDuplicateReview:
    review = TransactionDuplicateReview.objects.select_for_update().select_related(
        "first_transaction", "second_transaction"
    ).get(pk=review.pk)
    first = review.first_transaction
    second = review.second_transaction

    if action == "keep_both":
        for tx in (first, second):
            if tx.is_financially_ignored and (
                tx.canonical_transaction_id in {first.pk, second.pk}
                or "duplicidade" in (tx.ignored_reason or "").lower()
            ):
                tx.is_financially_ignored = False
                tx.ignored_reason = ""
                tx.canonical_transaction = None
                tx.save(
                    update_fields=[
                        "is_financially_ignored",
                        "ignored_reason",
                        "canonical_transaction",
                        "updated_at",
                    ]
                )
        review.status = TransactionDuplicateReview.Status.KEEP_BOTH
    elif action in {"keep_first", "merge_first"}:
        if action == "merge_first":
            _merge_missing_metadata(first, second)
            _repoint_pluggy_links(second, first)
            review.status = TransactionDuplicateReview.Status.MERGED_FIRST
        else:
            review.status = TransactionDuplicateReview.Status.KEEP_FIRST
        _ignore_transaction(second, first, reason=f"Duplicidade revisada; mantida movimentação #{first.pk}.")
        _remove_invalid_internal_links([second.pk])
    elif action in {"keep_second", "merge_second"}:
        if action == "merge_second":
            _merge_missing_metadata(second, first)
            _repoint_pluggy_links(first, second)
            review.status = TransactionDuplicateReview.Status.MERGED_SECOND
        else:
            review.status = TransactionDuplicateReview.Status.KEEP_SECOND
        _ignore_transaction(first, second, reason=f"Duplicidade revisada; mantida movimentação #{second.pk}.")
        _remove_invalid_internal_links([first.pk])
    else:
        raise ValueError("Ação de revisão de duplicidade inválida.")

    review.reviewed_by = user
    review.reviewed_at = timezone.now()
    review.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
    return review


def merge_duplicate_pair(review: TransactionDuplicateReview, *, keep: str, user):
    action = "merge_first" if keep == "first" else "merge_second"
    return review_duplicate_pair(review, action=action, user=user)
