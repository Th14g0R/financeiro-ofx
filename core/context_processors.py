from __future__ import annotations

from .access import user_is_system_admin
from .access import user_role


def access_context(request):
    user = getattr(request, "user", None)

    if not user or not user.is_authenticated:
        return {
            "system_user_role": "",
            "can_manage_system_users": False,
            "can_manage_integrations": False,
        }

    is_admin = user_is_system_admin(user)
    return {
        "system_user_role": user_role(user),
        "can_manage_system_users": is_admin,
        "can_manage_integrations": is_admin,
    }
