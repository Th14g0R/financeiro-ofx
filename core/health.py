from __future__ import annotations

import os

from django.http import JsonResponse
from django.views.decorators.http import require_GET


LOOPBACK_ADDRESSES = {
    "127.0.0.1",
    "::1",
}


@require_GET
def health_check(request):
    payload = {
        "application": "financeiro-ofx",
        "status": "ok",
    }

    remote_addr = (
        request.META.get(
            "REMOTE_ADDR",
            "",
        )
        .strip()
    )

    # O PID é útil para o Gerenciador local encerrar o processo correto,
    # mas não é exposto aos clientes da rede local.
    if remote_addr in LOOPBACK_ADDRESSES:
        payload["pid"] = os.getpid()

    response = JsonResponse(
        payload
    )
    response["Cache-Control"] = (
        "no-store, max-age=0"
    )
    return response
