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
    ]

    operations = [
        migrations.CreateModel(
            name="LoginThrottleBucket",
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
                    "scope",
                    models.CharField(
                        choices=[
                            (
                                "USERNAME",
                                "Usuário",
                            ),
                            (
                                "IP",
                                "IP",
                            ),
                        ],
                        db_index=True,
                        max_length=12,
                        verbose_name="Escopo",
                    ),
                ),
                (
                    "key_hash",
                    models.CharField(
                        max_length=64,
                        unique=True,
                        verbose_name="Chave protegida",
                    ),
                ),
                (
                    "failures",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="Falhas",
                    ),
                ),
                (
                    "window_started_at",
                    models.DateTimeField(
                        verbose_name="Janela iniciada em",
                    ),
                ),
                (
                    "locked_until",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        null=True,
                        verbose_name="Bloqueado até",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="Atualizado em",
                    ),
                ),
            ],
            options={
                "verbose_name": (
                    "Controle de tentativas de login"
                ),
                "verbose_name_plural": (
                    "Controles de tentativas de login"
                ),
            },
        ),
        migrations.CreateModel(
            name="SecurityEvent",
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
                    "event_type",
                    models.CharField(
                        choices=[
                            (
                                "LOGIN_BLOCKED",
                                "Login bloqueado",
                            ),
                            (
                                "LOGIN_SUCCESS",
                                "Login realizado",
                            ),
                            (
                                "INTEGRATION_CREATED",
                                "Integração criada",
                            ),
                            (
                                "INTEGRATION_UPDATED",
                                "Integração atualizada",
                            ),
                            (
                                "INTEGRATION_TESTED",
                                "Integração testada",
                            ),
                            (
                                "REPORT_REQUESTED",
                                "Relatório solicitado",
                            ),
                            (
                                "REPORT_IMPORTED",
                                "Relatório importado",
                            ),
                        ],
                        db_index=True,
                        max_length=32,
                        verbose_name="Evento",
                    ),
                ),
                (
                    "success",
                    models.BooleanField(
                        db_index=True,
                        default=True,
                        verbose_name="Sucesso",
                    ),
                ),
                (
                    "ip_hash",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        max_length=64,
                        verbose_name="Hash do IP",
                    ),
                ),
                (
                    "detail",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        verbose_name="Detalhes",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        db_index=True,
                        verbose_name="Criado em",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=(
                            django.db.models.deletion.SET_NULL
                        ),
                        related_name="security_events",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuário",
                    ),
                ),
            ],
            options={
                "verbose_name": "Evento de segurança",
                "verbose_name_plural": "Eventos de segurança",
                "ordering": [
                    "-created_at",
                    "-id",
                ],
            },
        ),
    ]
