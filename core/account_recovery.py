from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import LoginThrottleBucket
from .models import SecurityEvent


@dataclass(frozen=True, slots=True)
class LocalAccountInfo:
    username: str
    email: str
    is_active: bool
    is_superuser: bool
    has_usable_password: bool


def list_local_accounts() -> tuple[LocalAccountInfo, ...]:
    user_model = get_user_model()

    return tuple(
        LocalAccountInfo(
            username=user.get_username(),
            email=user.email or "",
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            has_usable_password=(
                user.has_usable_password()
            ),
        )
        for user in user_model._default_manager.order_by(
            user_model.USERNAME_FIELD
        )
    )


def _get_user_case_insensitive(
    username: str,
):
    user_model = get_user_model()
    username = (username or "").strip()

    matches = list(
        user_model._default_manager.filter(
            **{
                f"{user_model.USERNAME_FIELD}__iexact": (
                    username
                )
            }
        )[:2]
    )

    if len(matches) != 1:
        raise ValueError(
            "Usuário não encontrado ou nome ambíguo."
        )

    return matches[0]


def verify_local_password(
    *,
    username: str,
    password: str,
) -> bool:
    user = _get_user_case_insensitive(
        username
    )
    return user.check_password(
        password
    )


@transaction.atomic
def update_local_account_recovery(
    *,
    username: str,
    email: str | None = None,
    new_password: str | None = None,
) -> LocalAccountInfo:
    user_model = get_user_model()
    user = _get_user_case_insensitive(
        username
    )

    update_fields = []

    if email is not None:
        normalized_email = (
            email.strip()
        )

        if normalized_email:
            duplicate = (
                user_model._default_manager.filter(
                    email__iexact=(
                        normalized_email
                    ),
                    is_active=True,
                )
                .exclude(pk=user.pk)
                .exists()
            )

            if duplicate:
                raise ValueError(
                    (
                        "Este e-mail já está associado "
                        "a outra conta ativa."
                    )
                )

        user.email = normalized_email
        update_fields.append("email")

    password_changed = bool(
        new_password
    )

    if password_changed:
        try:
            validate_password(
                new_password,
                user=user,
            )
        except ValidationError as exc:
            raise ValueError(
                "\n".join(exc.messages)
            ) from exc

        user.set_password(
            new_password
        )
        update_fields.append("password")

    if update_fields:
        user.save(
            update_fields=update_fields
        )

    if password_changed:
        # A recuperação local é uma ação administrativa feita no próprio
        # computador. Depois de redefinir a senha, limpamos os bloqueios
        # temporários para que o novo acesso possa ser testado imediatamente.
        LoginThrottleBucket.objects.all().delete()

        SecurityEvent.objects.create(
            event_type=(
                SecurityEvent.EventType.LOCAL_ACCOUNT_RECOVERY
            ),
            user=user,
            success=True,
            detail={
                "password_reset": True,
                "email_updated": (
                    email is not None
                ),
            },
        )

    return LocalAccountInfo(
        username=user.get_username(),
        email=user.email or "",
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        has_usable_password=(
            user.has_usable_password()
        ),
    )
