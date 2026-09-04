from django.db import migrations
from django.db import models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="importbatch",
            name="reprocessed_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Reprocessado em",
            ),
        ),
        migrations.CreateModel(
            name="ImportEffect",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("CREATED", "Criou movimentação"),
                            ("UPDATED", "Atualizou movimentação"),
                        ],
                        max_length=8,
                        verbose_name="Ação",
                    ),
                ),
                (
                    "before_data",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        verbose_name="Antes",
                    ),
                ),
                (
                    "after_data",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        verbose_name="Depois",
                    ),
                ),
                (
                    "applied_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        db_index=True,
                        verbose_name="Aplicado em",
                    ),
                ),
                (
                    "reverted_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        null=True,
                        verbose_name="Desfeito em",
                    ),
                ),
                (
                    "import_item",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="effect",
                        to="imports.importitem",
                        verbose_name="Item da importação",
                    ),
                ),
                (
                    "transaction",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="import_effects",
                        to="finance.transaction",
                        verbose_name="Movimentação",
                    ),
                ),
            ],
            options={
                "verbose_name": "Efeito da importação",
                "verbose_name_plural": "Efeitos das importações",
                "ordering": ["-applied_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="importeffect",
            index=models.Index(
                fields=[
                    "transaction",
                    "reverted_at",
                    "-applied_at",
                ],
                name="imp_effect_tx_active_idx",
            ),
        ),
    ]
