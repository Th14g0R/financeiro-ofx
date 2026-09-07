from __future__ import annotations

from django.conf import settings
from django.db import models


class LoginThrottleBucket(models.Model):
    class Scope(models.TextChoices):
        USERNAME = "USERNAME", "Usuário"
        IP = "IP", "IP"

    scope = models.CharField(
        "Escopo",
        max_length=12,
        choices=Scope.choices,
        db_index=True,
    )
    key_hash = models.CharField(
        "Chave protegida",
        max_length=64,
        unique=True,
    )
    failures = models.PositiveIntegerField(
        "Falhas",
        default=0,
    )
    window_started_at = models.DateTimeField(
        "Janela iniciada em",
    )
    locked_until = models.DateTimeField(
        "Bloqueado até",
        null=True,
        blank=True,
        db_index=True,
    )
    updated_at = models.DateTimeField(
        "Atualizado em",
        auto_now=True,
    )

    class Meta:
        verbose_name = "Controle de tentativas de login"
        verbose_name_plural = "Controles de tentativas de login"

    def __str__(self):
        return (
            f"{self.scope}: "
            f"{self.failures} falha(s)"
        )


class SecurityEvent(models.Model):
    class EventType(models.TextChoices):
        LOGIN_BLOCKED = (
            "LOGIN_BLOCKED",
            "Login bloqueado",
        )
        LOGIN_SUCCESS = (
            "LOGIN_SUCCESS",
            "Login realizado",
        )
        LOCAL_ACCOUNT_RECOVERY = (
            "LOCAL_ACCOUNT_RECOVERY",
            "Recuperação local de acesso",
        )
        PROFILE_UPDATED = (
            "PROFILE_UPDATED",
            "Perfil atualizado",
        )
        INTEGRATION_CREATED = (
            "INTEGRATION_CREATED",
            "Integração criada",
        )
        INTEGRATION_UPDATED = (
            "INTEGRATION_UPDATED",
            "Integração atualizada",
        )
        INTEGRATION_TESTED = (
            "INTEGRATION_TESTED",
            "Integração testada",
        )
        REPORT_REQUESTED = (
            "REPORT_REQUESTED",
            "Relatório solicitado",
        )
        REPORT_IMPORTED = (
            "REPORT_IMPORTED",
            "Relatório importado",
        )

    event_type = models.CharField(
        "Evento",
        max_length=32,
        choices=EventType.choices,
        db_index=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Usuário",
        related_name="security_events",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    success = models.BooleanField(
        "Sucesso",
        default=True,
        db_index=True,
    )
    ip_hash = models.CharField(
        "Hash do IP",
        max_length=64,
        blank=True,
        db_index=True,
    )
    detail = models.JSONField(
        "Detalhes",
        default=dict,
        blank=True,
    )
    created_at = models.DateTimeField(
        "Criado em",
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        ordering = [
            "-created_at",
            "-id",
        ]
        verbose_name = "Evento de segurança"
        verbose_name_plural = "Eventos de segurança"

    def __str__(self):
        return (
            f"{self.event_type} "
            f"{self.created_at:%d/%m/%Y %H:%M:%S}"
        )
