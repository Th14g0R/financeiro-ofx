from __future__ import annotations

from datetime import date
from datetime import datetime
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.utils import timezone

from finance.models import Transaction
from imports.models import ImportBatch
from imports.models import ImportEffect
from imports.models import ImportFile
from imports.models import ImportItem
from services.counterparties import resolve_transaction_counterparty
from services.importing.staging import reclassify_import_item


class ImportCommitError(ValueError):
    pass


def transaction_snapshot(transaction: Transaction) -> dict:
    return {
        "account_id": transaction.account_id,
        "posted_at": transaction.posted_at.isoformat(),
        "competence_date": (
            transaction.competence_date.isoformat()
            if transaction.competence_date
            else None
        ),
        "amount": str(transaction.amount),
        "direction": transaction.direction,
        "transaction_type": transaction.transaction_type,
        "source_type": transaction.source_type,
        "fitid": transaction.fitid,
        "raw_description": transaction.raw_description,
        "normalized_description": transaction.normalized_description,
        "document": transaction.document,
        "reference": transaction.reference,
        "fingerprint": transaction.fingerprint,
        "fingerprint_version": transaction.fingerprint_version,
        "raw_data": transaction.raw_data,
        "notes": transaction.notes,
        "category_id": transaction.category_id,
        "counterparty_id": transaction.counterparty_id,
        "counterparty_raw_name": transaction.counterparty_raw_name,
    }


def restore_transaction_snapshot(
    transaction: Transaction,
    snapshot: dict,
) -> Transaction:
    posted_at = datetime.fromisoformat(snapshot["posted_at"])

    if timezone.is_naive(posted_at):
        posted_at = timezone.make_aware(
            posted_at,
            timezone.get_current_timezone(),
        )

    competence_date = snapshot.get("competence_date")

    transaction.account_id = snapshot["account_id"]
    transaction.posted_at = posted_at
    transaction.competence_date = (
        date.fromisoformat(competence_date)
        if competence_date
        else None
    )
    transaction.amount = snapshot["amount"]
    transaction.direction = snapshot["direction"]
    transaction.transaction_type = snapshot["transaction_type"]
    transaction.source_type = snapshot["source_type"]
    transaction.fitid = snapshot.get("fitid", "")
    transaction.raw_description = snapshot.get(
        "raw_description",
        "",
    )
    transaction.normalized_description = snapshot.get(
        "normalized_description",
        "",
    )
    transaction.document = snapshot.get("document", "")
    transaction.reference = snapshot.get("reference", "")
    transaction.fingerprint = snapshot.get("fingerprint", "")
    transaction.fingerprint_version = snapshot.get(
        "fingerprint_version",
        1,
    )
    transaction.raw_data = snapshot.get("raw_data", {})
    transaction.notes = snapshot.get("notes", "")
    transaction.category_id = snapshot.get("category_id")
    transaction.counterparty_id = snapshot.get("counterparty_id")
    transaction.counterparty_raw_name = snapshot.get(
        "counterparty_raw_name",
        "",
    )

    transaction.full_clean()
    transaction.save()

    return transaction


def _source_type_for_item(
    item: ImportItem,
) -> str:
    source_format = (
        item.statement.import_file.source_format
    )

    if (
        source_format
        == ImportFile.SourceFormat.PDF
    ):
        return Transaction.SourceType.PDF

    if (
        source_format
        == ImportFile.SourceFormat.API_CSV
    ):
        return Transaction.SourceType.API

    return Transaction.SourceType.OFX


def _create_transaction(item: ImportItem, user) -> Transaction:
    account = item.statement.matched_account

    if account is None:
        raise ImportCommitError(
            "A movimentação não possui uma conta relacionada."
        )

    transaction = Transaction(
        account=account,
        posted_at=item.posted_at,
        competence_date=item.posted_at.date(),
        amount=item.amount,
        direction=item.direction,
        transaction_type=item.transaction_type,
        source_type=_source_type_for_item(item),
        fitid=item.fitid,
        raw_description=item.raw_description,
        normalized_description="",
        document=item.document,
        reference=item.reference,
        fingerprint=item.fingerprint,
        fingerprint_version=2,
        raw_data=item.raw_data,
        created_by=user,
    )

    transaction.full_clean()
    transaction.save()

    resolve_transaction_counterparty(transaction)

    ImportEffect.objects.create(
        import_item=item,
        transaction=transaction,
        action=ImportEffect.Action.CREATED,
        before_data={},
        after_data=transaction_snapshot(transaction),
    )

    return transaction


def _update_transaction(
    item: ImportItem,
    transaction: Transaction,
):
    account = item.statement.matched_account

    if account is None:
        raise ImportCommitError(
            "A movimentação não possui uma conta relacionada."
        )

    before_data = transaction_snapshot(transaction)

    transaction.account = account
    transaction.posted_at = item.posted_at
    transaction.competence_date = item.posted_at.date()
    transaction.amount = item.amount
    transaction.direction = item.direction
    transaction.transaction_type = item.transaction_type
    transaction.source_type = _source_type_for_item(item)
    transaction.fitid = item.fitid
    transaction.raw_description = item.raw_description
    transaction.document = item.document
    transaction.reference = item.reference
    transaction.fingerprint = item.fingerprint
    transaction.fingerprint_version = 2
    transaction.raw_data = item.raw_data

    transaction.full_clean()
    transaction.save()

    resolve_transaction_counterparty(transaction)

    ImportEffect.objects.create(
        import_item=item,
        transaction=transaction,
        action=ImportEffect.Action.UPDATED,
        before_data=before_data,
        after_data=transaction_snapshot(transaction),
    )

    return transaction


def _validation_details(exc: ValidationError) -> dict[str, Any]:
    if hasattr(exc, "message_dict"):
        return {
            field: list(messages)
            for field, messages in exc.message_dict.items()
        }

    return {
        "__all__": list(exc.messages),
    }


def _flatten_details(details: dict[str, Any]) -> str:
    parts = []

    for field, messages in details.items():
        label = "registro" if field == "__all__" else field

        for message in messages:
            parts.append(f"{label}: {message}")

    return " | ".join(parts)


def describe_commit_exception(exc: Exception) -> tuple[str, str, dict]:
    if isinstance(exc, ValidationError):
        details = _validation_details(exc)
        raw_text = _flatten_details(details)
        lowered = raw_text.lower()

        if "fitid" in lowered:
            return (
                "DUPLICATE_FITID",
                "FITID duplicado para esta conta.",
                details,
            )

        if "amount" in lowered or "valor" in lowered:
            return (
                "INVALID_AMOUNT",
                "Valor inválido para gravação.",
                details,
            )

        if (
            "raw_description" in lowered
            or "descrição original" in lowered
            or "description" in lowered
        ):
            return (
                "INVALID_DESCRIPTION",
                "Descrição inválida ou ausente.",
                details,
            )

        return (
            "VALIDATION_ERROR",
            "A movimentação não passou na validação.",
            details,
        )

    if isinstance(exc, IntegrityError):
        raw_text = str(exc)
        lowered = raw_text.lower()

        if "fitid" in lowered:
            return (
                "DUPLICATE_FITID",
                "FITID duplicado para esta conta.",
                {"database": raw_text},
            )

        return (
            "INTEGRITY_ERROR",
            "Conflito de integridade no banco de dados.",
            {"database": raw_text},
        )

    if isinstance(exc, ImportCommitError):
        return (
            "IMPORT_ERROR",
            str(exc),
            {"error": str(exc)},
        )

    return (
        "UNKNOWN_ERROR",
        "Erro não identificado durante a gravação.",
        {"error": str(exc)},
    )


def _record_item_error(
    item: ImportItem,
    exc: Exception,
):
    code, message, details = describe_commit_exception(exc)

    item.commit_error_code = code
    item.commit_error_message = message
    item.commit_error_details = details
    item.commit_status = ImportItem.CommitStatus.PENDING
    item.imported_transaction = None

    item.save(
        update_fields=[
            "commit_error_code",
            "commit_error_message",
            "commit_error_details",
            "commit_status",
            "imported_transaction",
        ]
    )


def refresh_batch_status(batch: ImportBatch):
    items = ImportItem.objects.filter(
        statement__import_file__batch=batch
    )

    for import_file in batch.files.all():
        if import_file.status in {
            ImportFile.Status.FAILED,
            ImportFile.Status.DUPLICATE_FILE,
        }:
            continue

        has_pending = items.filter(
            statement__import_file=import_file,
            commit_status=ImportItem.CommitStatus.PENDING,
            is_excluded=False,
        ).exists()

        import_file.status = (
            ImportFile.Status.PARTIAL
            if has_pending
            else ImportFile.Status.IMPORTED
        )
        import_file.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

    has_pending_batch = items.filter(
        commit_status=ImportItem.CommitStatus.PENDING,
        is_excluded=False,
    ).exists()

    batch.status = (
        ImportBatch.Status.PARTIAL
        if has_pending_batch
        else ImportBatch.Status.COMMITTED
    )

    if batch.status == ImportBatch.Status.COMMITTED:
        if batch.committed_at is None:
            batch.committed_at = timezone.now()
    else:
        batch.committed_at = None

    batch.save(
        update_fields=[
            "status",
            "committed_at",
            "updated_at",
        ]
    )


def _skip_item(
    item: ImportItem,
    *,
    resolution: str,
):
    item.resolution = resolution
    item.commit_status = ImportItem.CommitStatus.SKIPPED
    item.imported_transaction = item.existing_transaction
    item.save(
        update_fields=[
            "resolution",
            "commit_status",
            "imported_transaction",
        ]
    )


def commit_item(
    *,
    item: ImportItem,
    user,
    divergent_resolution: str | None = None,
    force_possible_duplicate: bool = False,
) -> dict[str, int | str]:
    """
    Grava um item isoladamente.

    Retorno status:
      created / updated / skipped / unresolved / pending_review / failed
    """
    if item.is_excluded:
        _skip_item(
            item,
            resolution=ImportItem.Resolution.IGNORE,
        )
        return {"status": "skipped"}

    reclassify_import_item(
        item,
        clear_commit_error=True,
    )

    if (
        item.classification
        == ImportItem.Classification.UNRESOLVED_ACCOUNT
    ):
        return {"status": "unresolved"}

    if item.classification == ImportItem.Classification.INVALID:
        _skip_item(
            item,
            resolution=ImportItem.Resolution.IGNORE,
        )
        return {"status": "skipped"}

    if item.classification == ImportItem.Classification.DUPLICATE:
        _skip_item(
            item,
            resolution=ImportItem.Resolution.KEEP_CURRENT,
        )
        return {"status": "skipped"}

    if (
        item.classification
        == ImportItem.Classification.POSSIBLE_DUPLICATE
        and not force_possible_duplicate
    ):
        item.resolution = ImportItem.Resolution.PENDING
        item.save(update_fields=["resolution"])
        return {"status": "pending_review"}

    try:
        with db_transaction.atomic():
            if (
                item.classification
                == ImportItem.Classification.DIVERGENT
            ):
                resolution = (
                    divergent_resolution
                    or item.resolution
                    or ImportItem.Resolution.KEEP_CURRENT
                )

                valid_resolutions = {
                    ImportItem.Resolution.KEEP_CURRENT,
                    ImportItem.Resolution.UPDATE,
                    ImportItem.Resolution.IGNORE,
                }

                if resolution not in valid_resolutions:
                    resolution = ImportItem.Resolution.KEEP_CURRENT

                item.resolution = resolution

                if resolution == ImportItem.Resolution.UPDATE:
                    if item.existing_transaction is None:
                        raise ImportCommitError(
                            "Movimentação divergente sem registro existente."
                        )

                    transaction = _update_transaction(
                        item,
                        item.existing_transaction,
                    )

                    item.imported_transaction = transaction
                    item.commit_status = ImportItem.CommitStatus.UPDATED
                    item.save(
                        update_fields=[
                            "resolution",
                            "commit_status",
                            "imported_transaction",
                        ]
                    )
                    return {"status": "updated"}

                _skip_item(
                    item,
                    resolution=resolution,
                )
                return {"status": "skipped"}

            if (
                item.classification
                in {
                    ImportItem.Classification.NEW,
                    ImportItem.Classification.POSSIBLE_DUPLICATE,
                }
            ):
                transaction = _create_transaction(
                    item,
                    user,
                )

                item.resolution = (
                    ImportItem.Resolution.IMPORT_ANYWAY
                    if (
                        item.classification
                        == ImportItem.Classification.POSSIBLE_DUPLICATE
                    )
                    else ImportItem.Resolution.IMPORT
                )
                item.imported_transaction = transaction
                item.commit_status = ImportItem.CommitStatus.CREATED
                item.save(
                    update_fields=[
                        "resolution",
                        "commit_status",
                        "imported_transaction",
                    ]
                )
                return {"status": "created"}

            raise ImportCommitError(
                "Classificação não suportada para gravação: "
                f"{item.classification}."
            )

    except (IntegrityError, ValidationError, ImportCommitError) as exc:
        if item.existing_transaction_id:
            item.existing_transaction.refresh_from_db()

        _record_item_error(item, exc)
        return {"status": "failed"}


@db_transaction.atomic
def commit_batch(
    *,
    batch: ImportBatch,
    user,
    divergent_resolutions: dict[int, str] | None = None,
):
    divergent_resolutions = divergent_resolutions or {}

    pending_items = list(
        ImportItem.objects.select_related(
            "statement",
            "statement__import_file",
            "statement__matched_account",
            "existing_transaction",
        )
        .filter(
            statement__import_file__batch=batch,
            commit_status=ImportItem.CommitStatus.PENDING,
        )
        .order_by(
            "statement__import_file_id",
            "statement_id",
            "sequence",
            "id",
        )
    )

    counters = {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "unresolved": 0,
        "failed": 0,
        "pending_review": 0,
    }

    for item in pending_items:
        result = commit_item(
            item=item,
            user=user,
            divergent_resolution=divergent_resolutions.get(
                item.pk
            ),
            force_possible_duplicate=False,
        )

        status = result["status"]

        if status in counters:
            counters[status] += 1

    refresh_batch_status(batch)

    affected_transaction_ids = tuple(
        sorted(
            {
                item.imported_transaction_id
                for item in pending_items
                if item.imported_transaction_id
                and item.commit_status
                in {
                    ImportItem.CommitStatus.CREATED,
                    ImportItem.CommitStatus.UPDATED,
                }
            }
        )
    )

    if affected_transaction_ids:
        def analyze_after_commit():
            from services.internal_transfers import (
                analyze_internal_transfers,
            )

            analyze_internal_transfers(
                transaction_ids=(
                    affected_transaction_ids
                )
            )

        db_transaction.on_commit(
            analyze_after_commit,
            robust=True,
        )

    return counters
