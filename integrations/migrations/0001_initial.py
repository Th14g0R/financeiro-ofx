from django.conf import settings
from django.db import migrations
from django.db import models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(
            settings.AUTH_USER_MODEL
        ),
        (
            "finance",
            "0004_transaction_source_types",
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="BankIntegration",
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
                        verbose_name="Nome",
                    ),
                ),
                (
                    "provider",
                    models.CharField(
                        choices=[
                            (
                                "MERCADO_PAGO",
                                "Mercado Pago",
                            ),
                        ],
                        db_index=True,
                        default="MERCADO_PAGO",
                        max_length=32,
                        verbose_name="Provedor",
                    ),
                ),
                (
                    "auth_mode",
                    models.CharField(
                        choices=[
                            (
                                "ACCESS_TOKEN",
                                "Access Token",
                            ),
                            (
                                "CLIENT_CREDENTIALS",
                                "Client ID + Client Secret",
                            ),
                        ],
                        default="CLIENT_CREDENTIALS",
                        max_length=24,
                        verbose_name="Autenticação",
                    ),
                ),
                (
                    "client_id",
                    models.CharField(
                        blank=True,
                        max_length=180,
                        verbose_name="Client ID",
                    ),
                ),
                (
                    "client_secret_encrypted",
                    models.TextField(
                        blank=True,
                        verbose_name=(
                            "Client Secret criptografado"
                        ),
                    ),
                ),
                (
                    "access_token_encrypted",
                    models.TextField(
                        blank=True,
                        verbose_name=(
                            "Access Token criptografado"
                        ),
                    ),
                ),
                (
                    "access_token_expires_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name=(
                            "Access Token expira em"
                        ),
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("NEW", "Não testada"),
                            ("OK", "Conectada"),
                            ("ERROR", "Erro"),
                        ],
                        db_index=True,
                        default="NEW",
                        max_length=12,
                        verbose_name="Situação",
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
                    "last_sync_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name=(
                            "Última sincronização"
                        ),
                    ),
                ),
                (
                    "last_error",
                    models.TextField(
                        blank=True,
                        verbose_name="Último erro",
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
                        on_delete=(
                            django.db.models.deletion.PROTECT
                        ),
                        related_name=(
                            "bank_integrations"
                        ),
                        to="finance.account",
                        verbose_name="Conta local",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=(
                            django.db.models.deletion.SET_NULL
                        ),
                        related_name=(
                            "created_bank_integrations"
                        ),
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Criada por",
                    ),
                ),
            ],
            options={
                "verbose_name": (
                    "Integração bancária"
                ),
                "verbose_name_plural": (
                    "Integrações bancárias"
                ),
                "ordering": ["name", "id"],
            },
        ),
    ]
