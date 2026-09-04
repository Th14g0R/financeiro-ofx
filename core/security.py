from __future__ import annotations

from datetime import timedelta
import hashlib
import ipaddress
import hmac

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import LoginThrottleBucket
from .models import SecurityEvent


def _protected_hash(
    scope: str,
    value: str,
) -> str:
    normalized = (
        value or ""
    ).strip().casefold()

    return hmac.new(
        settings.SECRET_KEY.encode(
            "utf-8"
        ),
        (
            f"{scope}:"
            f"{normalized}"
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def client_ip(
    request,
) -> str:
    # Por padrão não confiamos em X-Forwarded-For.
    # O reverse proxy deve entregar REMOTE_ADDR corretamente.
    return (
        request.META.get(
            "REMOTE_ADDR",
            "",
        )
        or ""
    ).strip()


def client_is_loopback(
    request,
) -> bool:
    value = client_ip(
        request
    )

    if not value:
        return False

    try:
        return ipaddress.ip_address(
            value
        ).is_loopback
    except ValueError:
        return False


def sensitive_operation_allowed(
    request,
) -> bool:
    # Credenciais bancárias só podem ser digitadas no próprio computador
    # ou através de HTTPS corretamente reconhecido pelo Django.
    return (
        client_is_loopback(
            request
        )
        or request.is_secure()
    )


def _bucket_hash(
    scope: str,
    value: str,
) -> str:
    return _protected_hash(
        scope,
        value,
    )


def _limits(
    scope: str,
):
    if (
        scope
        == LoginThrottleBucket.Scope.USERNAME
    ):
        return (
            settings.LOGIN_THROTTLE_USERNAME_MAX,
            settings.LOGIN_THROTTLE_WINDOW_SECONDS,
            settings.LOGIN_THROTTLE_LOCK_SECONDS,
        )

    return (
        settings.LOGIN_THROTTLE_IP_MAX,
        settings.LOGIN_THROTTLE_WINDOW_SECONDS,
        settings.LOGIN_THROTTLE_LOCK_SECONDS,
    )


def _is_bucket_locked(
    bucket,
    *,
    now,
):
    return bool(
        bucket
        and bucket.locked_until
        and bucket.locked_until > now
    )


def login_is_blocked(
    request,
    username: str,
) -> bool:
    now = timezone.now()

    keys = [
        (
            LoginThrottleBucket.Scope.USERNAME,
            username,
        ),
        (
            LoginThrottleBucket.Scope.IP,
            client_ip(request),
        ),
    ]

    for scope, value in keys:
        if not value:
            continue

        bucket = (
            LoginThrottleBucket.objects.filter(
                key_hash=_bucket_hash(
                    scope,
                    value,
                )
            )
            .only(
                "locked_until",
            )
            .first()
        )

        if _is_bucket_locked(
            bucket,
            now=now,
        ):
            return True

    return False


@transaction.atomic
def _register_failure(
    *,
    scope: str,
    value: str,
):
    if not value:
        return

    now = timezone.now()

    maximum, window_seconds, lock_seconds = (
        _limits(scope)
    )

    key_hash = _bucket_hash(
        scope,
        value,
    )

    bucket = (
        LoginThrottleBucket.objects
        .select_for_update()
        .filter(
            key_hash=key_hash
        )
        .first()
    )

    if bucket is None:
        bucket = (
            LoginThrottleBucket.objects.create(
                scope=scope,
                key_hash=key_hash,
                failures=0,
                window_started_at=now,
            )
        )

    window_end = (
        bucket.window_started_at
        + timedelta(
            seconds=window_seconds
        )
    )

    if now >= window_end:
        bucket.failures = 0
        bucket.window_started_at = now
        bucket.locked_until = None

    bucket.failures += 1

    if bucket.failures >= maximum:
        bucket.locked_until = (
            now
            + timedelta(
                seconds=lock_seconds
            )
        )

    bucket.save(
        update_fields=[
            "failures",
            "window_started_at",
            "locked_until",
            "updated_at",
        ]
    )


def register_login_failure(
    request,
    username: str,
):
    _register_failure(
        scope=(
            LoginThrottleBucket.Scope.USERNAME
        ),
        value=username,
    )
    _register_failure(
        scope=(
            LoginThrottleBucket.Scope.IP
        ),
        value=client_ip(request),
    )


def clear_username_failures(
    username: str,
):
    if not username:
        return

    LoginThrottleBucket.objects.filter(
        key_hash=_bucket_hash(
            LoginThrottleBucket.Scope.USERNAME,
            username,
        )
    ).delete()


def record_security_event(
    request,
    *,
    event_type: str,
    success: bool = True,
    detail: dict | None = None,
):
    ip_value = client_ip(request)

    SecurityEvent.objects.create(
        event_type=event_type,
        user=(
            request.user
            if getattr(
                request,
                "user",
                None,
            )
            and request.user.is_authenticated
            else None
        ),
        success=success,
        ip_hash=(
            _protected_hash(
                "event-ip",
                ip_value,
            )
            if ip_value
            else ""
        ),
        detail=detail or {},
    )
