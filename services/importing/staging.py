from __future__ import annotations

import hashlib
from pathlib import Path
from datetime import datetime
from datetime import timezone as datetime_timezone
from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone

from finance.models import Transaction
from imports.models import ImportBatch
from imports.models import ImportFile
from imports.models import ImportItem
from imports.models import ImportStatement
from services.statements import StatementParseError
from services.statements import parse_statement_bytes
from services.ofx.account_matcher import match_statement
from services.ofx.mapping import map_direction
from services.ofx.mapping import map_transaction_type
from services.ofx.models import ParsedTransaction


class StagingError(ValueError):
    pass


def source_format_from_filename(
    filename: str,
) -> str:
    extension = Path(
        filename
    ).suffix.lower()

    if extension == ".pdf":
        return ImportFile.SourceFormat.PDF

    if extension == ".csv":
        return ImportFile.SourceFormat.CSV

    return ImportFile.SourceFormat.OFX


def calculate_file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def ensure_aware(value: datetime) -> datetime:
    if timezone.is_naive(value):
        return timezone.make_aware(
            value,
            timezone.get_current_timezone(),
        )

    return value


def ensure_optional_aware(
    value: datetime | None,
) -> datetime | None:
    if value is None:
        return None

    return ensure_aware(value)


def build_description(transaction: ParsedTransaction) -> str:
    return " ".join(
        transaction.description.split()
    ).strip()


def build_fingerprint(
    *,
    account_id: int,
    posted_at: datetime,
    signed_amount: Decimal,
    transaction_type: str,
    description: str,
    document: str,
    reference: str,
) -> str:
    """
    Fingerprint heurístico para lançamentos SEM FITID.

    A data/hora é convertida para UTC antes do hash. Isso evita que o mesmo
    instante gere fingerprints diferentes apenas porque um objeto ainda está
    em America/Fortaleza e outro já foi desserializado pelo Django em UTC.
    """
    canonical_posted_at = posted_at

    if timezone.is_naive(canonical_posted_at):
        canonical_posted_at = timezone.make_aware(
            canonical_posted_at,
            timezone.get_current_timezone(),
        )

    canonical_posted_at = canonical_posted_at.astimezone(
        datetime_timezone.utc
    ).replace(
        microsecond=0
    )

    payload = "|".join(
        [
            str(account_id),
            canonical_posted_at.isoformat(),
            f"{signed_amount:.2f}",
            transaction_type.strip().upper(),
            " ".join(description.split()).upper(),
            document.strip().upper(),
            reference.strip().upper(),
        ]
    )

    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()


def compare_existing(
    existing: Transaction,
    *,
    posted_at: datetime,
    amount: Decimal,
    direction: str,
    transaction_type: str,
    raw_description: str,
    document: str,
    reference: str,
) -> list[str]:
    differences = []

    existing_posted_at = existing.posted_at
    if timezone.is_naive(existing_posted_at):
        existing_posted_at = timezone.make_aware(
            existing_posted_at,
            timezone.get_current_timezone(),
        )

    if existing_posted_at != posted_at:
        differences.append("posted_at")

    if existing.amount != amount:
        differences.append("amount")

    if existing.direction != direction:
        differences.append("direction")

    if existing.transaction_type != transaction_type:
        differences.append("transaction_type")

    if existing.raw_description.strip() != raw_description.strip():
        differences.append("raw_description")

    if existing.document.strip() != document.strip():
        differences.append("document")

    if existing.reference.strip() != reference.strip():
        differences.append("reference")

    return differences


def classify_values(
    *,
    account,
    fitid: str,
    posted_at: datetime,
    amount: Decimal,
    direction: str,
    transaction_type: str,
    raw_description: str,
    document: str,
    reference: str,
    fingerprint: str,
):
    if account is None:
        return (
            ImportItem.Classification.UNRESOLVED_ACCOUNT,
            None,
            [],
        )

    normalized_fitid = fitid.strip()

    # Regra principal OFX:
    # -----------------------------------------------
    # FITID presente é a identidade bancária da operação dentro da conta.
    #
    # Mesmo valor + mesma data + mesma descrição + FITID DIFERENTE
    # são operações distintas e legítimas.
    #
    # O fingerprint NÃO pode invalidar um FITID diferente.
    if normalized_fitid:
        existing = (
            Transaction.objects.filter(
                account=account,
                fitid=normalized_fitid,
            )
            .order_by("id")
            .first()
        )

        if existing:
            differences = compare_existing(
                existing,
                posted_at=posted_at,
                amount=amount,
                direction=direction,
                transaction_type=transaction_type,
                raw_description=raw_description,
                document=document,
                reference=reference,
            )

            if differences:
                return (
                    ImportItem.Classification.DIVERGENT,
                    existing,
                    differences,
                )

            return (
                ImportItem.Classification.DUPLICATE,
                existing,
                [],
            )

        return (
            ImportItem.Classification.NEW,
            None,
            [],
        )

    # Sem FITID não há identidade bancária suficientemente forte.
    # O fingerprint passa a ser SOMENTE uma heurística.
    existing = (
        Transaction.objects.filter(
            account=account,
            fitid="",
            fingerprint=fingerprint,
        )
        .order_by("id")
        .first()
    )

    # Compatibilidade com fingerprints antigos (v1), que podiam mudar quando
    # o timezone do DateTimeField era normalizado pelo banco. Se o hash não
    # encontrou o registro, fazemos uma comparação estrutural conservadora.
    if existing is None:
        existing = (
            Transaction.objects.filter(
                account=account,
                fitid="",
                posted_at=posted_at,
                amount=amount,
                direction=direction,
                transaction_type=transaction_type,
                raw_description=raw_description,
                document=document,
                reference=reference,
            )
            .order_by("id")
            .first()
        )

    if existing:
        return (
            ImportItem.Classification.POSSIBLE_DUPLICATE,
            existing,
            ["fitid_missing"],
        )

    return (
        ImportItem.Classification.NEW,
        None,
        [],
    )


def default_resolution_for(classification: str) -> str:
    mapping = {
        ImportItem.Classification.NEW: ImportItem.Resolution.IMPORT,
        ImportItem.Classification.DUPLICATE: (
            ImportItem.Resolution.KEEP_CURRENT
        ),
        ImportItem.Classification.POSSIBLE_DUPLICATE: (
            ImportItem.Resolution.PENDING
        ),
        ImportItem.Classification.DIVERGENT: (
            ImportItem.Resolution.KEEP_CURRENT
        ),
        ImportItem.Classification.UNRESOLVED_ACCOUNT: (
            ImportItem.Resolution.PENDING
        ),
        ImportItem.Classification.INVALID: ImportItem.Resolution.IGNORE,
        ImportItem.Classification.COMMIT_ERROR: (
            ImportItem.Resolution.PENDING
        ),
    }

    return mapping[classification]


def reclassify_import_item(
    item: ImportItem,
    *,
    clear_commit_error: bool = True,
) -> ImportItem:
    account = item.statement.matched_account

    item.fingerprint = build_fingerprint(
        account_id=account.pk if account else 0,
        posted_at=item.posted_at,
        signed_amount=item.signed_amount,
        transaction_type=item.transaction_type,
        description=item.raw_description,
        document=item.document,
        reference=item.reference,
    )

    if item.amount == Decimal("0.00"):
        item.classification = ImportItem.Classification.INVALID
        item.existing_transaction = None
        item.divergence_fields = ["amount"]
    else:
        (
            item.classification,
            item.existing_transaction,
            item.divergence_fields,
        ) = classify_values(
            account=account,
            fitid=item.fitid,
            posted_at=item.posted_at,
            amount=item.amount,
            direction=item.direction,
            transaction_type=item.transaction_type,
            raw_description=item.raw_description,
            document=item.document,
            reference=item.reference,
            fingerprint=item.fingerprint,
        )

    item.resolution = default_resolution_for(
        item.classification
    )

    if clear_commit_error:
        item.commit_error_code = ""
        item.commit_error_message = ""
        item.commit_error_details = {}

    item.imported_transaction = None

    if not item.is_excluded:
        item.commit_status = ImportItem.CommitStatus.PENDING

    update_fields = [
        "fingerprint",
        "classification",
        "existing_transaction",
        "divergence_fields",
        "resolution",
        "imported_transaction",
        "commit_status",
    ]

    if clear_commit_error:
        update_fields.extend(
            [
                "commit_error_code",
                "commit_error_message",
                "commit_error_details",
            ]
        )

    item.save(update_fields=update_fields)

    return item


@db_transaction.atomic
def stage_uploaded_file(
    *,
    batch: ImportBatch,
    uploaded_file,
) -> ImportFile:
    content = uploaded_file.read()
    uploaded_file.seek(0)

    file_hash = calculate_file_hash(content)

    previous_imported = (
        ImportFile.objects.filter(
            file_hash=file_hash,
            status=ImportFile.Status.IMPORTED,
        )
        .order_by("-id")
        .first()
    )

    import_file = ImportFile.objects.create(
        batch=batch,
        file=uploaded_file,
        original_name=uploaded_file.name,
        file_hash=file_hash,
        file_size=uploaded_file.size,
        status=(
            ImportFile.Status.DUPLICATE_FILE
            if previous_imported
            else ImportFile.Status.ANALYZED
        ),
        duplicate_of=previous_imported,
        source_format=(
            previous_imported.source_format
            if previous_imported
            else source_format_from_filename(
                uploaded_file.name
            )
        ),
        provider=(
            previous_imported.provider
            if previous_imported
            else ImportFile.Provider.GENERIC
        ),
    )

    if previous_imported:
        return import_file

    try:
        parsed_document = parse_statement_bytes(
            content=content,
            filename=uploaded_file.name,
        )
    except StatementParseError as exc:
        import_file.status = ImportFile.Status.FAILED
        import_file.error_message = str(exc)
        import_file.save(
            update_fields=[
                "status",
                "error_message",
                "updated_at",
            ]
        )
        return import_file

    parsed = parsed_document.parsed

    import_file.ofx_version = str(
        parsed.version or ""
    )
    import_file.encoding = parsed.encoding
    import_file.source_format = (
        parsed_document.source_format
    )
    import_file.provider = (
        parsed_document.provider
    )
    import_file.save(
        update_fields=[
            "ofx_version",
            "encoding",
            "source_format",
            "provider",
            "updated_at",
        ]
    )

    for statement_index, parsed_statement in enumerate(
        parsed.statements,
        start=1,
    ):
        match = match_statement(parsed_statement)

        staged_statement = ImportStatement.objects.create(
            import_file=import_file,
            sequence=statement_index,
            bank_id=parsed_statement.bank_id,
            bank_name=parsed_statement.bank_name,
            branch_id=parsed_statement.branch_id,
            account_id=parsed_statement.account_id,
            account_type=parsed_statement.account_type,
            currency=parsed_statement.currency,
            period_start=ensure_optional_aware(
                parsed_statement.start
            ),
            period_end=ensure_optional_aware(
                parsed_statement.end
            ),
            ledger_balance=parsed_statement.ledger_balance,
            matched_bank=match.bank,
            matched_account=match.account,
            match_method=(
                ImportStatement.MatchMethod.AUTOMATIC
                if match.account
                else ImportStatement.MatchMethod.NONE
            ),
        )

        for item_index, parsed_item in enumerate(
            parsed_statement.transactions,
            start=1,
        ):
            _create_import_item(
                statement=staged_statement,
                sequence=item_index,
                parsed_item=parsed_item,
            )

    return import_file


def _create_import_item(
    *,
    statement: ImportStatement,
    sequence: int,
    parsed_item: ParsedTransaction,
) -> ImportItem:
    posted_at = ensure_aware(parsed_item.posted_at)

    direction = map_direction(parsed_item)
    transaction_type = map_transaction_type(parsed_item)

    signed_amount = parsed_item.amount
    amount = abs(signed_amount)

    raw_description = build_description(parsed_item)
    document = parsed_item.checknum.strip()
    reference = parsed_item.reference.strip()

    account = statement.matched_account

    fingerprint = build_fingerprint(
        account_id=account.pk if account else 0,
        posted_at=posted_at,
        signed_amount=signed_amount,
        transaction_type=transaction_type,
        description=raw_description,
        document=document,
        reference=reference,
    )

    if amount == Decimal("0.00"):
        classification = ImportItem.Classification.INVALID
        existing = None
        divergence_fields = ["amount"]
    else:
        (
            classification,
            existing,
            divergence_fields,
        ) = classify_values(
            account=account,
            fitid=parsed_item.fitid.strip(),
            posted_at=posted_at,
            amount=amount,
            direction=direction,
            transaction_type=transaction_type,
            raw_description=raw_description,
            document=document,
            reference=reference,
            fingerprint=fingerprint,
        )

    default_resolution = default_resolution_for(
        classification
    )

    return ImportItem.objects.create(
        statement=statement,
        sequence=sequence,
        fitid=parsed_item.fitid.strip(),
        posted_at=posted_at,
        posted_at_raw=parsed_item.posted_at_raw,
        posted_at_has_time=parsed_item.posted_at_has_time,
        signed_amount=signed_amount,
        amount=amount,
        direction=direction,
        transaction_type=transaction_type,
        ofx_transaction_type=parsed_item.transaction_type,
        raw_description=raw_description,
        document=document,
        reference=reference,
        fingerprint=fingerprint,
        raw_data=parsed_item.raw,
        classification=classification,
        resolution=default_resolution,
        existing_transaction=existing,
        divergence_fields=divergence_fields,
    )


@db_transaction.atomic
def reclassify_statement(statement: ImportStatement):
    for item in statement.items.select_related(
        "existing_transaction",
        "statement",
        "statement__matched_account",
    ):
        if item.is_excluded:
            continue

        reclassify_import_item(item)

