from django.db import migrations
from django.db import models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0002_category_transaction"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="transaction",
            name="finance_transaction_unique_account_fingerprint",
        ),
        migrations.AddIndex(
            model_name="transaction",
            index=models.Index(
                fields=["account", "fingerprint"],
                name="fin_tx_acc_fp_idx",
            ),
        ),
        migrations.CreateModel(
            name="Counterparty",
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
                    "display_name",
                    models.CharField(
                        max_length=200,
                        verbose_name="Nome",
                    ),
                ),
                (
                    "normalized_name",
                    models.CharField(
                        db_index=True,
                        max_length=200,
                        verbose_name="Nome normalizado",
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("PERSON", "Pessoa"),
                            ("COMPANY", "Empresa"),
                            ("UNKNOWN", "Não definido"),
                        ],
                        default="UNKNOWN",
                        max_length=10,
                        verbose_name="Tipo",
                    ),
                ),
                (
                    "tax_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        help_text=(
                            "Somente números, quando o identificador completo "
                            "estiver disponível."
                        ),
                        max_length=14,
                        verbose_name="CPF/CNPJ",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        verbose_name="Ativa",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Criada em",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="Atualizada em",
                    ),
                ),
            ],
            options={
                "verbose_name": "Contraparte",
                "verbose_name_plural": "Contrapartes",
                "ordering": ["display_name", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="counterparty",
            index=models.Index(
                fields=["normalized_name", "is_active"],
                name="fin_cp_name_active_idx",
            ),
        ),
        migrations.CreateModel(
            name="CounterpartyAlias",
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
                    "alias",
                    models.CharField(
                        max_length=255,
                        verbose_name="Alias",
                    ),
                ),
                (
                    "normalized_alias",
                    models.CharField(
                        db_index=True,
                        max_length=255,
                        verbose_name="Alias normalizado",
                    ),
                ),
                (
                    "alias_type",
                    models.CharField(
                        choices=[
                            ("NAME", "Nome"),
                            ("PIX", "PIX"),
                            ("TAX_ID", "CPF/CNPJ"),
                            ("BANK_TEXT", "Texto bancário"),
                        ],
                        default="NAME",
                        max_length=12,
                        verbose_name="Tipo",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Criado em",
                    ),
                ),
                (
                    "counterparty",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="aliases",
                        to="finance.counterparty",
                        verbose_name="Contraparte",
                    ),
                ),
            ],
            options={
                "verbose_name": "Alias de contraparte",
                "verbose_name_plural": "Aliases de contrapartes",
                "ordering": ["counterparty__display_name", "alias"],
            },
        ),
        migrations.AddConstraint(
            model_name="counterpartyalias",
            constraint=models.UniqueConstraint(
                fields=(
                    "counterparty",
                    "normalized_alias",
                    "alias_type",
                ),
                name="finance_counterparty_alias_unique",
            ),
        ),
        migrations.AddField(
            model_name="transaction",
            name="counterparty",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="transactions",
                to="finance.counterparty",
                verbose_name="Contraparte",
            ),
        ),
        migrations.AddField(
            model_name="transaction",
            name="counterparty_raw_name",
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name="Nome da contraparte no histórico",
            ),
        ),
    ]
