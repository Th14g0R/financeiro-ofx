from __future__ import annotations

import os

from django.conf import settings
from django.core.checks import Error
from django.core.checks import Tags
from django.core.checks import Warning
from django.core.checks import register


_LOOPBACK_HOSTS = {
    "127.0.0.1",
    "::1",
    "localhost",
}


def _env_flag(
    name: str,
    default: bool = False,
) -> bool:
    return (
        os.getenv(
            name,
            str(default),
        )
        .strip()
        .lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )


@register(
    Tags.security
)
def financeiro_security_checks(
    app_configs,
    **kwargs,
):
    issues = []

    if "*" in settings.ALLOWED_HOSTS:
        issues.append(
            Error(
                (
                    "DJANGO_ALLOWED_HOSTS não pode "
                    "usar '*' neste sistema financeiro."
                ),
                id="financeiro_security.E001",
            )
        )

    host = os.getenv(
        "FINANCEIRO_HOST",
        "127.0.0.1",
    ).strip()

    allow_network = _env_flag(
        "FINANCEIRO_ALLOW_NETWORK",
        False,
    )
    lan_mode = _env_flag(
        "FINANCEIRO_LAN_MODE",
        False,
    )

    if (
        host not in _LOOPBACK_HOSTS
        and not allow_network
    ):
        issues.append(
            Error(
                (
                    "FINANCEIRO_HOST expõe a aplicação "
                    "fora do localhost sem "
                    "FINANCEIRO_ALLOW_NETWORK=True."
                ),
                id="financeiro_security.E002",
            )
        )

    if (
        host not in _LOOPBACK_HOSTS
        and allow_network
        and not settings.SECURE_MODE
        and not lan_mode
    ):
        issues.append(
            Error(
                (
                    "Exposição fora do localhost exige "
                    "DJANGO_SECURE_MODE=True/HTTPS ou "
                    "FINANCEIRO_LAN_MODE=True para uma "
                    "sub-rede local explicitamente autorizada."
                ),
                id="financeiro_security.E003",
            )
        )

    if (
        host not in _LOOPBACK_HOSTS
        and allow_network
        and lan_mode
        and not settings.SECURE_MODE
    ):
        issues.append(
            Warning(
                (
                    "Modo Rede Local ativo sem HTTPS. "
                    "Use somente em rede privada/confiável; "
                    "o Firewall deve limitar o acesso à LocalSubnet."
                ),
                id="financeiro_security.W003",
            )
        )

    if (
        settings.SECURE_MODE
        and settings.DEBUG
    ):
        issues.append(
            Error(
                (
                    "DJANGO_DEBUG deve ser False "
                    "quando DJANGO_SECURE_MODE=True."
                ),
                id="financeiro_security.E004",
            )
        )

    if (
        settings.SECURE_MODE
        and not os.getenv(
            "FINANCEIRO_CREDENTIAL_KEY",
            "",
        ).strip()
    ):
        issues.append(
            Error(
                (
                    "FINANCEIRO_CREDENTIAL_KEY é "
                    "obrigatória no modo seguro."
                ),
                id="financeiro_security.E005",
            )
        )

    if (
        settings.SECURE_MODE
        and not settings.CSRF_TRUSTED_ORIGINS
    ):
        issues.append(
            Warning(
                (
                    "Defina DJANGO_CSRF_TRUSTED_ORIGINS "
                    "com a origem HTTPS pública."
                ),
                id="financeiro_security.W001",
            )
        )

    if (
        settings.DEBUG
        and host in _LOOPBACK_HOSTS
    ):
        issues.append(
            Warning(
                (
                    "DJANGO_DEBUG=True está ativo. "
                    "Use apenas para diagnóstico local "
                    "e desative antes de armazenar "
                    "credenciais de produção."
                ),
                id="financeiro_security.W002",
            )
        )

    return issues
