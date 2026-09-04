from django.conf import settings
from django.db import migrations
from django.db import models
import django.db.models.deletion
import imports.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("finance", "0002_category_transaction"),
    ]

    operations = [
        migrations.CreateModel(
            name="ImportBatch",
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
                    "status",
                    models.CharField(
                        choices=[
                            ("ANALYZING", "Analisando"),
                            ("ANALYZED", "Analisado"),
                            ("PARTIAL", "Parcialmente gravado"),
                            ("COMMITTED", "Gravado"),
                            ("FAILED", "Falhou"),
                        ],
                        db_index=True,
                        default="ANALYZING",
                        max_length=16,
                        verbose_name="Situação",
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
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="Atualizado em",
                    ),
                ),
                (
                    "committed_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Gravado em",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ofx_import_batches",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Criado por",
                    ),
                ),
            ],
            options={
                "verbose_name": "Lote de importação",
                "verbose_name_plural": "Lotes de importação",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="ImportFile",
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
                    "file",
                    models.FileField(
                        upload_to=imports.models.import_file_upload_to,
                        verbose_name="Arquivo",
                    ),
                ),
                (
                    "original_name",
                    models.CharField(
                        max_length=255,
                        verbose_name="Nome original",
                    ),
                ),
                (
                    "file_hash",
                    models.CharField(
                        db_index=True,
                        max_length=64,
                        verbose_name="SHA-256",
                    ),
                ),
                (
                    "file_size",
                    models.PositiveBigIntegerField(
                        default=0,
                        verbose_name="Tamanho",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ANALYZED", "Analisado"),
                            ("DUPLICATE_FILE", "Arquivo já importado"),
                            ("PARTIAL", "Parcialmente gravado"),
                            ("IMPORTED", "Gravado"),
                            ("FAILED", "Falhou"),
                        ],
                        db_index=True,
                        default="ANALYZED",
                        max_length=20,
                        verbose_name="Situação",
                    ),
                ),
                (
                    "ofx_version",
                    models.CharField(
                        blank=True,
                        max_length=20,
                        verbose_name="Versão OFX",
                    ),
                ),
                (
                    "encoding",
                    models.CharField(
                        blank=True,
                        max_length=40,
                        verbose_name="Codificação",
                    ),
                ),
                (
                    "error_message",
                    models.TextField(
                        blank=True,
                        verbose_name="Erro",
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
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="Atualizado em",
                    ),
                ),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="files",
                        to="imports.importbatch",
                        verbose_name="Lote",
                    ),
                ),
                (
                    "duplicate_of",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="duplicate_attempts",
                        to="imports.importfile",
                        verbose_name="Duplicado de",
                    ),
                ),
            ],
            options={
                "verbose_name": "Arquivo importado",
                "verbose_name_plural": "Arquivos importados",
                "ordering": ["id"],
            },
        ),
        migrations.CreateModel(
            name="ImportStatement",
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
                    "sequence",
                    models.PositiveIntegerField(
                        verbose_name="Sequência",
                    ),
                ),
                (
                    "bank_id",
                    models.CharField(
                        blank=True,
                        max_length=32,
                        verbose_name="BANKID",
                    ),
                ),
                (
                    "bank_name",
                    models.CharField(
                        blank=True,
                        max_length=160,
                        verbose_name="Banco informado",
                    ),
                ),
                (
                    "branch_id",
                    models.CharField(
                        blank=True,
                        max_length=40,
                        verbose_name="Agência",
                    ),
                ),
                (
                    "account_id",
                    models.CharField(
                        blank=True,
                        max_length=120,
                        verbose_name="ACCTID",
                    ),
                ),
                (
                    "account_type",
                    models.CharField(
                        blank=True,
                        max_length=40,
                        verbose_name="Tipo da conta no OFX",
                    ),
                ),
                (
                    "currency",
                    models.CharField(
                        blank=True,
                        max_length=3,
                        verbose_name="Moeda",
                    ),
                ),
                (
                    "period_start",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Início",
                    ),
                ),
                (
                    "period_end",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Fim",
                    ),
                ),
                (
                    "ledger_balance",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=18,
                        null=True,
                        verbose_name="Saldo",
                    ),
                ),
                (
                    "match_method",
                    models.CharField(
                        choices=[
                            ("AUTOMATIC", "Automático"),
                            ("MANUAL", "Manual"),
                            ("NONE", "Não relacionado"),
                        ],
                        default="NONE",
                        max_length=12,
                        verbose_name="Método de relação",
                    ),
                ),
                (
                    "import_file",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="statements",
                        to="imports.importfile",
                        verbose_name="Arquivo",
                    ),
                ),
                (
                    "matched_account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="import_statements",
                        to="finance.account",
                        verbose_name="Conta relacionada",
                    ),
                ),
                (
                    "matched_bank",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="import_statements",
                        to="finance.bank",
                        verbose_name="Banco relacionado",
                    ),
                ),
            ],
            options={
                "verbose_name": "Extrato em staging",
                "verbose_name_plural": "Extratos em staging",
                "ordering": ["import_file_id", "sequence"],
            },
        ),
        migrations.CreateModel(
            name="ImportItem",
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
                    "sequence",
                    models.PositiveIntegerField(
                        verbose_name="Sequência",
                    ),
                ),
                (
                    "fitid",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        verbose_name="FITID",
                    ),
                ),
                (
                    "posted_at",
                    models.DateTimeField(
                        verbose_name="Data do movimento",
                    ),
                ),
                (
                    "signed_amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=18,
                        verbose_name="Valor original",
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=18,
                        verbose_name="Valor absoluto",
                    ),
                ),
                (
                    "direction",
                    models.CharField(
                        choices=[
                            ("CREDIT", "Entrada"),
                            ("DEBIT", "Saída"),
                        ],
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
                        max_length=24,
                        verbose_name="Tipo",
                    ),
                ),
                (
                    "ofx_transaction_type",
                    models.CharField(
                        blank=True,
                        max_length=40,
                        verbose_name="Tipo original OFX",
                    ),
                ),
                (
                    "raw_description",
                    models.TextField(
                        blank=True,
                        verbose_name="Descrição original",
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
                        db_index=True,
                        max_length=64,
                        verbose_name="Fingerprint",
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
                    "classification",
                    models.CharField(
                        choices=[
                            ("NEW", "Novo"),
                            ("DUPLICATE", "Duplicado"),
                            ("DIVERGENT", "Divergente"),
                            (
                                "UNRESOLVED_ACCOUNT",
                                "Conta não relacionada",
                            ),
                            ("INVALID", "Inválido"),
                        ],
                        db_index=True,
                        max_length=24,
                        verbose_name="Classificação",
                    ),
                ),
                (
                    "resolution",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pendente"),
                            ("IMPORT", "Importar"),
                            ("KEEP_CURRENT", "Manter atual"),
                            ("UPDATE", "Atualizar com OFX"),
                            ("IGNORE", "Ignorar"),
                        ],
                        default="PENDING",
                        max_length=16,
                        verbose_name="Resolução",
                    ),
                ),
                (
                    "commit_status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pendente"),
                            ("CREATED", "Criado"),
                            ("UPDATED", "Atualizado"),
                            ("SKIPPED", "Ignorado"),
                        ],
                        db_index=True,
                        default="PENDING",
                        max_length=12,
                        verbose_name="Gravação",
                    ),
                ),
                (
                    "divergence_fields",
                    models.JSONField(
                        blank=True,
                        default=list,
                        verbose_name="Campos divergentes",
                    ),
                ),
                (
                    "existing_transaction",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="staging_matches",
                        to="finance.transaction",
                        verbose_name="Movimentação existente",
                    ),
                ),
                (
                    "imported_transaction",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="staging_imports",
                        to="finance.transaction",
                        verbose_name="Movimentação gravada",
                    ),
                ),
                (
                    "statement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="imports.importstatement",
                        verbose_name="Extrato",
                    ),
                ),
            ],
            options={
                "verbose_name": "Movimentação em staging",
                "verbose_name_plural": "Movimentações em staging",
                "ordering": ["statement_id", "sequence"],
            },
        ),
        migrations.AddConstraint(
            model_name="importstatement",
            constraint=models.UniqueConstraint(
                fields=("import_file", "sequence"),
                name="imports_statement_unique_sequence",
            ),
        ),
        migrations.AddConstraint(
            model_name="importitem",
            constraint=models.UniqueConstraint(
                fields=("statement", "sequence"),
                name="imports_item_unique_sequence",
            ),
        ),
        migrations.AddIndex(
            model_name="importfile",
            index=models.Index(
                fields=["file_hash", "status"],
                name="imp_file_hash_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="importitem",
            index=models.Index(
                fields=["classification", "commit_status"],
                name="imp_item_class_commit_idx",
            ),
        ),
    ]
