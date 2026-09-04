from __future__ import annotations

import os
from pathlib import Path

from waitress import serve


BASE_DIR = Path(__file__).resolve().parent
RUN_DIR = BASE_DIR / "run"
LOG_DIR = BASE_DIR / "logs"
PID_FILE = RUN_DIR / "financeiro_ofx.pid"


def main():
    os.chdir(BASE_DIR)

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE",
        "config.settings",
    )

    from config.wsgi import application
    from django.conf import settings

    host = os.getenv(
        "FINANCEIRO_HOST",
        "127.0.0.1",
    )
    port = int(
        os.getenv(
            "FINANCEIRO_PORT",
            "8000",
        )
    )

    loopback_hosts = {
        "127.0.0.1",
        "::1",
        "localhost",
    }
    allow_network = os.getenv(
        "FINANCEIRO_ALLOW_NETWORK",
        "False",
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    lan_mode = os.getenv(
        "FINANCEIRO_LAN_MODE",
        "False",
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if (
        host not in loopback_hosts
        and not allow_network
    ):
        raise RuntimeError(
            (
                "Inicialização recusada: o servidor "
                "está configurado para escutar fora "
                "do localhost. Defina "
                "FINANCEIRO_ALLOW_NETWORK=True "
                "explicitamente."
            )
        )

    if (
        host not in loopback_hosts
        and not settings.SECURE_MODE
        and not lan_mode
    ):
        raise RuntimeError(
            (
                "Inicialização recusada: exposição fora do localhost "
                "exige DJANGO_SECURE_MODE=True/HTTPS ou o modo "
                "FINANCEIRO_LAN_MODE=True explicitamente habilitado "
                "para uma rede local privada."
            )
        )

    PID_FILE.write_text(
        str(os.getpid()),
        encoding="ascii",
    )

    try:
        serve(
            application,
            host=host,
            port=port,
            threads=4,
            clear_untrusted_proxy_headers=True,
            expose_tracebacks=False,
        )
    finally:
        try:
            if PID_FILE.exists():
                current = PID_FILE.read_text(
                    encoding="ascii"
                ).strip()

                if current == str(os.getpid()):
                    PID_FILE.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
