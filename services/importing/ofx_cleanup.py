from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from django.db import transaction as db_transaction
from django.db.models import Q
from django.utils import timezone

from finance.models import InternalTransfer
from finance.models import Transaction
from finance.models import TransactionDuplicateReview
from imports.models import ImportBatch
from imports.models import ImportEffect
from imports.models import ImportFile
from imports.models import ImportItem
from integrations.models import PluggyTransactionLink
from services.importing.commit import restore_transaction_snapshot
from services.importing.commit import transaction_snapshot


class OfxCleanupError(ValueError):
    pass


CATEGORY_PLUGGY_DUPLICATE = "PLUGGY_DUPLICATE"
CATEGORY_DIRECT_UNIQUE = "DIRECT_UNIQUE"
CATEGORY_UPDATED_REVERT = "UPDATED_REVERT"
CATEGORY_MODIFIED_UNIQUE = "MODIFIED_UNIQUE"
CATEGORY_AMBIGUOUS = "AMBIGUOUS"
CATEGORY_BLOCKED = "BLOCKED"
CATEGORY_MISSING = "MISSING"


FIELD_LABELS = {
    "account_id": "Conta",
    "posted_at": "Data/hora",
    "competence_date": "Competência",
    "amount": "Valor",
    "direction": "Natureza",
    "transaction_type": "Tipo",
    "source_type": "Origem",
    "fitid": "FITID",
    "raw_description": "Descrição original",
    "normalized_description": "Descrição normalizada",
    "document": "Documento",
    "reference": "Referência",
    "fingerprint": "Fingerprint",
    "fingerprint_version": "Versão do fingerprint",
    "raw_data": "Dados brutos",
    "notes": "Observações",
    "category_id": "Categoria",
    "counterparty_id": "Pessoa/contraparte",
    "counterparty_raw_name": "Nome da contraparte",
}


@dataclass(slots=True)
class FieldDifference:
    field: str
    label: str
    imported_value: object
    current_value: object


@dataclass(slots=True)
class CleanupEntry:
    effect_id: int
    batch_id: int
    import_item_id: int
    transaction_id: int | None
    bank_name: str
    account_label: str
    posted_at: object | None
    amount: object | None
    direction: str
    description: str
    action: str
    category: str
    category_label: str
    pluggy_transaction_id: int | None = None
    pluggy_confidence: int = 0
    pluggy_label: str = ""
    differences: list[FieldDifference] = field(default_factory=list)
    reason: str = ""

    @property
    def is_safe_default(self) -> bool:
        return self.category in {
            CATEGORY_PLUGGY_DUPLICATE,
            CATEGORY_UPDATED_REVERT,
        }


@dataclass(slots=True)
class CleanupBatchSummary:
    batch_id: int
    created_at: object
    files: list[str]
    total: int = 0
    pluggy_duplicates: int = 0
    updated_reverts: int = 0
    unique_direct: int = 0
    modified_unique: int = 0
    ambiguous: int = 0
    blocked: int = 0
    missing: int = 0

    @property
    def safe_default(self) -> int:
        return self.pluggy_duplicates + self.updated_reverts


@dataclass(slots=True)
class CleanupPlan:
    entries: list[CleanupEntry]
    batches: list[CleanupBatchSummary]
    confidence_min: int

    @property
    def totals(self) -> dict[str, int]:
        result = defaultdict(int)
        for entry in self.entries:
            result[entry.category] += 1
        result["TOTAL"] = len(self.entries)
        result["SAFE_DEFAULT"] = sum(1 for entry in self.entries if entry.is_safe_default)
        return dict(result)


@dataclass(slots=True)
class CleanupResult:
    effects_reverted: int = 0
    ofx_transactions_deleted: int = 0
    transactions_restored: int = 0
    pluggy_transactions_reactivated: int = 0
    pluggy_transactions_enriched: int = 0
    unique_ofx_deleted: int = 0
    modified_unique_deleted: int = 0
    skipped_modified_unique: int = 0
    skipped_ambiguous: int = 0
    skipped_blocked: int = 0
    batches_archived: int = 0
    affected_transaction_ids: set[int] = field(default_factory=set)


def is_pluggy_transaction(tx: Transaction | None) -> bool:
    if tx is None or tx.source_type != Transaction.SourceType.API:
        return False
    fitid = (tx.fitid or "").upper()
    if fitid.startswith("PLUGGY:") or fitid.startswith("PLUGGY-PROVIDER:"):
        return True
    return str((tx.raw_data or {}).get("provider") or "").upper() == "PLUGGY"


def _active_ofx_effects(*, batch_ids: Iterable[int] | None = None):
    queryset = (
        ImportEffect.objects.select_related(
            "transaction",
            "transaction__account",
            "transaction__account__bank",
            "transaction__counterparty",
            "import_item",
            "import_item__statement",
            "import_item__statement__import_file",
            "import_item__statement__import_file__batch",
        )
        .filter(
            reverted_at__isnull=True,
            import_item__statement__import_file__source_format=ImportFile.SourceFormat.OFX,
            import_item__statement__import_file__batch__cleanup_archived_at__isnull=True,
        )
    )
    if batch_ids is not None:
        queryset = queryset.filter(
            import_item__statement__import_file__batch_id__in=list(batch_ids)
        )
    return queryset.order_by("-applied_at", "-id")


def _later_active_effect_ids(effects: list[ImportEffect]) -> dict[int, bool]:
    selected_ids = {effect.pk for effect in effects}
    transaction_ids = {effect.transaction_id for effect in effects if effect.transaction_id}
    active_by_transaction: dict[int, list[tuple[object, int]]] = defaultdict(list)
    if transaction_ids:
        for row in (
            ImportEffect.objects.filter(
                transaction_id__in=transaction_ids,
                reverted_at__isnull=True,
            )
            .values("id", "transaction_id", "applied_at")
        ):
            if row["id"] not in selected_ids:
                active_by_transaction[row["transaction_id"]].append(
                    (row["applied_at"], row["id"])
                )

    result: dict[int, bool] = {}
    for effect in effects:
        if not effect.transaction_id:
            result[effect.pk] = False
            continue
        key = (effect.applied_at, effect.pk)
        result[effect.pk] = any(
            other_key > key
            for other_key in active_by_transaction.get(effect.transaction_id, [])
        )
    return result


def _review_candidates(transaction_ids: set[int]) -> dict[int, list[tuple[Transaction, int]]]:
    mapping: dict[int, list[tuple[Transaction, int]]] = defaultdict(list)
    if not transaction_ids:
        return mapping

    reviews = (
        TransactionDuplicateReview.objects.select_related(
            "first_transaction",
            "first_transaction__account",
            "first_transaction__account__bank",
            "second_transaction",
            "second_transaction__account",
            "second_transaction__account__bank",
        )
        .filter(
            Q(first_transaction_id__in=transaction_ids)
            | Q(second_transaction_id__in=transaction_ids)
        )
        .order_by("-confidence", "id")
    )

    seen: dict[int, set[int]] = defaultdict(set)
    for review in reviews:
        first = review.first_transaction
        second = review.second_transaction
        if first.pk in transaction_ids and is_pluggy_transaction(second):
            if second.pk not in seen[first.pk]:
                mapping[first.pk].append((second, review.confidence))
                seen[first.pk].add(second.pk)
        if second.pk in transaction_ids and is_pluggy_transaction(first):
            if first.pk not in seen[second.pk]:
                mapping[second.pk].append((first, review.confidence))
                seen[second.pk].add(first.pk)
    return mapping


def _pick_pluggy_candidate(
    candidates: list[tuple[Transaction, int]],
    *,
    confidence_min: int,
) -> tuple[Transaction | None, int, str]:
    eligible = [(tx, score) for tx, score in candidates if score >= confidence_min]
    if not eligible:
        return None, 0, ""
    eligible.sort(key=lambda value: (-value[1], value[0].pk))
    top_tx, top_score = eligible[0]
    if len(eligible) > 1:
        second_tx, second_score = eligible[1]
        if top_score - second_score < 5:
            return None, top_score, (
                "Há mais de um equivalente Pluggy forte e a diferença entre os dois melhores "
                f"é menor que 5 pontos ({top_score}% x {second_score}%; "
                f"movimentações #{top_tx.pk} e #{second_tx.pk})."
            )
    return top_tx, top_score, ""


def _differences(effect: ImportEffect) -> list[FieldDifference]:
    tx = effect.transaction
    if tx is None or not effect.after_data:
        return []
    current = transaction_snapshot(tx)
    differences = []
    for field_name, imported_value in effect.after_data.items():
        current_value = current.get(field_name)
        if current_value != imported_value:
            differences.append(
                FieldDifference(
                    field=field_name,
                    label=FIELD_LABELS.get(field_name, field_name),
                    imported_value=imported_value,
                    current_value=current_value,
                )
            )
    return differences


def build_ofx_cleanup_plan(
    *,
    batch_ids: Iterable[int] | None = None,
    confidence_min: int = 90,
) -> CleanupPlan:
    confidence_min = max(72, min(100, int(confidence_min)))
    effects = list(_active_ofx_effects(batch_ids=batch_ids))
    later_external = _later_active_effect_ids(effects)
    transaction_ids = {effect.transaction_id for effect in effects if effect.transaction_id}
    candidate_map = _review_candidates(transaction_ids)

    entries: list[CleanupEntry] = []
    batch_map: dict[int, CleanupBatchSummary] = {}

    batch_ids_found = {
        effect.import_item.statement.import_file.batch_id for effect in effects
    }
    batches = (
        ImportBatch.objects.prefetch_related("files")
        .filter(pk__in=batch_ids_found)
        .order_by("created_at", "pk")
    )
    for batch in batches:
        batch_map[batch.pk] = CleanupBatchSummary(
            batch_id=batch.pk,
            created_at=batch.created_at,
            files=[
                file.original_name
                for file in batch.files.all()
                if file.source_format == ImportFile.SourceFormat.OFX
            ],
        )

    for effect in effects:
        tx = effect.transaction
        batch_id = effect.import_item.statement.import_file.batch_id
        summary = batch_map[batch_id]
        summary.total += 1
        diffs = _differences(effect)

        common = {
            "effect_id": effect.pk,
            "batch_id": batch_id,
            "import_item_id": effect.import_item_id,
            "transaction_id": tx.pk if tx else None,
            "bank_name": tx.account.bank.name if tx else "—",
            "account_label": tx.account.nickname if tx else "—",
            "posted_at": tx.posted_at if tx else None,
            "amount": tx.amount if tx else None,
            "direction": tx.direction if tx else "",
            "description": tx.raw_description if tx else "",
            "action": effect.action,
            "differences": diffs,
        }

        if tx is None:
            category = CATEGORY_MISSING
            label = "Movimentação já ausente"
            reason = "O efeito ainda está ativo, mas a movimentação não existe mais."
            summary.missing += 1
            entries.append(CleanupEntry(**common, category=category, category_label=label, reason=reason))
            continue

        if later_external.get(effect.pk):
            category = CATEGORY_BLOCKED
            label = "Bloqueada por efeito posterior"
            reason = (
                "Existe uma importação posterior ativa sobre a mesma movimentação que não faz parte "
                "desta limpeza OFX. Ela precisa ser tratada primeiro."
            )
            summary.blocked += 1
            entries.append(CleanupEntry(**common, category=category, category_label=label, reason=reason))
            continue

        if effect.action == ImportEffect.Action.UPDATED:
            category = CATEGORY_UPDATED_REVERT
            label = "Reverter alteração OFX"
            reason = (
                "O OFX atualizou uma movimentação já existente. Será feito um desfazer em três vias: "
                "campos que ainda estão iguais ao OFX voltam ao valor anterior; alterações posteriores "
                "do usuário/sistema são preservadas."
            )
            summary.updated_reverts += 1
            entries.append(CleanupEntry(**common, category=category, category_label=label, reason=reason))
            continue

        candidate, confidence, ambiguity_reason = _pick_pluggy_candidate(
            candidate_map.get(tx.pk, []),
            confidence_min=confidence_min,
        )
        if ambiguity_reason:
            category = CATEGORY_AMBIGUOUS
            label = "Mais de um equivalente Pluggy"
            summary.ambiguous += 1
            entries.append(
                CleanupEntry(
                    **common,
                    category=category,
                    category_label=label,
                    pluggy_confidence=confidence,
                    reason=ambiguity_reason,
                )
            )
            continue

        if candidate is not None:
            category = CATEGORY_PLUGGY_DUPLICATE
            label = "Substituir por Pluggy"
            summary.pluggy_duplicates += 1
            entries.append(
                CleanupEntry(
                    **common,
                    category=category,
                    category_label=label,
                    pluggy_transaction_id=candidate.pk,
                    pluggy_confidence=confidence,
                    pluggy_label=(
                        f"#{candidate.pk} · {candidate.posted_at:%d/%m/%Y %H:%M} · "
                        f"{candidate.raw_description[:100]}"
                    ),
                    reason=(
                        "O Pluggy será mantido como canônico. Pessoa/categoria/documento/referência "
                        "que existirem apenas no OFX serão aproveitados sem substituir a data/hora do Pluggy."
                    ),
                )
            )
            continue

        if not diffs:
            category = CATEGORY_DIRECT_UNIQUE
            label = "OFX único e não alterado"
            reason = (
                "Não foi encontrado equivalente Pluggy com a confiança mínima. A exclusão deste registro "
                "remove informação financeira única e só será feita se você habilitar essa opção explicitamente."
            )
            summary.unique_direct += 1
            entries.append(CleanupEntry(**common, category=category, category_label=label, reason=reason))
            continue

        category = CATEGORY_MODIFIED_UNIQUE
        label = "OFX alterado sem equivalente Pluggy"
        reason = (
            "A movimentação foi criada pelo OFX e recebeu alterações posteriores, mas não há um equivalente "
            "Pluggy seguro para receber esses metadados. Ela ficará preservada para revisão manual."
        )
        summary.modified_unique += 1
        entries.append(CleanupEntry(**common, category=category, category_label=label, reason=reason))

    return CleanupPlan(
        entries=entries,
        batches=list(batch_map.values()),
        confidence_min=confidence_min,
    )


def _merged_raw_data_with_ofx_source(winner: Transaction, loser: Transaction) -> dict:
    raw_data = dict(winner.raw_data or {})
    sources = list(raw_data.get("_ofx_cleanup_sources") or [])
    snapshot = transaction_snapshot(loser)
    snapshot["transaction_id"] = loser.pk
    sources.append(snapshot)
    raw_data["_ofx_cleanup_sources"] = sources[-50:]
    return raw_data


def _enrich_pluggy_from_ofx(pluggy_tx: Transaction, ofx_tx: Transaction) -> bool:
    changed: list[str] = []
    if not pluggy_tx.counterparty_id and ofx_tx.counterparty_id:
        pluggy_tx.counterparty = ofx_tx.counterparty
        changed.append("counterparty")
    if not pluggy_tx.counterparty_raw_name and ofx_tx.counterparty_raw_name:
        pluggy_tx.counterparty_raw_name = ofx_tx.counterparty_raw_name
        changed.append("counterparty_raw_name")
    if not pluggy_tx.category_id and ofx_tx.category_id:
        pluggy_tx.category = ofx_tx.category
        changed.append("category")
    if not pluggy_tx.document and ofx_tx.document:
        pluggy_tx.document = ofx_tx.document
        changed.append("document")
    if not pluggy_tx.reference and ofx_tx.reference:
        pluggy_tx.reference = ofx_tx.reference
        changed.append("reference")
    if not pluggy_tx.normalized_description and ofx_tx.normalized_description:
        pluggy_tx.normalized_description = ofx_tx.normalized_description
        changed.append("normalized_description")

    pluggy_tx.raw_data = _merged_raw_data_with_ofx_source(pluggy_tx, ofx_tx)
    changed.append("raw_data")

    if changed:
        pluggy_tx.save(update_fields=[*dict.fromkeys(changed), "updated_at"])
        return True
    return False


def _reactivate_pluggy_if_ignored_by(pluggy_tx: Transaction, ofx_tx: Transaction) -> bool:
    if not pluggy_tx.is_financially_ignored:
        return False
    if pluggy_tx.canonical_transaction_id != ofx_tx.pk:
        return False
    pluggy_tx.is_financially_ignored = False
    pluggy_tx.ignored_reason = ""
    pluggy_tx.canonical_transaction = None
    pluggy_tx.save(
        update_fields=[
            "is_financially_ignored",
            "ignored_reason",
            "canonical_transaction",
            "updated_at",
        ]
    )
    return True


def _repoint_or_reactivate_merged_dependents(
    ofx_tx: Transaction,
    *,
    replacement: Transaction | None,
) -> None:
    dependents = Transaction.objects.select_for_update().filter(
        canonical_transaction=ofx_tx,
        is_financially_ignored=True,
    ).exclude(pk=replacement.pk if replacement is not None else None)
    if replacement is not None:
        dependents.update(
            canonical_transaction=replacement,
            ignored_reason=(
                f"Duplicidade preservada após limpeza OFX; movimentação canônica #{replacement.pk}."
            ),
        )
    else:
        dependents.update(
            is_financially_ignored=False,
            canonical_transaction=None,
            ignored_reason="",
        )


def _repoint_candidate_pluggy_link(ofx_tx: Transaction, pluggy_tx: Transaction) -> None:
    fitid = (pluggy_tx.fitid or "").strip()
    queryset = PluggyTransactionLink.objects.filter(transaction=ofx_tx)
    matched = None
    if fitid.upper().startswith("PLUGGY-PROVIDER:"):
        provider_id = fitid.split(":", 1)[1]
        matched = queryset.filter(provider_id=provider_id).first()
    elif fitid.upper().startswith("PLUGGY:"):
        remote_id = fitid.split(":", 1)[1]
        matched = queryset.filter(remote_transaction_id=remote_id).first()

    if matched is None:
        links = list(queryset[:2])
        if len(links) == 1 and not PluggyTransactionLink.objects.filter(transaction=pluggy_tx).exists():
            matched = links[0]

    if matched is not None:
        matched.transaction = pluggy_tx
        matched.has_conflict = False
        matched.conflict_fields = []
        matched.save(update_fields=["transaction", "has_conflict", "conflict_fields", "updated_at"])


def _three_way_revert_snapshot(effect: ImportEffect, current: dict) -> dict:
    before = effect.before_data or {}
    after = effect.after_data or {}
    target = dict(current)
    for field_name, before_value in before.items():
        after_value = after.get(field_name)
        current_value = current.get(field_name)
        if before_value == after_value:
            continue
        # Reverte apenas o valor que ainda representa exatamente a alteração
        # da importação. Se houve edição posterior, ela prevalece.
        if current_value == after_value:
            target[field_name] = before_value
    return target


def _mark_effect_reverted(
    effect: ImportEffect,
    *,
    user,
    now,
    cleanup_data: dict | None = None,
) -> None:
    payload = {
        "cleanup_version": "10.9.8",
        "cleaned_at": now.isoformat(),
        "cleaned_by_id": getattr(user, "pk", None),
    }
    if cleanup_data:
        payload.update(cleanup_data)
    ImportEffect.objects.filter(pk=effect.pk, reverted_at__isnull=True).update(
        reverted_at=now,
        cleanup_data=payload,
    )
    ImportItem.objects.filter(pk=effect.import_item_id).update(
        resolution=ImportItem.Resolution.IGNORE,
        commit_status=ImportItem.CommitStatus.SKIPPED,
        imported_transaction=None,
        is_excluded=True,
        excluded_at=now,
        excluded_by=user,
        commit_error_code="",
        commit_error_message="",
        commit_error_details={},
    )


def _archive_completed_batches(batch_ids: set[int], *, user, result: CleanupResult, now) -> None:
    for batch in ImportBatch.objects.filter(pk__in=batch_ids).prefetch_related("files"):
        has_active_effect = ImportEffect.objects.filter(
            import_item__statement__import_file__batch=batch,
            reverted_at__isnull=True,
        ).exists()
        if has_active_effect:
            batch.status = ImportBatch.Status.PARTIAL
            batch.committed_at = None
            batch.save(update_fields=["status", "committed_at", "updated_at"])
            continue

        batch.cleanup_archived_at = now
        batch.cleanup_archived_by = user
        batch.cleanup_note = (
            "Efeitos financeiros OFX removidos pela limpeza assistida; arquivos originais preservados para auditoria."
        )
        batch.status = ImportBatch.Status.ANALYZED
        batch.committed_at = None
        batch.save(
            update_fields=[
                "cleanup_archived_at",
                "cleanup_archived_by",
                "cleanup_note",
                "status",
                "committed_at",
                "updated_at",
            ]
        )
        batch.files.filter(source_format=ImportFile.SourceFormat.OFX).update(
            status=ImportFile.Status.ANALYZED
        )
        result.batches_archived += 1


def execute_ofx_cleanup(
    *,
    user,
    batch_ids: Iterable[int],
    confidence_min: int = 90,
    delete_unique_ofx: bool = False,
    delete_modified_unique_ofx: bool = False,
) -> CleanupResult:
    selected_batch_ids = {int(value) for value in batch_ids}
    if not selected_batch_ids:
        raise OfxCleanupError("Selecione ao menos um lote OFX para a limpeza.")

    plan = build_ofx_cleanup_plan(
        batch_ids=selected_batch_ids,
        confidence_min=confidence_min,
    )
    if not plan.entries:
        raise OfxCleanupError("Não há efeitos OFX ativos nos lotes selecionados.")

    result = CleanupResult()
    now = timezone.now()

    # IDs calculados na prévia são revalidados dentro da transação. O lock
    # impede que decisões concorrentes alterem o mesmo efeito durante a limpeza.
    entry_by_effect = {entry.effect_id: entry for entry in plan.entries}

    with db_transaction.atomic():
        effects = list(
            _active_ofx_effects(batch_ids=selected_batch_ids)
            .select_for_update()
        )
        if {effect.pk for effect in effects} != set(entry_by_effect):
            raise OfxCleanupError(
                "As importações mudaram enquanto a limpeza era preparada. Nenhuma alteração foi aplicada; atualize a página e tente novamente."
            )

        active_keys_by_transaction: dict[int, set[tuple[object, int]]] = defaultdict(set)
        locked_transaction_ids = {effect.transaction_id for effect in effects if effect.transaction_id}
        if locked_transaction_ids:
            for row in (
                ImportEffect.objects.filter(
                    transaction_id__in=locked_transaction_ids,
                    reverted_at__isnull=True,
                )
                .values("id", "transaction_id", "applied_at")
            ):
                active_keys_by_transaction[row["transaction_id"]].add(
                    (row["applied_at"], row["id"])
                )

        def has_later_active(effect_to_check: ImportEffect) -> bool:
            if not effect_to_check.transaction_id:
                return False
            key = (effect_to_check.applied_at, effect_to_check.pk)
            return any(
                other_key > key
                for other_key in active_keys_by_transaction.get(effect_to_check.transaction_id, set())
            )

        def mark_effect_inactive(effect_to_mark: ImportEffect) -> None:
            if not effect_to_mark.transaction_id:
                return
            active_keys_by_transaction.get(effect_to_mark.transaction_id, set()).discard(
                (effect_to_mark.applied_at, effect_to_mark.pk)
            )

        for effect in effects:
            entry = entry_by_effect[effect.pk]
            if has_later_active(effect):
                result.skipped_blocked += 1
                continue
            if entry.category == CATEGORY_BLOCKED:
                result.skipped_blocked += 1
                continue
            if entry.category == CATEGORY_AMBIGUOUS:
                result.skipped_ambiguous += 1
                continue
            if entry.category == CATEGORY_MODIFIED_UNIQUE and not delete_modified_unique_ofx:
                result.skipped_modified_unique += 1
                continue
            if entry.category == CATEGORY_DIRECT_UNIQUE and not delete_unique_ofx:
                continue

            tx = Transaction.objects.select_for_update().filter(pk=effect.transaction_id).first()
            if tx is None:
                _mark_effect_reverted(
                    effect,
                    user=user,
                    now=now,
                    cleanup_data={
                        "category": entry.category,
                        "transaction_missing": True,
                    },
                )
                result.effects_reverted += 1
                mark_effect_inactive(effect)
                continue

            if entry.category == CATEGORY_UPDATED_REVERT:
                current = transaction_snapshot(tx)
                target = _three_way_revert_snapshot(effect, current)
                restore_transaction_snapshot(tx, target)
                result.transactions_restored += 1
                result.affected_transaction_ids.add(tx.pk)
                _mark_effect_reverted(
                    effect,
                    user=user,
                    now=now,
                    cleanup_data={
                        "category": entry.category,
                        "transaction_id": tx.pk,
                        "current_before_cleanup": current,
                        "restored_snapshot": target,
                    },
                )
                result.effects_reverted += 1
                mark_effect_inactive(effect)
                continue

            if entry.category == CATEGORY_PLUGGY_DUPLICATE:
                pluggy_tx = (
                    Transaction.objects.select_for_update()
                    .filter(pk=entry.pluggy_transaction_id)
                    .first()
                )
                if pluggy_tx is None or not is_pluggy_transaction(pluggy_tx):
                    raise OfxCleanupError(
                        f"O equivalente Pluggy da movimentação OFX #{tx.pk} não está mais disponível. Nenhuma alteração foi aplicada."
                    )
                if _reactivate_pluggy_if_ignored_by(pluggy_tx, tx):
                    result.pluggy_transactions_reactivated += 1
                if _enrich_pluggy_from_ofx(pluggy_tx, tx):
                    result.pluggy_transactions_enriched += 1
                _repoint_candidate_pluggy_link(tx, pluggy_tx)
                result.affected_transaction_ids.add(pluggy_tx.pk)

            if entry.category == CATEGORY_DIRECT_UNIQUE:
                result.unique_ofx_deleted += 1
                _repoint_or_reactivate_merged_dependents(tx, replacement=None)
            elif entry.category == CATEGORY_MODIFIED_UNIQUE:
                result.modified_unique_deleted += 1
                _repoint_or_reactivate_merged_dependents(tx, replacement=None)
            elif entry.category == CATEGORY_PLUGGY_DUPLICATE:
                _repoint_or_reactivate_merged_dependents(tx, replacement=pluggy_tx)

            current_before_delete = transaction_snapshot(tx)
            InternalTransfer.objects.filter(
                Q(debit_transaction=tx) | Q(credit_transaction=tx)
            ).delete()
            tx_id = tx.pk
            tx.delete()
            result.ofx_transactions_deleted += 1
            _mark_effect_reverted(
                effect,
                user=user,
                now=now,
                cleanup_data={
                    "category": entry.category,
                    "deleted_transaction_id": tx_id,
                    "current_before_cleanup": current_before_delete,
                    "pluggy_replacement_id": entry.pluggy_transaction_id,
                    "pluggy_confidence": entry.pluggy_confidence,
                },
            )
            result.effects_reverted += 1
            mark_effect_inactive(effect)
            # tx foi removida; não deve ser reanalisada, mas registramos para auditoria.
            result.affected_transaction_ids.discard(tx_id)

        _archive_completed_batches(selected_batch_ids, user=user, result=result, now=now)

        affected_ids = tuple(sorted(result.affected_transaction_ids))
        if affected_ids:
            def _reanalyze_after_commit(ids=affected_ids):
                from services.duplicates import analyze_duplicates
                from services.internal_transfers import analyze_internal_transfers

                analyze_duplicates(transaction_ids=ids, quarantine_new=False)
                analyze_internal_transfers(transaction_ids=ids)

            db_transaction.on_commit(_reanalyze_after_commit, robust=True)

    return result
