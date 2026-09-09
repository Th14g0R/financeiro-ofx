from decimal import Decimal
import re
import unicodedata

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F
from django.db.models import Q


def _normalize_identity_value(value: str) -> str:
    decomposed = unicodedata.normalize(
        "NFKD",
        value or "",
    )
    ascii_text = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    ascii_text = re.sub(
        r"[^A-Za-z0-9]+",
        " ",
        ascii_text,
    )
    return " ".join(
        ascii_text.upper().split()
    )

class Bank(models.Model):
    name = models.CharField(
        "Nome",
        max_length=120,
        unique=True,
    )
    code = models.CharField(
        "Código COMPE",
        max_length=3,
        blank=True,
        help_text="Código bancário de 3 dígitos, quando aplicável.",
    )
    ofx_bank_id = models.CharField(
        "BANKID do OFX",
        max_length=32,
        blank=True,
        db_index=True,
        help_text="Identificador BANKID informado pelo arquivo OFX.",
    )
    is_active = models.BooleanField(
        "Ativo",
        default=True,
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
        ordering = ["name"]
        verbose_name = "Banco"
        verbose_name_plural = "Bancos"
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=~Q(code=""),
                name="finance_bank_unique_code_nonempty",
            ),
            models.UniqueConstraint(
                fields=["ofx_bank_id"],
                condition=~Q(ofx_bank_id=""),
                name="finance_bank_unique_ofx_id_nonempty",
            ),
        ]

    def clean(self):
        super().clean()

        self.name = " ".join(self.name.split())
        self.code = self.code.strip()
        self.ofx_bank_id = self.ofx_bank_id.strip()

        if self.code:
            if not self.code.isdigit():
                raise ValidationError(
                    {"code": "Informe somente números no código COMPE."}
                )

            self.code = self.code.zfill(3)

    def __str__(self):
        if self.code:
            return f"{self.code} - {self.name}"

        return self.name


class Account(models.Model):
    class AccountType(models.TextChoices):
        CHECKING = "CHECKING", "Conta corrente"
        SAVINGS = "SAVINGS", "Poupança"
        PAYMENT = "PAYMENT", "Conta de pagamento"
        INVESTMENT = "INVESTMENT", "Investimento"
        OTHER = "OTHER", "Outra"

    bank = models.ForeignKey(
        Bank,
        verbose_name="Banco",
        related_name="accounts",
        on_delete=models.PROTECT,
    )
    nickname = models.CharField(
        "Apelido",
        max_length=120,
        help_text="Ex.: Principal, Empresa, Reserva.",
    )
    branch = models.CharField(
        "Agência",
        max_length=20,
        blank=True,
    )
    number = models.CharField(
        "Conta",
        max_length=40,
    )
    digit = models.CharField(
        "Dígito",
        max_length=10,
        blank=True,
    )
    account_type = models.CharField(
        "Tipo",
        max_length=20,
        choices=AccountType.choices,
        default=AccountType.CHECKING,
    )
    currency = models.CharField(
        "Moeda",
        max_length=3,
        default="BRL",
    )
    ofx_account_id = models.CharField(
        "ACCTID do OFX",
        max_length=100,
        blank=True,
        db_index=True,
        help_text=(
            "Identificador ACCTID informado no OFX. "
            "Será usado para reconhecimento automático da conta."
        ),
    )
    holder_name = models.CharField(
        "Titular",
        max_length=200,
        blank=True,
        help_text="Nome do titular informado pela instituição/Open Finance, quando disponível.",
    )
    holder_tax_id = models.CharField(
        "CPF/CNPJ do titular",
        max_length=32,
        blank=True,
        help_text="Documento do titular informado pela instituição/Open Finance, quando disponível.",
    )
    is_own_account = models.BooleanField(
        "Esta conta é minha",
        default=True,
        db_index=True,
        help_text=(
            "Marque para contas do próprio titular. "
            "O sistema usa esta informação para separar transferências "
            "entre contas próprias de entradas/saídas externas."
        ),
    )
    is_active = models.BooleanField(
        "Ativa",
        default=True,
    )
    created_at = models.DateTimeField(
        "Criada em",
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        "Atualizada em",
        auto_now=True,
    )

    class Meta:
        ordering = ["bank__name", "nickname"]
        verbose_name = "Conta"
        verbose_name_plural = "Contas"
        constraints = [
            models.UniqueConstraint(
                fields=["bank", "branch", "number", "digit"],
                name="finance_account_unique_bank_branch_number_digit",
            ),
            models.UniqueConstraint(
                fields=["bank", "ofx_account_id"],
                condition=~Q(ofx_account_id=""),
                name="finance_account_unique_bank_ofx_id_nonempty",
            ),
        ]

    def clean(self):
        super().clean()

        self.nickname = " ".join(self.nickname.split())
        self.branch = self.branch.strip()
        self.number = self.number.strip()
        self.digit = self.digit.strip()
        self.currency = self.currency.strip().upper()
        self.ofx_account_id = self.ofx_account_id.strip()
        self.holder_name = " ".join(self.holder_name.split())
        self.holder_tax_id = self.holder_tax_id.strip()

        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValidationError(
                {"currency": "Informe uma moeda ISO de 3 letras, como BRL."}
            )

    @property
    def formatted_number(self):
        if self.digit:
            return f"{self.number}-{self.digit}"

        return self.number

    def __str__(self):
        return f"{self.nickname} | {self.bank.name} | {self.formatted_number}"


class Category(models.Model):
    class CategoryType(models.TextChoices):
        INCOME = "INCOME", "Entrada"
        EXPENSE = "EXPENSE", "Saída"
        BOTH = "BOTH", "Entrada e saída"

    name = models.CharField(
        "Nome",
        max_length=120,
        unique=True,
    )
    category_type = models.CharField(
        "Aplicação",
        max_length=10,
        choices=CategoryType.choices,
        default=CategoryType.BOTH,
    )
    is_active = models.BooleanField(
        "Ativa",
        default=True,
    )
    created_at = models.DateTimeField(
        "Criada em",
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        "Atualizada em",
        auto_now=True,
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Categoria"
        verbose_name_plural = "Categorias"

    def clean(self):
        super().clean()
        self.name = " ".join(self.name.split())

    def __str__(self):
        return self.name


class Counterparty(models.Model):
    class Kind(models.TextChoices):
        PERSON = "PERSON", "Pessoa"
        COMPANY = "COMPANY", "Empresa"
        UNKNOWN = "UNKNOWN", "Não definido"

    display_name = models.CharField(
        "Nome",
        max_length=200,
    )
    normalized_name = models.CharField(
        "Nome normalizado",
        max_length=200,
        db_index=True,
    )
    kind = models.CharField(
        "Tipo",
        max_length=10,
        choices=Kind.choices,
        default=Kind.UNKNOWN,
    )
    tax_id = models.CharField(
        "CPF/CNPJ",
        max_length=14,
        blank=True,
        db_index=True,
        help_text="Somente números, quando o identificador completo estiver disponível.",
    )
    is_active = models.BooleanField(
        "Ativa",
        default=True,
    )
    created_at = models.DateTimeField(
        "Criada em",
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        "Atualizada em",
        auto_now=True,
    )

    class Meta:
        ordering = ["display_name", "id"]
        verbose_name = "Contraparte"
        verbose_name_plural = "Contrapartes"
        indexes = [
            models.Index(
                fields=["normalized_name", "is_active"],
                name="fin_cp_name_active_idx",
            ),
        ]

    def clean(self):
        super().clean()
        self.display_name = " ".join(self.display_name.split())
        self.normalized_name = _normalize_identity_value(
            self.display_name
        )
        self.tax_id = "".join(
            char for char in self.tax_id
            if char.isdigit()
        )

        if self.tax_id and len(self.tax_id) not in {11, 14}:
            raise ValidationError(
                {"tax_id": "CPF/CNPJ completo deve possuir 11 ou 14 dígitos."}
            )

    def __str__(self):
        return self.display_name


class CounterpartyAlias(models.Model):
    class AliasType(models.TextChoices):
        NAME = "NAME", "Nome"
        PIX = "PIX", "PIX"
        TAX_ID = "TAX_ID", "CPF/CNPJ"
        BANK_ID = "BANK_ID", "Identificador bancário"
        BANK_TEXT = "BANK_TEXT", "Texto bancário"

    counterparty = models.ForeignKey(
        Counterparty,
        verbose_name="Contraparte",
        related_name="aliases",
        on_delete=models.CASCADE,
    )
    alias = models.CharField(
        "Alias",
        max_length=255,
    )
    normalized_alias = models.CharField(
        "Alias normalizado",
        max_length=255,
        db_index=True,
    )
    alias_type = models.CharField(
        "Tipo",
        max_length=12,
        choices=AliasType.choices,
        default=AliasType.NAME,
    )
    created_at = models.DateTimeField(
        "Criado em",
        auto_now_add=True,
    )

    class Meta:
        ordering = ["counterparty__display_name", "alias"]
        verbose_name = "Alias de contraparte"
        verbose_name_plural = "Aliases de contrapartes"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "counterparty",
                    "normalized_alias",
                    "alias_type",
                ],
                name="finance_counterparty_alias_unique",
            ),
        ]

    def clean(self):
        super().clean()
        self.alias = " ".join(self.alias.split())
        self.normalized_alias = _normalize_identity_value(
            self.alias
        )

    def __str__(self):
        return f"{self.counterparty}: {self.alias}"


class Transaction(models.Model):
    class Direction(models.TextChoices):
        CREDIT = "CREDIT", "Entrada"
        DEBIT = "DEBIT", "Saída"

    class TransactionType(models.TextChoices):
        PIX = "PIX", "PIX"
        TED = "TED", "TED"
        DOC = "DOC", "DOC"
        TRANSFER = "TRANSFER", "Transferência"
        CARD_PURCHASE = "CARD_PURCHASE", "Compra no cartão"
        PAYMENT = "PAYMENT", "Pagamento"
        FEE = "FEE", "Tarifa"
        INTEREST = "INTEREST", "Juros"
        CASH_WITHDRAWAL = "CASH_WITHDRAWAL", "Saque"
        CASH_DEPOSIT = "CASH_DEPOSIT", "Depósito"
        REFUND = "REFUND", "Estorno"
        OTHER = "OTHER", "Outro"

    class SourceType(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        OFX = "OFX", "OFX/QFX"
        PDF = "PDF", "PDF"
        API = "API", "API"
        IMPORT = "IMPORT", "Importação"

    account = models.ForeignKey(
        Account,
        verbose_name="Conta",
        related_name="transactions",
        on_delete=models.PROTECT,
    )
    posted_at = models.DateTimeField(
        "Data do movimento",
        db_index=True,
    )
    competence_date = models.DateField(
        "Data de competência",
        null=True,
        blank=True,
    )
    amount = models.DecimalField(
        "Valor",
        max_digits=18,
        decimal_places=2,
        validators=[
            MinValueValidator(
                Decimal("0.01"),
                "O valor deve ser maior que zero.",
            )
        ],
    )
    direction = models.CharField(
        "Natureza",
        max_length=6,
        choices=Direction.choices,
        db_index=True,
    )
    transaction_type = models.CharField(
        "Tipo",
        max_length=24,
        choices=TransactionType.choices,
        default=TransactionType.OTHER,
    )
    source_type = models.CharField(
        "Origem",
        max_length=16,
        choices=SourceType.choices,
        default=SourceType.MANUAL,
        db_index=True,
    )
    fitid = models.CharField(
        "FITID",
        max_length=255,
        blank=True,
        help_text="Identificador da movimentação fornecido pelo OFX.",
    )
    raw_description = models.TextField(
        "Descrição original",
    )
    normalized_description = models.TextField(
        "Descrição normalizada",
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
    category = models.ForeignKey(
        Category,
        verbose_name="Categoria",
        related_name="transactions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    counterparty = models.ForeignKey(
        Counterparty,
        verbose_name="Contraparte",
        related_name="transactions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    counterparty_raw_name = models.CharField(
        "Nome da contraparte no histórico",
        max_length=255,
        blank=True,
    )
    fingerprint = models.CharField(
        "Fingerprint",
        max_length=64,
        blank=True,
        help_text="Hash interno usado no controle de duplicidade.",
    )
    fingerprint_version = models.PositiveSmallIntegerField(
        "Versão do fingerprint",
        default=1,
    )
    raw_data = models.JSONField(
        "Dados brutos",
        default=dict,
        blank=True,
    )
    notes = models.TextField(
        "Observações",
        blank=True,
    )
    is_financially_ignored = models.BooleanField(
        "Ignorar nos totais financeiros",
        default=False,
        db_index=True,
        help_text=(
            "Mantém o lançamento para auditoria/proveniência, mas o exclui "
            "dos totais e gráficos financeiros após revisão de duplicidade."
        ),
    )
    ignored_reason = models.CharField(
        "Motivo da exclusão financeira",
        max_length=255,
        blank=True,
    )
    canonical_transaction = models.ForeignKey(
        "self",
        verbose_name="Movimentação canônica",
        related_name="merged_duplicates",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=(
            "Quando este lançamento foi descartado/mesclado como duplicado, "
            "aponta para a movimentação mantida como canônica."
        ),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Criado por",
        related_name="created_financial_transactions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(
        "Criada em",
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        "Atualizada em",
        auto_now=True,
    )

    class Meta:
        ordering = ["-posted_at", "-id"]
        verbose_name = "Movimentação"
        verbose_name_plural = "Movimentações"
        indexes = [
            models.Index(
                fields=["account", "-posted_at"],
                name="fin_tx_acc_post_idx",
            ),
            models.Index(
                fields=["direction", "-posted_at"],
                name="fin_tx_dir_post_idx",
            ),
            models.Index(
                fields=["source_type", "-posted_at"],
                name="fin_tx_src_post_idx",
            ),
            models.Index(
                fields=["account", "fingerprint"],
                name="fin_tx_acc_fp_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="finance_transaction_amount_gt_zero",
            ),
            models.CheckConstraint(
                condition=Q(fingerprint_version__gte=1),
                name="finance_transaction_fingerprint_version_gte_1",
            ),
            models.UniqueConstraint(
                fields=["account", "fitid"],
                condition=~Q(fitid=""),
                name="finance_transaction_unique_account_fitid",
            ),
        ]

    def clean(self):
        super().clean()

        self.fitid = self.fitid.strip()
        self.raw_description = self.raw_description.strip()
        self.normalized_description = self.normalized_description.strip()
        self.document = self.document.strip()
        self.reference = self.reference.strip()
        self.fingerprint = self.fingerprint.strip().lower()
        self.notes = self.notes.strip()

        if self.category:
            allowed_types = {
                Category.CategoryType.BOTH,
                (
                    Category.CategoryType.INCOME
                    if self.direction == self.Direction.CREDIT
                    else Category.CategoryType.EXPENSE
                ),
            }

            if self.category.category_type not in allowed_types:
                raise ValidationError(
                    {
                        "category": (
                            "A categoria escolhida não é compatível "
                            "com a natureza desta movimentação."
                        )
                    }
                )

        if self.fingerprint and len(self.fingerprint) != 64:
            raise ValidationError(
                {
                    "fingerprint": (
                        "O fingerprint deve possuir 64 caracteres "
                        "hexadecimais (SHA-256)."
                    )
                }
            )

        if self.fingerprint:
            try:
                int(self.fingerprint, 16)
            except ValueError as exc:
                raise ValidationError(
                    {
                        "fingerprint": (
                            "O fingerprint deve conter somente "
                            "caracteres hexadecimais."
                        )
                    }
                ) from exc

    @property
    def ofx_posted_at_raw(self):
        return (
            self.raw_data.get("_ofx_datetime", {})
            .get("dtposted", "")
        )

    @property
    def ofx_time_was_supplied(self):
        return bool(
            self.raw_data.get("_ofx_datetime", {})
            .get("has_time", True)
        )

    @property
    def signed_amount(self):
        if self.direction == self.Direction.CREDIT:
            return self.amount

        return -self.amount

    @property
    def description(self):
        return self.normalized_description or self.raw_description

    def __str__(self):
        return (
            f"{self.posted_at:%d/%m/%Y} | "
            f"{self.get_direction_display()} | "
            f"{self.amount:.2f} | "
            f"{self.account}"
        )


class TransactionDuplicateReview(models.Model):
    class Classification(models.TextChoices):
        EXACT = "EXACT", "Duplicidade muito provável"
        POSSIBLE = "POSSIBLE", "Possível duplicidade"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendente de revisão"
        KEEP_BOTH = "KEEP_BOTH", "Manter as duas"
        KEEP_FIRST = "KEEP_FIRST", "Manter primeira"
        KEEP_SECOND = "KEEP_SECOND", "Manter segunda"
        MERGED_FIRST = "MERGED_FIRST", "Mesclada na primeira"
        MERGED_SECOND = "MERGED_SECOND", "Mesclada na segunda"

    first_transaction = models.ForeignKey(
        Transaction,
        verbose_name="Primeira movimentação",
        related_name="duplicate_reviews_as_first",
        on_delete=models.CASCADE,
    )
    second_transaction = models.ForeignKey(
        Transaction,
        verbose_name="Segunda movimentação",
        related_name="duplicate_reviews_as_second",
        on_delete=models.CASCADE,
    )
    classification = models.CharField(
        "Classificação",
        max_length=12,
        choices=Classification.choices,
        db_index=True,
    )
    confidence = models.PositiveSmallIntegerField(
        "Confiança",
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    match_reasons = models.JSONField(
        "Evidências",
        default=list,
        blank=True,
    )
    status = models.CharField(
        "Situação",
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Revisado por",
        related_name="reviewed_transaction_duplicates",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(
        "Revisado em",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        ordering = ["status", "-confidence", "-created_at"]
        verbose_name = "Revisão de duplicidade"
        verbose_name_plural = "Revisões de duplicidade"
        constraints = [
            models.CheckConstraint(
                condition=Q(first_transaction_id__lt=F("second_transaction_id")),
                name="fin_dup_review_ordered_pair",
            ),
            models.UniqueConstraint(
                fields=["first_transaction", "second_transaction"],
                name="fin_dup_review_unique_pair",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "-confidence"],
                name="fin_dup_status_conf_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.first_transaction_id} x {self.second_transaction_id} "
            f"({self.confidence}%)"
        )


class InternalTransfer(models.Model):
    class Status(models.TextChoices):
        POSSIBLE = (
            "POSSIBLE",
            "Possível transferência interna",
        )
        CONFIRMED = (
            "CONFIRMED",
            "Transferência interna",
        )
        REJECTED = (
            "REJECTED",
            "Não é transferência interna",
        )

    class MatchMethod(models.TextChoices):
        AUTOMATIC = (
            "AUTOMATIC",
            "Automático",
        )
        MANUAL = (
            "MANUAL",
            "Manual",
        )

    debit_transaction = models.ForeignKey(
        Transaction,
        verbose_name="Saída",
        related_name="internal_transfer_debit_matches",
        on_delete=models.CASCADE,
    )
    credit_transaction = models.ForeignKey(
        Transaction,
        verbose_name="Entrada",
        related_name="internal_transfer_credit_matches",
        on_delete=models.CASCADE,
    )
    status = models.CharField(
        "Situação",
        max_length=12,
        choices=Status.choices,
        default=Status.POSSIBLE,
        db_index=True,
    )
    match_method = models.CharField(
        "Método",
        max_length=12,
        choices=MatchMethod.choices,
        default=MatchMethod.AUTOMATIC,
        db_index=True,
    )
    confidence = models.PositiveSmallIntegerField(
        "Confiança",
        default=0,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100),
        ],
        help_text="Pontuação heurística de 0 a 100.",
    )
    match_reasons = models.JSONField(
        "Evidências",
        default=list,
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Revisado por",
        related_name="reviewed_internal_transfers",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(
        "Revisado em",
        null=True,
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
        ordering = [
            "-status",
            "-confidence",
            "-created_at",
        ]
        verbose_name = "Transferência interna"
        verbose_name_plural = "Transferências internas"
        constraints = [
            models.CheckConstraint(
                condition=~Q(
                    debit_transaction=F(
                        "credit_transaction"
                    )
                ),
                name="fin_internal_transfer_distinct_legs",
            ),
            models.UniqueConstraint(
                fields=["debit_transaction"],
                condition=Q(
                    status__in=[
                        "POSSIBLE",
                        "CONFIRMED",
                    ]
                ),
                name="fin_internal_transfer_active_debit_unique",
            ),
            models.UniqueConstraint(
                fields=["credit_transaction"],
                condition=Q(
                    status__in=[
                        "POSSIBLE",
                        "CONFIRMED",
                    ]
                ),
                name="fin_internal_transfer_active_credit_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=[
                    "status",
                    "-created_at",
                ],
                name="fin_int_status_created_idx",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.debit_transaction_id
            and self.credit_transaction_id
        ):
            debit = self.debit_transaction
            credit = self.credit_transaction

            if (
                debit.direction
                != Transaction.Direction.DEBIT
            ):
                raise ValidationError(
                    {
                        "debit_transaction": (
                            "A perna de saída deve ser um débito."
                        )
                    }
                )

            if (
                credit.direction
                != Transaction.Direction.CREDIT
            ):
                raise ValidationError(
                    {
                        "credit_transaction": (
                            "A perna de entrada deve ser um crédito."
                        )
                    }
                )

            if debit.account_id == credit.account_id:
                raise ValidationError(
                    (
                        "Transferência interna exige duas contas "
                        "próprias diferentes."
                    )
                )

            if debit.amount != credit.amount:
                raise ValidationError(
                    (
                        "As duas pernas da transferência interna "
                        "devem possuir o mesmo valor."
                    )
                )

            if (
                not debit.account.is_own_account
                or not credit.account.is_own_account
            ):
                raise ValidationError(
                    (
                        "As duas contas precisam estar marcadas "
                        "como contas próprias."
                    )
                )

    @property
    def amount(self):
        return self.debit_transaction.amount

    @property
    def source_account(self):
        return self.debit_transaction.account

    @property
    def target_account(self):
        return self.credit_transaction.account

    def __str__(self):
        return (
            f"{self.source_account} → {self.target_account} | "
            f"{self.amount:.2f}"
        )

