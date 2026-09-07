from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        (
            "imports",
            "0005_source_format_provider",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="importfile",
            name="provider",
            field=models.CharField(
                choices=[
                    ("GENERIC", "Genérico"),
                    ("MERCADO_PAGO", "Mercado Pago"),
                    ("ASTROPAY", "AstroPay"),
                ],
                db_index=True,
                default="GENERIC",
                max_length=32,
                verbose_name="Provedor",
            ),
        ),
    ]
