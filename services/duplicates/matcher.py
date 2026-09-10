from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from dataclasses import dataclass
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


@lru_cache(maxsize=4096)
def _parsed_counterparty_name(description: str, transaction_type: str) -> str:
    try:
        from services.counterparties import extract_counterparty_candidate

        candidate = extract_counterparty_candidate(
            description,
            transaction_type=transaction_type,
        )
        return _normalize_text(candidate.name if candidate else "")
    except Exception:
        return ""


def _transaction_counterparty_names(transaction: Transaction) -> set[str]:
    names: set[str] = set()
    for value in (
        transaction.counterparty_raw_name,
        transaction.counterparty.display_name if transaction.counterparty_id else "",
    ):
        normalized = _normalize_text(value)
        if normalized:
            names.add(normalized)

    # Historical Pluggy rows may predate the structured counterparty resolver.
    # Parse the description on demand so ``Transferência Recebida|Nome`` also
    # protects duplicate matching before a full counterparty rebuild is run.
    normalized = _parsed_counterparty_name(
        transaction.raw_description or transaction.normalized_description or "",
        transaction.transaction_type,
    )
    if normalized:
        names.add(normalized)

    # Quando a origem fornece paymentData (ex.: Pluggy), use diretamente a
    # contraparte financeira estruturada. Para saídas interessa o recebedor;
    # para entradas, o pagador. Isso evita depender apenas do texto do histórico.
    details = transaction.payment_details if isinstance(transaction.payment_details, dict) else {}
    participant_key = (
        "receiver"
        if transaction.direction == Transaction.Direction.DEBIT
        else "payer"
    )
    participant = details.get(participant_key)
    if isinstance(participant, dict):
        payment_name = _normalize_text(str(participant.get("name") or ""))
        if payment_name:
            names.add(payment_name)
    return names


def _counterparty_similarity(first: Transaction, second: Transaction) -> bool:
    return bool(
        _transaction_counterparty_names(first)
        & _transaction_counterparty_names(second)
    )


def _counterparty_conflicts(first: Transaction, second: Transaction) -> bool:
    """Return True when both movements identify clearly different parties."""
    first_names = _transaction_counterparty_names(first)
    second_names = _transaction_counterparty_names(second)
    if not first_names or not second_names:
        return False
    if first_names & second_names:
        return False

    # If every known identity pair is materially different, these are separate
    # operations even when date/value/type match. This blocks cases such as a
    # series of R$ 15 PIX transfers to different people on the same day.
    best_similarity = max(
        SequenceMatcher(None, left, right).ratio()
        for left in first_names
        for right in second_names
    )
    return best_similarity < 0.88

def _same_nonempty(left: str, right: str) -> bool:
    return bool(left and right and _normalize_text(left) == _normalize_text(right))


def _has_strong_identity_evidence(
    first: Transaction,
    second: Transaction,
    *,
    description_similarity: float,
) -> bool:
    return bool(
        description_similarity >= 0.68
        or _counterparty_similarity(first, second)
        or _same_nonempty(first.document, second.document)
        or _same_nonempty(first.reference, second.reference)
    )


def _source_family(transaction: Transaction) -> str:
    """Return the effective import/provider family used by duplicate matching.

    ``source_type=API`` is shared by Pluggy and legacy/direct APIs, so treating
    every API row as one source would hide valid cross-provider duplicates.
    """
    if transaction.source_type == Transaction.SourceType.API:
        fitid = (transaction.fitid or "").upper()
        if fitid.startswith("PLUGGY:") or fitid.startswith("PLUGGY-PROVIDER:"):
            return "PLUGGY"
        raw_data = transaction.raw_data if isinstance(transaction.raw_data, dict) else {}
        if str(raw_data.get("provider") or "").upper() == "PLUGGY":
            return "PLUGGY"
        return "API_OTHER"
    return str(transaction.source_type or "")


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

    # Same-source records with distinct provider/FITID identifiers are normally
    # distinct real operations. Re-import duplication should already be caught
    # by FITID/fingerprint uniqueness, so do not create broad same-source pairs.
    if (
        _source_family(first) == _source_family(second)
        and first.fitid
        and second.fitid
        and first.fitid != second.fitid
    ):
        return 0, []

    if _counterparty_conflicts(first, second):
        return 0, []

    similarity = _description_similarity(first, second)
    if not _has_strong_identity_evidence(
        first, second, description_similarity=similarity
    ):
        return 0, []

    score = 40
    reasons = ["Mesmo banco, natureza e valor"]

    # Para duplicidade financeira, a data local precisa coincidir. Uma operação
    # de 15/06 não pode ser agrupada com outra de 16/06 apenas porque valor e
    # descrição são iguais (caso típico de rendimentos CDI recorrentes).
    first_local = (
        timezone.localtime(first.posted_at)
        if timezone.is_aware(first.posted_at)
        else first.posted_at
    )
    second_local = (
        timezone.localtime(second.posted_at)
        if timezone.is_aware(second.posted_at)
        else second.posted_at
    )
    if first_local.date() != second_local.date():
        return 0, []

    score += 25
    reasons.append("Mesma data")

    # Horário é evidência adicional quando ambas as fontes realmente o
    # fornecem. OFX sem hora costuma chegar como 00:00 e não deve ser penalizado
    # por divergir do horário preciso do Pluggy.
    first_has_time = not (
        first.source_type == Transaction.SourceType.OFX
        and not first.ofx_time_was_supplied
    )
    second_has_time = not (
        second.source_type == Transaction.SourceType.OFX
        and not second.ofx_time_was_supplied
    )
    if first_has_time and second_has_time:
        seconds = abs((first_local - second_local).total_seconds())

        # Quando as duas fontes realmente fornecem horário, diferenças grandes
        # representam operações distintas. Mantemos uma tolerância de até
        # 60 minutos para acomodar pequenas diferenças entre horário de
        # autorização, contabilização e disponibilização por provedores
        # diferentes. OFX sem horário não entra nesta regra.
        if seconds > 60 * 60:
            return 0, []
        if seconds <= 60:
            score += 10
            reasons.append("Mesmo horário")
        elif seconds <= 10 * 60:
            score += 6
            reasons.append("Horários muito próximos")
        else:
            score += 2
            reasons.append("Horários próximos")

    if _same_account_identity(first, second):
        score += 10
        reasons.append("Mesma conta ou conta equivalente")

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

    if _same_nonempty(first.document, second.document):
        score += 5
        reasons.append("Mesmo documento")
    elif _same_nonempty(first.reference, second.reference):
        score += 4
        reasons.append("Mesma referência")

    if _source_family(first) != _source_family(second):
        score += 3
        reasons.append("Mesma operação em origens diferentes")

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
    base = Transaction.objects.filter(
        Q(is_financially_ignored=False)
        | Q(
            is_financially_ignored=True,
            ignored_reason__istartswith="Aguardando revisão de duplicidade provável",
        )
    ).select_related(
        "account", "account__bank", "counterparty"
    )
    seed_ids = set(transaction_ids or [])
    if transaction_ids is not None:
        seeds = list(base.filter(pk__in=seed_ids))
    else:
        seeds = list(base.order_by("-posted_at", "-id"))

    created_or_updated = 0
    seen_pairs: set[tuple[int, int]] = set()
    valid_pairs: set[tuple[int, int]] = set()

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
            valid_pairs.add(pair)
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

    # Pending suggestions are ephemeral analysis output, not user decisions.
    # Remove suggestions that no longer satisfy the current matcher so old false
    # positives do not remain forever after the algorithm is improved.
    stale_scope = TransactionDuplicateReview.objects.filter(
        status=TransactionDuplicateReview.Status.PENDING
    )
    if transaction_ids is not None:
        stale_scope = stale_scope.filter(
            Q(first_transaction_id__in=seed_ids)
            | Q(second_transaction_id__in=seed_ids)
        )

    stale_ids: list[int] = []
    affected_transaction_ids: set[int] = set()
    for review_id, first_id, second_id in stale_scope.values_list(
        "pk", "first_transaction_id", "second_transaction_id"
    ):
        if (first_id, second_id) not in valid_pairs:
            stale_ids.append(review_id)
            affected_transaction_ids.update((first_id, second_id))

    if stale_ids:
        TransactionDuplicateReview.objects.filter(pk__in=stale_ids).delete()

        # A transaction quarantined only because of a suggestion that vanished
        # must return to the financial totals. Manual/reviewed ignores are never
        # touched here.
        for tx in Transaction.objects.filter(
            pk__in=affected_transaction_ids,
            is_financially_ignored=True,
            ignored_reason__istartswith="Aguardando revisão de duplicidade provável",
        ):
            still_pending = TransactionDuplicateReview.objects.filter(
                status=TransactionDuplicateReview.Status.PENDING
            ).filter(
                Q(first_transaction_id=tx.pk)
                | Q(second_transaction_id=tx.pk)
            ).exists()
            if not still_pending:
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
        "category_id": tx.category_id,
        "source_category_name": tx.source_category_name,
        "source_category_id": tx.source_category_id,
        "category_assignment_source": tx.category_assignment_source,
        "payment_details": tx.payment_details,
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
        if loser.category_assignment_source:
            winner.category_assignment_source = loser.category_assignment_source
            changed.append("category_assignment_source")
    if not winner.source_category_name and loser.source_category_name:
        winner.source_category_name = loser.source_category_name
        changed.append("source_category_name")
    if not winner.source_category_id and loser.source_category_id:
        winner.source_category_id = loser.source_category_id
        changed.append("source_category_id")
    if not (winner.payment_details or {}) and (loser.payment_details or {}):
        winner.payment_details = dict(loser.payment_details)
        changed.append("payment_details")

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


def _restore_duplicate_ignored_transaction(
    transaction: Transaction,
    *,
    related_transaction_ids: set[int] | None = None,
) -> None:
    """Bring a transaction back to financial totals when a duplicate decision keeps it.

    A newly imported high-confidence duplicate can be quarantined before review.
    Choosing that row as the canonical movement must explicitly release the
    quarantine; otherwise both the discarded row and the chosen winner could
    remain outside totals. Unrelated/manual ignores are preserved.
    """
    if not transaction.is_financially_ignored:
        return

    reason = transaction.ignored_reason or ""
    related_ids = related_transaction_ids or set()
    duplicate_related = (
        "duplicidade" in reason.lower()
        or reason.startswith("Aguardando revisão")
        or transaction.canonical_transaction_id in related_ids
    )
    if not duplicate_related:
        return

    transaction.is_financially_ignored = False
    transaction.ignored_reason = ""
    transaction.canonical_transaction = None
    transaction.save(
        update_fields=[
            "is_financially_ignored",
            "ignored_reason",
            "canonical_transaction",
            "updated_at",
        ]
    )


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

    # Pairwise decisions are unsafe when either movement belongs to another
    # pending relation. Force the grouped workflow so the same transaction
    # cannot be processed twice through old/direct URLs or stale browser tabs.
    if review.status == TransactionDuplicateReview.Status.PENDING:
        has_group_neighbors = (
            TransactionDuplicateReview.objects.filter(
                status=TransactionDuplicateReview.Status.PENDING
            )
            .exclude(pk=review.pk)
            .filter(
                Q(first_transaction_id__in=[first.pk, second.pk])
                | Q(second_transaction_id__in=[first.pk, second.pk])
            )
            .exists()
        )
        if has_group_neighbors:
            raise ValueError(
                "Esta movimentação participa de mais de uma sugestão. "
                "Resolva o grupo completo na tela de duplicidades."
            )

    related_ids = {first.pk, second.pk}
    if action == "keep_both":
        for tx in (first, second):
            _restore_duplicate_ignored_transaction(
                tx,
                related_transaction_ids=related_ids,
            )
        review.status = TransactionDuplicateReview.Status.KEEP_BOTH
    elif action in {"keep_first", "merge_first"}:
        _restore_duplicate_ignored_transaction(
            first,
            related_transaction_ids=related_ids,
        )
        if action == "merge_first":
            _merge_missing_metadata(first, second)
            _repoint_pluggy_links(second, first)
            review.status = TransactionDuplicateReview.Status.MERGED_FIRST
        else:
            review.status = TransactionDuplicateReview.Status.KEEP_FIRST
        _ignore_transaction(second, first, reason=f"Duplicidade revisada; mantida movimentação #{first.pk}.")
        _remove_invalid_internal_links([second.pk])
    elif action in {"keep_second", "merge_second"}:
        _restore_duplicate_ignored_transaction(
            second,
            related_transaction_ids=related_ids,
        )
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


@dataclass(frozen=True, slots=True)
class DuplicateReviewGroup:
    seed_review_id: int
    review_ids: tuple[int, ...]
    transaction_ids: tuple[int, ...]
    reviews: tuple[TransactionDuplicateReview, ...]
    transactions: tuple[Transaction, ...]
    min_confidence: int
    max_confidence: int
    match_reasons: tuple[str, ...]
    fully_matches_filter: bool = True

    @property
    def pair_count(self) -> int:
        return len(self.review_ids)

    @property
    def transaction_count(self) -> int:
        return len(self.transaction_ids)


def build_duplicate_review_groups(
    reviews: Iterable[TransactionDuplicateReview],
) -> list[DuplicateReviewGroup]:
    """Collapse pairwise suggestions into connected components.

    A transaction appears only once in the resulting group, even if the
    pairwise matcher found it against two or more candidates.
    """
    review_list = list(reviews)
    if not review_list:
        return []

    by_transaction: dict[int, list[TransactionDuplicateReview]] = {}
    tx_objects: dict[int, Transaction] = {}
    for review in review_list:
        for transaction in (review.first_transaction, review.second_transaction):
            tx_objects[transaction.pk] = transaction
            by_transaction.setdefault(transaction.pk, []).append(review)

    unseen = {review.pk: review for review in review_list}
    groups: list[DuplicateReviewGroup] = []

    while unseen:
        seed_id = min(unseen)
        queue = [unseen[seed_id]]
        component_reviews: dict[int, TransactionDuplicateReview] = {}
        component_tx_ids: set[int] = set()

        while queue:
            review = queue.pop()
            if review.pk in component_reviews:
                continue
            component_reviews[review.pk] = review
            unseen.pop(review.pk, None)
            ids = (review.first_transaction_id, review.second_transaction_id)
            component_tx_ids.update(ids)
            for tx_id in ids:
                for neighbor in by_transaction.get(tx_id, []):
                    if neighbor.pk not in component_reviews:
                        queue.append(neighbor)

        ordered_reviews = tuple(
            sorted(component_reviews.values(), key=lambda item: (-item.confidence, item.pk))
        )
        ordered_transactions = tuple(
            sorted(
                (tx_objects[tx_id] for tx_id in component_tx_ids),
                key=lambda tx: (tx.posted_at, tx.pk),
            )
        )
        reasons: list[str] = []
        for review in ordered_reviews:
            for reason in review.match_reasons or []:
                if reason not in reasons:
                    reasons.append(reason)

        groups.append(
            DuplicateReviewGroup(
                seed_review_id=min(component_reviews),
                review_ids=tuple(sorted(component_reviews)),
                transaction_ids=tuple(tx.pk for tx in ordered_transactions),
                reviews=ordered_reviews,
                transactions=ordered_transactions,
                min_confidence=min(item.confidence for item in ordered_reviews),
                max_confidence=max(item.confidence for item in ordered_reviews),
                match_reasons=tuple(reasons),
            )
        )

    return sorted(groups, key=lambda group: (-group.max_confidence, group.seed_review_id))


def _load_pending_component(seed_review_id: int) -> list[TransactionDuplicateReview]:
    all_reviews = list(
        TransactionDuplicateReview.objects.filter(
            status=TransactionDuplicateReview.Status.PENDING
        )
        .select_related(
            "first_transaction",
            "first_transaction__account",
            "first_transaction__account__bank",
            "first_transaction__counterparty",
            "second_transaction",
            "second_transaction__account",
            "second_transaction__account__bank",
            "second_transaction__counterparty",
        )
        .order_by("pk")
    )
    groups = build_duplicate_review_groups(all_reviews)
    for group in groups:
        if seed_review_id in group.review_ids:
            return list(group.reviews)
    raise ValueError("O grupo de duplicidade não está mais pendente. Atualize a página.")


@db_transaction.atomic
def review_duplicate_group(
    seed_review_id: int,
    *,
    action: str,
    user,
    canonical_transaction_id: int | None = None,
) -> dict[str, int]:
    """Resolve an entire connected duplicate group in one atomic decision."""
    reviews = _load_pending_component(seed_review_id)
    review_ids = [review.pk for review in reviews]
    locked_reviews = list(
        TransactionDuplicateReview.objects.select_for_update()
        .filter(pk__in=review_ids, status=TransactionDuplicateReview.Status.PENDING)
        .select_related("first_transaction", "second_transaction")
        .order_by("pk")
    )
    if len(locked_reviews) != len(review_ids):
        raise ValueError("O grupo mudou durante a operação. Atualize a página e tente novamente.")

    transaction_ids = sorted(
        {
            tx_id
            for review in locked_reviews
            for tx_id in (review.first_transaction_id, review.second_transaction_id)
        }
    )
    transactions = {
        tx.pk: tx
        for tx in Transaction.objects.select_for_update().filter(pk__in=transaction_ids)
    }

    related_ids = set(transaction_ids)
    if action == "keep_all":
        for tx in transactions.values():
            _restore_duplicate_ignored_transaction(
                tx,
                related_transaction_ids=related_ids,
            )
        now = timezone.now()
        TransactionDuplicateReview.objects.filter(pk__in=review_ids).update(
            status=TransactionDuplicateReview.Status.KEEP_BOTH,
            reviewed_by=user,
            reviewed_at=now,
            updated_at=now,
        )
        return {"reviews": len(review_ids), "transactions": len(transaction_ids), "ignored": 0}

    if action not in {"keep_one", "merge_one"}:
        raise ValueError("Ação de revisão em grupo inválida.")
    if canonical_transaction_id not in transactions:
        raise ValueError("Escolha uma movimentação do próprio grupo para manter.")

    winner = transactions[canonical_transaction_id]
    _restore_duplicate_ignored_transaction(
        winner,
        related_transaction_ids=related_ids,
    )
    loser_ids = [tx_id for tx_id in transaction_ids if tx_id != winner.pk]
    for loser_id in loser_ids:
        loser = transactions[loser_id]
        if action == "merge_one":
            _merge_missing_metadata(winner, loser)
            _repoint_pluggy_links(loser, winner)
        _ignore_transaction(
            loser,
            winner,
            reason=f"Duplicidade resolvida em grupo; mantida movimentação #{winner.pk}.",
        )
    _remove_invalid_internal_links(loser_ids)

    now = timezone.now()
    for review in locked_reviews:
        if winner.pk == review.first_transaction_id:
            status = (
                TransactionDuplicateReview.Status.MERGED_FIRST
                if action == "merge_one"
                else TransactionDuplicateReview.Status.KEEP_FIRST
            )
        elif winner.pk == review.second_transaction_id:
            status = (
                TransactionDuplicateReview.Status.MERGED_SECOND
                if action == "merge_one"
                else TransactionDuplicateReview.Status.KEEP_SECOND
            )
        else:
            status = TransactionDuplicateReview.Status.GROUP_RESOLVED
        review.status = status
        review.reviewed_by = user
        review.reviewed_at = now
        review.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])

    return {
        "reviews": len(review_ids),
        "transactions": len(transaction_ids),
        "ignored": len(loser_ids),
    }
