from __future__ import annotations

from django.conf import settings
from django.db import models

from finance.models import Account

from .crypto import decrypt_secret
from .crypto import encrypt_secret


class BankIntegration(models.Model):
    class Provider(models.TextChoices):
        MERCADO_PAGO = (
            "MERCADO_PAGO",
            "Mercado Pago",
        )

    class AuthMode(models.TextChoices):
        ACCESS_TOKEN = (
            "ACCESS_TOKEN",
            "Access Token",
        )
        CLIENT_CREDENTIALS = (
            "CLIENT_CREDENTIALS",
            "Client ID + Client Secret",
        )

    class Status(models.TextChoices):
        NEW = "NEW", "Não testada"
        OK = "OK", "Conectada"
        ERROR = "ERROR", "Erro"

    name = models.CharField(
        "Nome",
        max_length=120,
    )
    provider = models.CharField(
        "Provedor",
        max_length=32,
        choices=Provider.choices,
        default=Provider.MERCADO_PAGO,
        db_index=True,
    )
    account = models.ForeignKey(
        Account,
        verbose_name="Conta local",
        related_name="bank_integrations",
        on_delete=models.PROTECT,
    )
    auth_mode = models.CharField(
        "Autenticação",
        max_length=24,
        choices=AuthMode.choices,
        default=AuthMode.CLIENT_CREDENTIALS,
    )
    client_id = models.CharField(
        "Client ID",
        max_length=180,
        blank=True,
    )
    client_secret_encrypted = models.TextField(
        "Client Secret criptografado",
        blank=True,
    )
    access_token_encrypted = models.TextField(
        "Access Token criptografado",
        blank=True,
    )
    access_token_expires_at = models.DateTimeField(
        "Access Token expira em",
        null=True,
        blank=True,
    )
    status = models.CharField(
        "Situação",
        max_length=12,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )
    is_active = models.BooleanField(
        "Ativa",
        default=True,
    )
    last_sync_at = models.DateTimeField(
        "Última sincronização",
        null=True,
        blank=True,
    )
    last_error = models.TextField(
        "Último erro",
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Criada por",
        related_name="created_bank_integrations",
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
        ordering = ["name", "id"]
        verbose_name = "Integração bancária"
        verbose_name_plural = "Integrações bancárias"

    def set_client_secret(self, value: str):
        self.client_secret_encrypted = encrypt_secret(
            value
        )

    def get_client_secret(self) -> str:
        return decrypt_secret(
            self.client_secret_encrypted
        )

    def set_access_token(self, value: str):
        self.access_token_encrypted = encrypt_secret(
            value
        )

    def get_access_token(self) -> str:
        return decrypt_secret(
            self.access_token_encrypted
        )

    def __str__(self):
        return (
            f"{self.name} - "
            f"{self.get_provider_display()}"
        )



class PluggyConfiguration(models.Model):
    class Status(models.TextChoices):
        NEW = "NEW", "Não testada"
        OK = "OK", "Conectada"
        ERROR = "ERROR", "Erro"

    name = models.CharField(
        "Nome",
        max_length=120,
        default="Pluggy / Open Finance",
        unique=True,
    )
    client_id = models.CharField(
        "Client ID",
        max_length=180,
    )
    client_secret_encrypted = models.TextField(
        "Client Secret criptografado",
    )
    api_key_encrypted = models.TextField(
        "API Key temporária criptografada",
        blank=True,
    )
    api_key_expires_at = models.DateTimeField(
        "API Key expira em",
        null=True,
        blank=True,
    )
    status = models.CharField(
        "Situação",
        max_length=12,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )
    is_active = models.BooleanField(
        "Ativa",
        default=True,
    )
    last_error = models.TextField(
        "Último erro",
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Criada por",
        related_name="created_pluggy_configurations",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField("Criada em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizada em", auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "Configuração Pluggy"
        verbose_name_plural = "Configurações Pluggy"

    def set_client_secret(self, value: str):
        self.client_secret_encrypted = encrypt_secret(value)

    def get_client_secret(self) -> str:
        return decrypt_secret(self.client_secret_encrypted)

    def set_api_key(self, value: str):
        self.api_key_encrypted = encrypt_secret(value)

    def get_api_key(self) -> str:
        return decrypt_secret(self.api_key_encrypted)

    def clear_api_key(self):
        self.api_key_encrypted = ""
        self.api_key_expires_at = None

    def __str__(self):
        return self.name


class PluggyItem(models.Model):
    configuration = models.ForeignKey(
        PluggyConfiguration,
        verbose_name="Configuração",
        related_name="items",
        on_delete=models.PROTECT,
    )
    item_id = models.CharField(
        "Item ID",
        max_length=64,
        unique=True,
    )
    connector_id = models.PositiveIntegerField(
        "Connector ID",
        null=True,
        blank=True,
        db_index=True,
    )
    connector_name = models.CharField(
        "Instituição",
        max_length=180,
        blank=True,
    )
    client_user_id = models.CharField(
        "Referência do usuário",
        max_length=120,
        blank=True,
    )
    status = models.CharField(
        "Situação Pluggy",
        max_length=40,
        blank=True,
        db_index=True,
    )
    execution_status = models.CharField(
        "Execução Pluggy",
        max_length=60,
        blank=True,
    )
    status_detail = models.JSONField(
        "Detalhes de situação",
        default=dict,
        blank=True,
    )
    last_updated_at = models.DateTimeField(
        "Última atualização na Pluggy",
        null=True,
        blank=True,
    )
    last_sync_at = models.DateTimeField(
        "Última cópia para o Financeiro",
        null=True,
        blank=True,
    )
    last_error = models.TextField("Último erro", blank=True)
    is_active = models.BooleanField("Ativo", default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Conectado por",
        related_name="created_pluggy_items",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        ordering = ["connector_name", "item_id"]
        verbose_name = "Conexão Pluggy"
        verbose_name_plural = "Conexões Pluggy"

    def __str__(self):
        return self.connector_name or self.item_id


class PluggyAccount(models.Model):
    item = models.ForeignKey(
        PluggyItem,
        verbose_name="Conexão Pluggy",
        related_name="accounts",
        on_delete=models.CASCADE,
    )
    pluggy_account_id = models.CharField(
        "Account ID Pluggy",
        max_length=64,
        unique=True,
    )
    local_account = models.ForeignKey(
        Account,
        verbose_name="Conta local",
        related_name="pluggy_accounts",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    remote_type = models.CharField(
        "Tipo Pluggy",
        max_length=20,
        blank=True,
        db_index=True,
    )
    subtype = models.CharField("Subtipo Pluggy", max_length=60, blank=True)
    name = models.CharField("Nome da conta", max_length=180, blank=True)
    masked_number = models.CharField(
        "Número apresentado",
        max_length=120,
        blank=True,
    )
    currency = models.CharField("Moeda", max_length=3, default="BRL")
    balance = models.DecimalField(
        "Saldo informado",
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    bank_data = models.JSONField(
        "Dados bancários normalizados",
        default=dict,
        blank=True,
    )
    is_active = models.BooleanField("Ativa", default=True, db_index=True)
    last_seen_at = models.DateTimeField(
        "Vista pela última vez",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField("Criada em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizada em", auto_now=True)

    class Meta:
        ordering = ["item__connector_name", "name", "pluggy_account_id"]
        verbose_name = "Conta Pluggy"
        verbose_name_plural = "Contas Pluggy"
        indexes = [
            models.Index(
                fields=["item", "remote_type", "is_active"],
                name="int_plug_acc_item_type_idx",
            ),
        ]

    def __str__(self):
        label = self.name or self.masked_number or self.pluggy_account_id
        return f"{self.item} · {label}"


class PluggyTransactionLink(models.Model):
    pluggy_account = models.ForeignKey(
        PluggyAccount,
        verbose_name="Conta Pluggy",
        related_name="transaction_links",
        on_delete=models.CASCADE,
    )
    remote_transaction_id = models.CharField(
        "Transaction ID Pluggy",
        max_length=64,
    )
    provider_id = models.CharField(
        "Provider ID",
        max_length=255,
        blank=True,
        db_index=True,
    )
    transaction = models.ForeignKey(
        "finance.Transaction",
        verbose_name="Movimentação local",
        related_name="pluggy_links",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    remote_hash = models.CharField("Hash remoto", max_length=64, blank=True)
    has_conflict = models.BooleanField(
        "Divergência detectada",
        default=False,
        db_index=True,
    )
    conflict_fields = models.JSONField(
        "Campos divergentes",
        default=list,
        blank=True,
    )
    last_seen_at = models.DateTimeField(
        "Vista pela última vez",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField("Criada em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizada em", auto_now=True)

    class Meta:
        ordering = ["-last_seen_at", "-id"]
        verbose_name = "Vínculo de transação Pluggy"
        verbose_name_plural = "Vínculos de transações Pluggy"
        constraints = [
            models.UniqueConstraint(
                fields=["pluggy_account", "remote_transaction_id"],
                name="int_plug_tx_remote_unique",
            ),
            models.UniqueConstraint(
                fields=["pluggy_account", "provider_id"],
                condition=~models.Q(provider_id=""),
                name="int_plug_tx_provider_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pluggy_account", "has_conflict"],
                name="int_plug_tx_conflict_idx",
            ),
        ]

    def __str__(self):
        return self.remote_transaction_id
