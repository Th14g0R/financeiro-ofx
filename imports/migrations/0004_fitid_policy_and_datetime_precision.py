from django.db import migrations
from django.db import models


def reopen_false_fingerprint_duplicates(apps, schema_editor):
    """
    Corrige itens históricos classificados como duplicados pela regra antiga.

    Antes da Etapa 8, um fingerprint igual podia marcar como duplicadas duas
    transações que tinham FITIDs diferentes. Quando ambos os FITIDs existem e
    são diferentes, essa duplicidade não é válida.

    Só reabrimos itens não excluídos pelo usuário.
    """
    ImportItem = apps.get_model("imports", "ImportItem")
    ImportFile = apps.get_model("imports", "ImportFile")
    ImportBatch = apps.get_model("imports", "ImportBatch")

    affected_file_ids = set()
    affected_batch_ids = set()

    candidates = (
        ImportItem.objects
        .filter(
            classification="DUPLICATE",
            is_excluded=False,
            existing_transaction__isnull=False,
        )
        .exclude(fitid="")
        .select_related(
            "existing_transaction",
            "statement__import_file",
        )
    )

    for item in candidates.iterator():
        existing_fitid = (
            item.existing_transaction.fitid or ""
        ).strip()
        incoming_fitid = (item.fitid or "").strip()

        if (
            not existing_fitid
            or not incoming_fitid
            or existing_fitid == incoming_fitid
        ):
            continue

        item.classification = "NEW"
        item.resolution = "IMPORT"
        item.commit_status = "PENDING"
        item.existing_transaction_id = None
        item.imported_transaction_id = None
        item.divergence_fields = []
        item.commit_error_code = ""
        item.commit_error_message = ""
        item.commit_error_details = {}

        item.save(
            update_fields=[
                "classification",
                "resolution",
                "commit_status",
                "existing_transaction",
                "imported_transaction",
                "divergence_fields",
                "commit_error_code",
                "commit_error_message",
                "commit_error_details",
            ]
        )

        affected_file_ids.add(
            item.statement.import_file_id
        )
        affected_batch_ids.add(
            item.statement.import_file.batch_id
        )

    if affected_file_ids:
        ImportFile.objects.filter(
            pk__in=affected_file_ids
        ).update(
            status="PARTIAL"
        )

    if affected_batch_ids:
        ImportBatch.objects.filter(
            pk__in=affected_batch_ids
        ).update(
            status="PARTIAL",
            committed_at=None,
        )


def noop_reverse(apps, schema_editor):
    # Não é seguro recriar os falsos positivos da regra antiga.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0003_counterparty_and_fitid_dedup"),
        ("imports", "0003_importitem_error_and_exclusion"),
    ]

    operations = [
        migrations.AddField(
            model_name="importitem",
            name="posted_at_raw",
            field=models.CharField(
                blank=True,
                max_length=64,
                verbose_name="DTPOSTED original",
            ),
        ),
        migrations.AddField(
            model_name="importitem",
            name="posted_at_has_time",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "True também é usado para registros legados cuja precisão "
                    "original ainda não foi reprocessada."
                ),
                verbose_name="OFX informou horário",
            ),
        ),
        migrations.AlterField(
            model_name="importitem",
            name="classification",
            field=models.CharField(
                choices=[
                    ("NEW", "Novo"),
                    ("DUPLICATE", "Duplicado por FITID"),
                    (
                        "POSSIBLE_DUPLICATE",
                        "Possível duplicado sem FITID",
                    ),
                    ("DIVERGENT", "Divergente"),
                    (
                        "UNRESOLVED_ACCOUNT",
                        "Conta não relacionada",
                    ),
                    ("INVALID", "Inválido"),
                    ("COMMIT_ERROR", "Erro de gravação"),
                ],
                db_index=True,
                max_length=24,
                verbose_name="Classificação",
            ),
        ),
        migrations.AlterField(
            model_name="importitem",
            name="resolution",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pendente"),
                    ("IMPORT", "Importar"),
                    ("IMPORT_ANYWAY", "Gravar mesmo assim"),
                    ("KEEP_CURRENT", "Manter atual"),
                    ("UPDATE", "Atualizar com OFX"),
                    ("IGNORE", "Ignorar"),
                ],
                default="PENDING",
                max_length=16,
                verbose_name="Resolução",
            ),
        ),
        migrations.RunPython(
            reopen_false_fingerprint_duplicates,
            noop_reverse,
        ),
    ]
