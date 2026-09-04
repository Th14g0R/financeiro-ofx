from __future__ import annotations

from dataclasses import dataclass

from django.core.files.base import ContentFile
from django.db import transaction as db_transaction
from django.db.models import Q
from django.utils import timezone

from imports.models import ImportBatch
from imports.models import ImportEffect
from imports.models import ImportFile
from imports.models import ImportItem
from services.importing.commit import restore_transaction_snapshot
from services.importing.commit import transaction_snapshot
from services.importing.staging import stage_uploaded_file


class ImportRollbackError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StoredImportFile:
    name: str
    content: bytes


def _has_later_active_effect(effect: ImportEffect) -> bool:
    if effect.transaction_id is None:
        return False

    return (
        ImportEffect.objects.filter(
            transaction_id=effect.transaction_id,
            reverted_at__isnull=True,
        )
        .filter(
            Q(applied_at__gt=effect.applied_at)
            | Q(
                applied_at=effect.applied_at,
                pk__gt=effect.pk,
            )
        )
        .exclude(pk=effect.pk)
        .exists()
    )


@db_transaction.atomic
def rollback_batch(batch: ImportBatch):
    effects = list(
        ImportEffect.objects.select_related(
            "transaction",
            "import_item",
        )
        .filter(
            import_item__statement__import_file__batch=batch,
            reverted_at__isnull=True,
        )
        .order_by("-applied_at", "-id")
    )

    for effect in effects:
        if _has_later_active_effect(effect):
            raise ImportRollbackError(
                "Esta importação possui movimentações alteradas por uma "
                "importação posterior. Desfaça a importação posterior "
                "primeiro para preservar a integridade do histórico."
            )

        transaction = effect.transaction

        if (
            transaction is not None
            and effect.after_data
            and transaction_snapshot(transaction) != effect.after_data
        ):
            raise ImportRollbackError(
                "Uma movimentação deste lote foi alterada depois da "
                "importação. O sistema não a desfará automaticamente "
                "para não perder alterações posteriores."
            )

        if effect.action == ImportEffect.Action.CREATED:
            if transaction is not None:
                transaction.delete()

        elif effect.action == ImportEffect.Action.UPDATED:
            if transaction is None:
                raise ImportRollbackError(
                    "Não foi possível localizar uma movimentação "
                    "atualizada por esta importação."
                )

            restore_transaction_snapshot(
                transaction,
                effect.before_data,
            )

        reverted_at = timezone.now()

        # Quando a ação CREATED exclui a Transaction, o Django mantém
        # o objeto Python em memória com pk=None. O efeito carregado via
        # select_related ainda pode manter essa referência em cache.
        #
        # Um effect.save() nesse ponto dispara a proteção do Django contra
        # objetos relacionados não salvos. Como precisamos atualizar apenas
        # a coluna reverted_at, usamos UPDATE direto no banco, sem passar
        # pela validação de relações em memória do Model.save().
        ImportEffect.objects.filter(
            pk=effect.pk,
            reverted_at__isnull=True,
        ).update(
            reverted_at=reverted_at
        )

        # Mantém a instância atual coerente caso seja consultada novamente
        # dentro deste mesmo fluxo.
        effect.reverted_at = reverted_at

        if effect.action == ImportEffect.Action.CREATED:
            effect.transaction_id = None

    # Compatibilidade com lotes gravados antes da criação do ImportEffect.
    legacy_created = (
        ImportItem.objects.select_related(
            "imported_transaction"
        )
        .filter(
            statement__import_file__batch=batch,
            commit_status=ImportItem.CommitStatus.CREATED,
            effect__isnull=True,
        )
    )

    for item in legacy_created:
        if item.imported_transaction_id:
            later_effect = ImportEffect.objects.filter(
                transaction_id=item.imported_transaction_id,
                reverted_at__isnull=True,
            ).exists()

            if later_effect:
                raise ImportRollbackError(
                    "Uma movimentação legada desta importação já foi "
                    "utilizada por outra importação."
                )

            item.imported_transaction.delete()

    legacy_updated = ImportItem.objects.filter(
        statement__import_file__batch=batch,
        commit_status=ImportItem.CommitStatus.UPDATED,
        effect__isnull=True,
    ).exists()

    if legacy_updated:
        raise ImportRollbackError(
            "Este lote contém atualizações feitas por uma versão antiga "
            "do sistema, sem snapshot anterior. Ele não pode ser desfeito "
            "automaticamente com segurança."
        )

    batch.status = ImportBatch.Status.ANALYZED
    batch.committed_at = None
    batch.save(
        update_fields=[
            "status",
            "committed_at",
            "updated_at",
        ]
    )


def _read_current_files(batch: ImportBatch) -> list[StoredImportFile]:
    stored_files = []

    for import_file in batch.files.all().order_by("id"):
        if not import_file.file:
            continue

        import_file.file.open("rb")

        try:
            content = import_file.file.read()
        finally:
            import_file.file.close()

        stored_files.append(
            StoredImportFile(
                name=import_file.original_name,
                content=content,
            )
        )

    return stored_files


def _schedule_file_deletion(import_files):
    for import_file in import_files:
        if not import_file.file:
            continue

        storage = import_file.file.storage
        name = import_file.file.name

        db_transaction.on_commit(
            lambda storage=storage, name=name: storage.delete(name)
        )


@db_transaction.atomic
def reprocess_batch(
    *,
    batch: ImportBatch,
    replacement_files=None,
):
    replacement_files = list(replacement_files or [])

    if replacement_files:
        source_files = replacement_files
    else:
        source_files = [
            ContentFile(
                stored.content,
                name=stored.name,
            )
            for stored in _read_current_files(batch)
        ]

    if not source_files:
        raise ImportRollbackError(
            "Não há arquivos disponíveis para reprocessar."
        )

    rollback_batch(batch)

    old_files = list(batch.files.all())
    _schedule_file_deletion(old_files)
    batch.files.all().delete()

    batch.status = ImportBatch.Status.ANALYZING
    batch.committed_at = None
    batch.reprocessed_at = timezone.now()
    batch.save(
        update_fields=[
            "status",
            "committed_at",
            "reprocessed_at",
            "updated_at",
        ]
    )

    analyzed = 0

    for source_file in source_files:
        import_file = stage_uploaded_file(
            batch=batch,
            uploaded_file=source_file,
        )

        if import_file.status != ImportFile.Status.FAILED:
            analyzed += 1

    batch.status = (
        ImportBatch.Status.ANALYZED
        if analyzed
        else ImportBatch.Status.FAILED
    )
    batch.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    return analyzed


@db_transaction.atomic
def delete_batch(batch: ImportBatch):
    rollback_batch(batch)

    old_files = list(batch.files.all())
    _schedule_file_deletion(old_files)

    batch.delete()
