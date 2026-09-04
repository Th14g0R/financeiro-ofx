from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        (
            "finance",
            "0003_counterparty_and_fitid_dedup",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="transaction",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("MANUAL", "Manual"),
                    ("OFX", "OFX/QFX"),
                    ("PDF", "PDF"),
                    ("API", "API"),
                    ("IMPORT", "Importação"),
                ],
                db_index=True,
                default="MANUAL",
                max_length=16,
                verbose_name="Origem",
            ),
        ),
    ]
