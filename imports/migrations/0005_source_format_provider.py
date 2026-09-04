from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        (
            "imports",
            "0004_fitid_policy_and_datetime_precision",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="importfile",
            name="source_format",
            field=models.CharField(
                choices=[
                    ("OFX", "OFX/QFX"),
                    ("PDF", "PDF"),
                    ("API_CSV", "Relatório API/CSV"),
                    ("CSV", "CSV"),
                ],
                db_index=True,
                default="OFX",
                max_length=12,
                verbose_name="Formato de origem",
            ),
        ),
        migrations.AddField(
            model_name="importfile",
            name="provider",
            field=models.CharField(
                choices=[
                    ("GENERIC", "Genérico"),
                    ("MERCADO_PAGO", "Mercado Pago"),
                ],
                db_index=True,
                default="GENERIC",
                max_length=32,
                verbose_name="Provedor",
            ),
        ),
        migrations.AddField(
            model_name="importfile",
            name="source_reference",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Ex.: nome do relatório gerado por uma API."
                ),
                max_length=255,
                verbose_name="Referência externa",
            ),
        ),
    ]
