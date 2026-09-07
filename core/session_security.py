from __future__ import annotations

from django.contrib.sessions.models import Session
from django.utils import timezone


def invalidate_user_sessions(
    user_id: int,
    *,
    exclude_session_key: str | None = None,
) -> int:
    """
    Remove sessões ativas pertencentes ao usuário.

    Isso é usado ao desativar uma conta ou redefinir sua senha para impedir
    que uma sessão antiga continue operando após a decisão administrativa.
    """
    deleted = 0

    sessions = Session.objects.filter(
        expire_date__gte=timezone.now()
    )

    for session in sessions.iterator():
        if (
            exclude_session_key
            and session.session_key == exclude_session_key
        ):
            continue

        try:
            data = session.get_decoded()
        except Exception:
            continue

        if str(data.get("_auth_user_id", "")) != str(user_id):
            continue

        session.delete()
        deleted += 1

    return deleted
