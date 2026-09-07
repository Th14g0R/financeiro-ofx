from __future__ import annotations

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import UserAccessProfile


def user_role(user) -> str:
    if not getattr(user, "is_authenticated", False):
        return ""

    if user.is_superuser:
        return UserAccessProfile.Role.ADMIN

    try:
        return user.access_profile.role
    except UserAccessProfile.DoesNotExist:
        # Fail-safe para usuário legado ainda sem profile: não concede
        # privilégios administrativos silenciosamente.
        return UserAccessProfile.Role.OPERATOR


def user_is_system_admin(user) -> bool:
    return user_role(user) == UserAccessProfile.Role.ADMIN


def system_admin_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not user_is_system_admin(request.user):
            raise PermissionDenied(
                "Somente administradores podem acessar esta área."
            )
        return view_func(request, *args, **kwargs)

    return wrapped
