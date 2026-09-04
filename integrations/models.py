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
