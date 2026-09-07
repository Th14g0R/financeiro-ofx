from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models

from finance.models import Account
from finance.models import Bank
from finance.models import Transaction


def import_file_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    safe_name = f"{uuid4().hex}{extension}"
    return f"imports/{instance.batch_id}/{safe_name}"


class ImportBatch(models.Model):
    class Status(models.TextChoices):
        ANALYZING = "ANALYZING", "Analisando"
        ANALYZED = "ANALYZED", "Analisado"
        PARTIAL = "PARTIAL", "Parcialmente gravado"
        COMMITTED = "COMMITTED", "Gravado"
        FAILED = "FAILED", "Falhou"

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Criado por",
        related_name="ofx_import_batches",
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        "Situação",
        max_length=16,
        choices=Status.choices,
        default=Status.ANALYZING,
        db_index=True,
    )
    created_at = models.DateTimeField(
        "Criado em",
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        "Atualizado em",
        auto_now=True,
    )
    committed_at = models.DateTimeField(
        "Gravado em",
        null=True,
        blank=True,
    )
    reprocessed_at = models.DateTimeField(
        "Reprocessado em",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Lote de importação"
        verbose_name_plural = "Lotes de importação"

    def __str__(self):
        return f"Importação #{self.pk} - {self.get_status_display()}"


class ImportFile(models.Model):
    class SourceFormat(models.TextChoices):
        OFX = "OFX", "OFX/QFX"
        PDF = "PDF", "PDF"
        API_CSV = "API_CSV", "Relatório API/CSV"
        CSV = "CSV", "CSV"

    class Provider(models.TextChoices):
        GENERIC = "GENERIC", "Genérico"
        MERCADO_PAGO = "MERCADO_PAGO", "Mercado Pago"
        ASTROPAY = "ASTROPAY", "AstroPay"

    class Status(models.TextChoices):
        ANALYZED = "ANALYZED", "Analisado"
        DUPLICATE_FILE = "DUPLICATE_FILE", "Arquivo já importado"
        PARTIAL = "PARTIAL", "Parcialmente gravado"
        IMPORTED = "IMPORTED", "Gravado"
        FAILED = "FAILED", "Falhou"

    batch = models.ForeignKey(
        ImportBatch,
        verbose_name="Lote",
        related_name="files",
        on_delete=models.CASCADE,
    )
    file = models.FileField(
        "Arquivo",
        upload_to=import_file_upload_to,
    )
    original_name = models.CharField(
        "Nome original",
        max_length=255,
    )
    file_hash = models.CharField(
        "SHA-256",
        max_length=64,
        db_index=True,
    )
    file_size = models.PositiveBigIntegerField(
        "Tamanho",
        default=0,
    )
    source_format = models.CharField(
        "Formato de origem",
        max_length=12,
        choices=SourceFormat.choices,
        default=SourceFormat.OFX,
        db_index=True,
    )
    provider = models.CharField(
        "Provedor",
        max_length=32,
        choices=Provider.choices,
        default=Provider.GENERIC,
        db_index=True,
    )
    source_reference = models.CharField(
        "Referência externa",
        max_length=255,
        blank=True,
        help_text=(
            "Ex.: nome do relatório gerado por uma API."
        ),
    )
    status = models.CharField(
        "Situação",
        max_length=20,
        choices=Status.choices,
        default=Status.ANALYZED,
        db_index=True,
    )
    duplicate_of = models.ForeignKey(
        "self",
        verbose_name="Duplicado de",
        related_name="duplicate_attempts",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    ofx_version = models.CharField(
        "Versão OFX",
        max_length=20,
        blank=True,
    )
    encoding = models.CharField(
        "Codificação",
        max_length=40,
        blank=True,
    )
    error_message = models.TextField(
        "Erro",
        blank=True,
    )
    created_at = models.DateTimeField(
        "Criado em",
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        "Atualizado em",
        auto_now=True,
    )

    class Meta:
        ordering = ["id"]
        verbose_name = "Arquivo importado"
        verbose_name_plural = "Arquivos importados"
        indexes = [
            models.Index(
                fields=["file_hash", "status"],
                name="imp_file_hash_status_idx",
            ),
        ]

    def __str__(self):
        return self.original_name


class ImportStatement(models.Model):
    class MatchMethod(models.TextChoices):
        AUTOMATIC = "AUTOMATIC", "Automático"
        MANUAL = "MANUAL", "Manual"
        NONE = "NONE", "Não relacionado"

    import_file = models.ForeignKey(
        ImportFile,
        verbose_name="Arquivo",
        related_name="statements",
        on_delete=models.CASCADE,
    )
    sequence = models.PositiveIntegerField(
        "Sequência",
    )
    bank_id = models.CharField(
        "BANKID",
        max_length=32,
        blank=True,
    )
    bank_name = models.CharField(
        "Banco informado",
        max_length=160,
        blank=True,
    )
    branch_id = models.CharField(
        "Agência",
        max_length=40,
        blank=True,
    )
    account_id = models.CharField(
        "ACCTID",
        max_length=120,
        blank=True,
    )
    account_type = models.CharField(
        "Tipo da conta no OFX",
        max_length=40,
        blank=True,
    )
    currency = models.CharField(
        "Moeda",
        max_length=3,
        blank=True,
    )
    period_start = models.DateTimeField(
        "Início",
        null=True,
        blank=True,
    )
    period_end = models.DateTimeField(
        "Fim",
        null=True,
        blank=True,
    )
    ledger_balance = models.DecimalField(
        "Saldo",
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    matched_bank = models.ForeignKey(
        Bank,
        verbose_name="Banco relacionado",
        related_name="import_statements",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    matched_account = models.ForeignKey(
        Account,
        verbose_name="Conta relacionada",
        related_name="import_statements",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    match_method = models.CharField(
        "Método de relação",
        max_length=12,
        choices=MatchMethod.choices,
        default=MatchMethod.NONE,
    )

    class Meta:
        ordering = ["import_file_id", "sequence"]
        verbose_name = "Extrato em staging"
        verbose_name_plural = "Extratos em staging"
        constraints = [
            models.UniqueConstraint(
                fields=["import_file", "sequence"],
                name="imports_statement_unique_sequence",
            ),
        ]

    def __str__(self):
        return (
            f"{self.import_file.original_name} / "
            f"{self.account_id or 'conta não identificada'}"
        )


class ImportItem(models.Model):
    class Classification(models.TextChoices):
        NEW = "NEW", "Novo"
        DUPLICATE = "DUPLICATE", "Duplicado por FITID"
        POSSIBLE_DUPLICATE = (
            "POSSIBLE_DUPLICATE",
            "Possível duplicado sem FITID",
        )
        DIVERGENT = "DIVERGENT", "Divergente"
        UNRESOLVED_ACCOUNT = (
            "UNRESOLVED_ACCOUNT",
            "Conta não relacionada",
        )
        INVALID = "INVALID", "Inválido"
        COMMIT_ERROR = "COMMIT_ERROR", "Erro de gravação"

    class Resolution(models.TextChoices):
        PENDING = "PENDING", "Pendente"
        IMPORT = "IMPORT", "Importar"
        IMPORT_ANYWAY = "IMPORT_ANYWAY", "Gravar mesmo assim"
        KEEP_CURRENT = "KEEP_CURRENT", "Manter atual"
        UPDATE = "UPDATE", "Atualizar com OFX"
        IGNORE = "IGNORE", "Ignorar"

    class CommitStatus(models.TextChoices):
        PENDING = "PENDING", "Pendente"
        CREATED = "CREATED", "Criado"
        UPDATED = "UPDATED", "Atualizado"
        SKIPPED = "SKIPPED", "Ignorado"

    statement = models.ForeignKey(
        ImportStatement,
        verbose_name="Extrato",
        related_name="items",
        on_delete=models.CASCADE,
    )
    sequence = models.PositiveIntegerField(
        "Sequência",
    )
    fitid = models.CharField(
        "FITID",
        max_length=255,
        blank=True,
    )
    posted_at = models.DateTimeField(
        "Data do movimento",
    )
    posted_at_raw = models.CharField(
        "DTPOSTED original",
        max_length=64,
        blank=True,
    )
    posted_at_has_time = models.BooleanField(
        "OFX informou horário",
        default=True,
        help_text=(
            "True também é usado para registros legados cuja precisão "
            "original ainda não foi reprocessada."
        ),
    )
    signed_amount = models.DecimalField(
        "Valor original",
        max_digits=18,
        decimal_places=2,
    )
    amount = models.DecimalField(
        "Valor absoluto",
        max_digits=18,
        decimal_places=2,
    )
    direction = models.CharField(
        "Natureza",
        max_length=6,
        choices=Transaction.Direction.choices,
    )
    transaction_type = models.CharField(
        "Tipo",
        max_length=24,
        choices=Transaction.TransactionType.choices,
    )
    ofx_transaction_type = models.CharField(
        "Tipo original OFX",
        max_length=40,
        blank=True,
    )
    raw_description = models.TextField(
        "Descrição original",
        blank=True,
    )
    document = models.CharField(
        "Documento",
        max_length=120,
        blank=True,
    )
    reference = models.CharField(
        "Referência",
        max_length=255,
        blank=True,
    )
    fingerprint = models.CharField(
        "Fingerprint",
        max_length=64,
        db_index=True,
    )
    raw_data = models.JSONField(
        "Dados brutos",
        default=dict,
        blank=True,
    )
    classification = models.CharField(
        "Classificação",
        max_length=24,
        choices=Classification.choices,
        db_index=True,
    )
    resolution = models.CharField(
        "Resolução",
        max_length=16,
        choices=Resolution.choices,
        default=Resolution.PENDING,
    )
    commit_status = models.CharField(
        "Gravação",
        max_length=12,
        choices=CommitStatus.choices,
        default=CommitStatus.PENDING,
        db_index=True,
    )
    existing_transaction = models.ForeignKey(
        Transaction,
        verbose_name="Movimentação existente",
        related_name="staging_matches",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    imported_transaction = models.ForeignKey(
        Transaction,
        verbose_name="Movimentação gravada",
        related_name="staging_imports",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    divergence_fields = models.JSONField(
        "Campos divergentes",
        default=list,
        blank=True,
    )
    commit_error_code = models.CharField(
        "Código do erro",
        max_length=40,
        blank=True,
    )
    commit_error_message = models.TextField(
        "Erro de gravação",
        blank=True,
    )
    commit_error_details = models.JSONField(
        "Detalhes do erro",
        default=dict,
        blank=True,
    )
    is_excluded = models.BooleanField(
        "Removido da importação",
        default=False,
        db_index=True,
    )
    excluded_at = models.DateTimeField(
        "Removido em",
        null=True,
        blank=True,
    )
    excluded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Removido por",
        related_name="excluded_import_items",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["statement_id", "sequence"]
        verbose_name = "Movimentação em staging"
        verbose_name_plural = "Movimentações em staging"
        constraints = [
            models.UniqueConstraint(
                fields=["statement", "sequence"],
                name="imports_item_unique_sequence",
            ),
        ]
        indexes = [
            models.Index(
                fields=["classification", "commit_status"],
                name="imp_item_class_commit_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.posted_at:%d/%m/%Y} "
            f"{self.amount:.2f} "
            f"{self.get_classification_display()}"
        )



class ImportEffect(models.Model):
    class Action(models.TextChoices):
        CREATED = "CREATED", "Criou movimentação"
        UPDATED = "UPDATED", "Atualizou movimentação"

    import_item = models.OneToOneField(
        ImportItem,
        verbose_name="Item da importação",
        related_name="effect",
        on_delete=models.CASCADE,
    )
    transaction = models.ForeignKey(
        Transaction,
        verbose_name="Movimentação",
        related_name="import_effects",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    action = models.CharField(
        "Ação",
        max_length=8,
        choices=Action.choices,
    )
    before_data = models.JSONField(
        "Antes",
        default=dict,
        blank=True,
    )
    after_data = models.JSONField(
        "Depois",
        default=dict,
        blank=True,
    )
    applied_at = models.DateTimeField(
        "Aplicado em",
        auto_now_add=True,
        db_index=True,
    )
    reverted_at = models.DateTimeField(
        "Desfeito em",
        null=True,
        blank=True,
        db_index=True,
    )

    class Meta:
        ordering = ["-applied_at", "-id"]
        verbose_name = "Efeito da importação"
        verbose_name_plural = "Efeitos das importações"
        indexes = [
            models.Index(
                fields=["transaction", "reverted_at", "-applied_at"],
                name="imp_effect_tx_active_idx",
            ),
        ]

    @property
    def is_active(self):
        return self.reverted_at is None

    def __str__(self):
        return (
            f"{self.get_action_display()} - "
            f"item #{self.import_item_id}"
        )
