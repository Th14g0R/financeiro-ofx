from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _key() -> bytes:
    explicit = os.getenv(
        "FINANCEIRO_CREDENTIAL_KEY",
        "",
    ).strip()

    if explicit:
        return explicit.encode("ascii")

    if settings.SECURE_MODE:
        raise ImproperlyConfigured(
            (
                "FINANCEIRO_CREDENTIAL_KEY é obrigatória "
                "quando DJANGO_SECURE_MODE=True."
            )
        )

    # Compatibilidade local com instalações antigas: deriva uma chave estável
    # do SECRET_KEY local. Para novas instalações, prefira a chave dedicada.
    digest = hashlib.sha256(
        settings.SECRET_KEY.encode("utf-8")
    ).digest()

    return base64.urlsafe_b64encode(
        digest
    )


def encrypt_secret(value: str) -> str:
    if not value:
        return ""

    return Fernet(_key()).encrypt(
        value.encode("utf-8")
    ).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""

    return Fernet(_key()).decrypt(
        value.encode("ascii")
    ).decode("utf-8")
