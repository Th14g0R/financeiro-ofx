from __future__ import annotations

from datetime import datetime
from datetime import time
from datetime import timedelta
from datetime import timezone as dt_timezone
from urllib.parse import quote

import requests
from django.utils import timezone

from .models import BankIntegration


BASE_URL = "https://api.mercadopago.com"
TIMEOUT = (
    10,
    30,
)
MAX_REPORT_BYTES = (
    20 * 1024 * 1024
)
USER_AGENT = (
    "FinanceiroOFX/9.2 "
    "(server-side integration)"
)


class MercadoPagoApiError(
    ValueError
):
    pass


def _safe_api_message(
    response,
) -> str:
    request_id = (
        response.headers.get(
            "x-request-id",
            "",
        )
        or response.headers.get(
            "X-Request-Id",
            "",
        )
    ).strip()

    message = ""

    try:
        payload = response.json()

        if isinstance(
            payload,
            dict,
        ):
            message = str(
                payload.get(
                    "message",
                    "",
                )
                or payload.get(
                    "error",
                    "",
                )
                or ""
            ).strip()
    except ValueError:
        pass

    if not message:
        message = (
            "A API recusou a operação."
        )

    # Evita devolver conteúdo completo da resposta, headers,
    # credenciais ou parâmetros de request para a interface/log.
    result = (
        f"Mercado Pago HTTP "
        f"{response.status_code}: "
        f"{message[:300]}"
    )

    if request_id:
        result += (
            f" (request-id: "
            f"{request_id[:120]})"
        )

    return result


def _json_payload(
    response,
):
    try:
        return response.json()
    except ValueError as exc:
        raise MercadoPagoApiError(
            (
                "O Mercado Pago respondeu em um "
                "formato inesperado."
            )
        ) from exc


def _raise_for_response(
    response,
):
    if (
        200
        <= response.status_code
        < 300
    ):
        return

    raise MercadoPagoApiError(
        _safe_api_message(
            response
        )
    )


def _headers(
    token: str,
) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": (
            f"Bearer {token}"
        ),
        "User-Agent": USER_AGENT,
    }


def _json_headers(
    token: str,
) -> dict[str, str]:
    return {
        **_headers(token),
        "Content-Type": (
            "application/json"
        ),
    }


def get_access_token(
    integration: BankIntegration,
) -> str:
    if (
        integration.auth_mode
        == BankIntegration.AuthMode.ACCESS_TOKEN
    ):
        token = (
            integration.get_access_token()
        )

        if not token:
            raise MercadoPagoApiError(
                "Access Token não configurado."
            )

        return token

    now = timezone.now()

    if (
        integration.access_token_encrypted
        and integration.access_token_expires_at
        and integration.access_token_expires_at
        > now + timedelta(
            minutes=5
        )
    ):
        return (
            integration.get_access_token()
        )

    client_id = (
        integration.client_id.strip()
    )
    client_secret = (
        integration.get_client_secret()
    )

    if (
        not client_id
        or not client_secret
    ):
        raise MercadoPagoApiError(
            (
                "Client ID/Client Secret "
                "não configurados."
            )
        )

    try:
        response = requests.post(
            (
                f"{BASE_URL}"
                "/oauth/token"
            ),
            json={
                "client_id": client_id,
                "client_secret": (
                    client_secret
                ),
                "grant_type": (
                    "client_credentials"
                ),
            },
            headers={
                "Accept": (
                    "application/json"
                ),
                "Content-Type": (
                    "application/json"
                ),
                "User-Agent": USER_AGENT,
            },
            timeout=TIMEOUT,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise MercadoPagoApiError(
            (
                "Falha segura de comunicação "
                "com o Mercado Pago."
            )
        ) from exc

    _raise_for_response(
        response
    )

    payload = response.json()
    token = (
        payload.get(
            "access_token",
            "",
        )
        or ""
    ).strip()

    try:
        expires_in = int(
            payload.get(
                "expires_in",
                21600,
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        expires_in = 21600

    if not token:
        raise MercadoPagoApiError(
            (
                "A API não devolveu "
                "access_token."
            )
        )

    integration.set_access_token(
        token
    )
    integration.access_token_expires_at = (
        now
        + timedelta(
            seconds=max(
                expires_in - 300,
                300,
            )
        )
    )
    integration.status = (
        BankIntegration.Status.OK
    )
    integration.last_error = ""
    integration.save(
        update_fields=[
            "access_token_encrypted",
            "access_token_expires_at",
            "status",
            "last_error",
            "updated_at",
        ]
    )

    return token


REPORT_COLUMNS = [
    "EXTERNAL_REFERENCE",
    "SOURCE_ID",
    "USER_ID",
    "PAYMENT_METHOD_TYPE",
    "PAYMENT_METHOD",
    "DESCRIPTION",
    "POI_BANK_NAME",
    "POI_WALLET_NAME",
    "TRANSACTION_TYPE",
    "TRANSACTION_AMOUNT",
    "TRANSACTION_CURRENCY",
    "TRANSACTION_DATE",
    "SETTLEMENT_NET_AMOUNT",
    "SETTLEMENT_CURRENCY",
    "SETTLEMENT_DATE",
    "REAL_AMOUNT",
]


def _get(
    url: str,
    *,
    token: str,
    stream: bool = False,
):
    try:
        return requests.get(
            url,
            headers=_headers(
                token
            ),
            timeout=TIMEOUT,
            allow_redirects=False,
            stream=stream,
        )
    except requests.RequestException as exc:
        raise MercadoPagoApiError(
            (
                "Falha segura de comunicação "
                "com o Mercado Pago."
            )
        ) from exc


def _post(
    url: str,
    *,
    token: str,
    payload: dict,
):
    try:
        return requests.post(
            url,
            headers=_json_headers(
                token
            ),
            json=payload,
            timeout=TIMEOUT,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise MercadoPagoApiError(
            (
                "Falha segura de comunicação "
                "com o Mercado Pago."
            )
        ) from exc


def ensure_report_configuration(
    integration: BankIntegration,
) -> None:
    token = get_access_token(
        integration
    )
    url = (
        f"{BASE_URL}/v1/account/"
        "settlement_report/config"
    )

    response = _get(
        url,
        token=token,
    )

    if response.status_code == 200:
        return

    if response.status_code not in {
        400,
        404,
    }:
        _raise_for_response(
            response
        )

    create_response = _post(
        url,
        token=token,
        payload={
            "file_name_prefix": (
                "financeiro-ofx-settlement"
            ),
            "show_fee_prevision": False,
            "show_chargeback_cancel": True,
            "coupon_detailed": True,
            "include_withdraw": True,
            "shipping_detail": True,
            "refund_detailed": True,
            "display_timezone": (
                "GMT-03"
            ),
            "header_language": "pt",
            "frequency": {
                "hour": 0,
                "type": "monthly",
                "value": 1,
            },
            "columns": [
                {
                    "key": key
                }
                for key in REPORT_COLUMNS
            ],
        },
    )

    if create_response.status_code not in {
        200,
        201,
    }:
        verify = _get(
            url,
            token=token,
        )
        _raise_for_response(
            verify
        )


def request_report(
    integration: BankIntegration,
    *,
    begin_date,
    end_date,
) -> dict:
    ensure_report_configuration(
        integration
    )

    token = get_access_token(
        integration
    )

    begin_dt = datetime.combine(
        begin_date,
        time.min,
        tzinfo=dt_timezone.utc,
    )
    end_dt = datetime.combine(
        end_date,
        time.max.replace(
            microsecond=0
        ),
        tzinfo=dt_timezone.utc,
    )

    response = _post(
        (
            f"{BASE_URL}/v1/account/"
            "settlement_report"
        ),
        token=token,
        payload={
            "begin_date": (
                begin_dt.isoformat()
                .replace(
                    "+00:00",
                    "Z",
                )
            ),
            "end_date": (
                end_dt.isoformat()
                .replace(
                    "+00:00",
                    "Z",
                )
            ),
        },
    )
    _raise_for_response(
        response
    )

    integration.status = (
        BankIntegration.Status.OK
    )
    integration.last_error = ""
    integration.save(
        update_fields=[
            "status",
            "last_error",
            "updated_at",
        ]
    )

    payload = _json_payload(
        response
    )

    if not isinstance(
        payload,
        dict,
    ):
        raise MercadoPagoApiError(
            (
                "Resposta inesperada ao "
                "solicitar o relatório."
            )
        )

    return payload


def list_reports(
    integration: BankIntegration,
) -> list[dict]:
    token = get_access_token(
        integration
    )

    response = _get(
        (
            f"{BASE_URL}/v1/account/"
            "settlement_report/list"
        ),
        token=token,
    )
    _raise_for_response(
        response
    )

    payload = _json_payload(
        response
    )

    if not isinstance(
        payload,
        list,
    ):
        raise MercadoPagoApiError(
            (
                "Resposta inesperada ao "
                "listar relatórios."
            )
        )

    return payload


def download_report(
    integration: BankIntegration,
    *,
    file_name: str,
) -> bytes:
    token = get_access_token(
        integration
    )

    safe_name = quote(
        file_name,
        safe="",
    )

    response = _get(
        (
            f"{BASE_URL}/v1/account/"
            f"settlement_report/{safe_name}"
        ),
        token=token,
        stream=True,
    )
    _raise_for_response(
        response
    )

    content_length = (
        response.headers.get(
            "Content-Length",
            "",
        )
        or ""
    ).strip()

    if content_length.isdigit():
        if (
            int(content_length)
            > MAX_REPORT_BYTES
        ):
            response.close()
            raise MercadoPagoApiError(
                (
                    "O relatório excede o "
                    "limite seguro de 20 MB."
                )
            )

    chunks = []
    total = 0

    try:
        for chunk in response.iter_content(
            chunk_size=64 * 1024
        ):
            if not chunk:
                continue

            total += len(chunk)

            if total > MAX_REPORT_BYTES:
                raise MercadoPagoApiError(
                    (
                        "O relatório excede o "
                        "limite seguro de 20 MB."
                    )
                )

            chunks.append(
                chunk
            )
    finally:
        response.close()

    return b"".join(
        chunks
    )


def test_connection(
    integration: BankIntegration,
) -> None:
    token = get_access_token(
        integration
    )

    response = _get(
        (
            f"{BASE_URL}/v1/account/"
            "settlement_report/config"
        ),
        token=token,
    )

    # A conta pode ainda não possuir configuração do relatório.
    # 400/404 indicam que o token chegou autenticado ao endpoint.
    if response.status_code not in {
        200,
        400,
        404,
    }:
        _raise_for_response(
            response
        )
