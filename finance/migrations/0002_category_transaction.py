from decimal import Decimal

from django.conf import settings
from django.db import migrations
from django.db import models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("finance", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Category",
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
                    "name",
                    models.CharField(
                        max_length=120,
                        unique=True,
                        verbose_name="Nome",
                    ),
                ),
                (
                    "category_type",
                    models.CharField(
                        choices=[
                            ("INCOME", "Entrada"),
                            ("EXPENSE", "Saída"),
                            ("BOTH", "Entrada e saída"),
                        ],
                        default="BOTH",
                        max_length=10,
                        verbose_name="Aplicação",
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
                "verbose_name": "Categoria",
                "verbose_name_plural": "Categorias",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="Transaction",
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
                    "posted_at",
                    models.DateTimeField(
                        db_index=True,
                        verbose_name="Data do movimento",
                    ),
                ),
                (
                    "competence_date",
                    models.DateField(
                        blank=True,
                        null=True,
                        verbose_name="Data de competência",
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=18,
                        validators=[
                            django.core.validators.MinValueValidator(
                                Decimal("0.01"),
                                "O valor deve ser maior que zero.",
                            )
                        ],
                        verbose_name="Valor",
                    ),
                ),
                (
                    "direction",
                    models.CharField(
                        choices=[
                            ("CREDIT", "Entrada"),
                            ("DEBIT", "Saída"),
                        ],
                        db_index=True,
                        max_length=6,
                        verbose_name="Natureza",
                    ),
                ),
                (
                    "transaction_type",
                    models.CharField(
                        choices=[
                            ("PIX", "PIX"),
                            ("TED", "TED"),
                            ("DOC", "DOC"),
                            ("TRANSFER", "Transferência"),
                            ("CARD_PURCHASE", "Compra no cartão"),
                            ("PAYMENT", "Pagamento"),
                            ("FEE", "Tarifa"),
                            ("INTEREST", "Juros"),
                            ("CASH_WITHDRAWAL", "Saque"),
                            ("CASH_DEPOSIT", "Depósito"),
                            ("REFUND", "Estorno"),
                            ("OTHER", "Outro"),
                        ],
                        default="OTHER",
                        max_length=24,
                        verbose_name="Tipo",
                    ),
                ),
                (
                    "source_type",
                    models.CharField(
                        choices=[
                            ("MANUAL", "Manual"),
                            ("OFX", "OFX"),
                            ("API", "API"),
                            ("IMPORT", "Importação"),
                        ],
                        db_index=True,
                        default="MANUAL",
                        max_length=10,
                        verbose_name="Origem",
                    ),
                ),
                (
                    "fitid",
                    models.CharField(
                        blank=True,
                        help_text=(
                            "Identificador da movimentação fornecido pelo OFX."
                        ),
                        max_length=255,
                        verbose_name="FITID",
                    ),
                ),
                (
                    "raw_description",
                    models.TextField(
                        verbose_name="Descrição original",
                    ),
                ),
                (
                    "normalized_description",
                    models.TextField(
                        blank=True,
                        verbose_name="Descrição normalizada",
                    ),
                ),
                (
                    "document",
                    models.CharField(
                        blank=True,
                        max_length=120,
                        verbose_name="Documento",
                    ),
                ),
                (
                    "reference",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        verbose_name="Referência",
                    ),
                ),
                (
                    "fingerprint",
                    models.CharField(
                        blank=True,
                        help_text=(
                            "Hash interno usado no controle de duplicidade."
                        ),
                        max_length=64,
                        verbose_name="Fingerprint",
                    ),
                ),
                (
                    "fingerprint_version",
                    models.PositiveSmallIntegerField(
                        default=1,
                        verbose_name="Versão do fingerprint",
                    ),
                ),
                (
                    "raw_data",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        verbose_name="Dados brutos",
                    ),
                ),
                (
                    "notes",
                    models.TextField(
                        blank=True,
                        verbose_name="Observações",
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
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transactions",
                        to="finance.account",
                        verbose_name="Conta",
                    ),
                ),
                (
                    "category",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="transactions",
                        to="finance.category",
                        verbose_name="Categoria",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_financial_transactions",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Criado por",
                    ),
                ),
            ],
            options={
                "verbose_name": "Movimentação",
                "verbose_name_plural": "Movimentações",
                "ordering": ["-posted_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="transaction",
            index=models.Index(
                fields=["account", "-posted_at"],
                name="fin_tx_acc_post_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="transaction",
            index=models.Index(
                fields=["direction", "-posted_at"],
                name="fin_tx_dir_post_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="transaction",
            index=models.Index(
                fields=["source_type", "-posted_at"],
                name="fin_tx_src_post_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="transaction",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount__gt", 0)),
                name="finance_transaction_amount_gt_zero",
            ),
        ),
        migrations.AddConstraint(
            model_name="transaction",
            constraint=models.CheckConstraint(
                condition=models.Q(("fingerprint_version__gte", 1)),
                name="finance_transaction_fingerprint_version_gte_1",
            ),
        ),
        migrations.AddConstraint(
            model_name="transaction",
            constraint=models.UniqueConstraint(
                condition=models.Q(("fitid", ""), _negated=True),
                fields=("account", "fitid"),
                name="finance_transaction_unique_account_fitid",
            ),
        ),
        migrations.AddConstraint(
            model_name="transaction",
            constraint=models.UniqueConstraint(
                condition=models.Q(("fingerprint", ""), _negated=True),
                fields=("account", "fingerprint"),
                name="finance_transaction_unique_account_fingerprint",
            ),
        ),
    ]
