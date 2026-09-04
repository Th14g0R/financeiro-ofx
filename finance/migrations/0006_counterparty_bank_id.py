from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        (
            "finance",
            "0005_internal_transfers",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="counterpartyalias",
            name="alias_type",
            field=models.CharField(
                choices=[
                    ("NAME", "Nome"),
                    ("PIX", "PIX"),
                    ("TAX_ID", "CPF/CNPJ"),
                    (
                        "BANK_ID",
                        "Identificador bancário",
                    ),
                    (
                        "BANK_TEXT",
                        "Texto bancário",
                    ),
                ],
                default="NAME",
                max_length=12,
                verbose_name="Tipo",
            ),
        ),
    ]
