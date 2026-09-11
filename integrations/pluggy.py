from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from django.utils import timezone

from .models import PluggyConfiguration


API_BASE_URL = "https://api.pluggy.ai"
REQUEST_TIMEOUT_SECONDS = 30
API_KEY_SAFETY_MARGIN = timedelta(minutes=5)
MEU_PLUGGY_CONNECTOR_ID = 200


class PluggyApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _safe_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        candidates = [
            payload.get("message"),
            payload.get("error"),
            payload.get("errorMessage"),
            payload.get("code"),
        ]
        for value in candidates:
            if isinstance(value, str) and value.strip():
                return value.strip()[:500]
    return f"Pluggy respondeu HTTP {response.status_code}."


def _request_json(
    method: str,
    path: str,
    *,
    api_key: str | None = None,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    if not path.startswith("/"):
        path = "/" + path

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Financeiro-OFX/10.9.11",
    }
    if api_key:
        headers["X-API-KEY"] = api_key

    try:
        response = requests.request(
            method,
            API_BASE_URL + path,
            headers=headers,
            json=json,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise PluggyApiError(
            "Não foi possível comunicar com a Pluggy. Verifique Internet/DNS e tente novamente."
        ) from exc

    if not 200 <= response.status_code < 300:
        raise PluggyApiError(
            _safe_error_message(response),
            status_code=response.status_code,
        )

    if response.status_code == 204 or not response.content:
        return {}

    try:
        return response.json()
    except ValueError as exc:
        raise PluggyApiError("A Pluggy retornou uma resposta JSON inválida.") from exc


def authenticate(configuration: PluggyConfiguration, *, force: bool = False) -> str:
    now = timezone.now()
    if (
        not force
        and configuration.api_key_encrypted
        and configuration.api_key_expires_at
        and configuration.api_key_expires_at - API_KEY_SAFETY_MARGIN > now
    ):
        return configuration.get_api_key()

    payload = _request_json(
        "POST",
        "/auth",
        json={
            "clientId": configuration.client_id,
            "clientSecret": configuration.get_client_secret(),
        },
    )
    if not isinstance(payload, dict):
        raise PluggyApiError("Resposta inesperada ao autenticar na Pluggy.")

    api_key = payload.get("apiKey") or payload.get("accessToken")
    if not isinstance(api_key, str) or not api_key.strip():
        raise PluggyApiError("A Pluggy não retornou a API Key esperada.")

    configuration.set_api_key(api_key.strip())
    configuration.api_key_expires_at = now + timedelta(hours=2)
    configuration.status = PluggyConfiguration.Status.OK
    configuration.last_error = ""
    configuration.save(
        update_fields=[
            "api_key_encrypted",
            "api_key_expires_at",
            "status",
            "last_error",
            "updated_at",
        ]
    )
    return api_key.strip()


def test_connection(configuration: PluggyConfiguration) -> None:
    api_key = authenticate(configuration, force=True)
    _request_json(
        "GET",
        "/connectors",
        api_key=api_key,
        params={"countries": "BR", "sandbox": "false"},
    )


def retrieve_connector(
    configuration: PluggyConfiguration,
    connector_id: int,
) -> dict[str, Any]:
    api_key = authenticate(configuration)
    payload = _request_json(
        "GET",
        f"/connectors/{int(connector_id)}",
        api_key=api_key,
    )
    if not isinstance(payload, dict):
        raise PluggyApiError(
            "Resposta inesperada ao consultar o conector Pluggy."
        )
    return payload


def create_connect_token(
    configuration: PluggyConfiguration,
    *,
    client_user_id: str,
    item_id: str | None = None,
) -> str:
    """
    Gera o Connect Token de curta duração destinado ao navegador.

    Client ID, Client Secret e API Key nunca são retornados ao frontend.
    """
    api_key = authenticate(configuration)

    payload: dict[str, Any] = {
        "options": {
            "clientUserId": str(client_user_id)[:120],
            "avoidDuplicates": True,
        }
    }

    if item_id:
        payload["itemId"] = str(item_id).strip()

    response = _request_json(
        "POST",
        "/connect_token",
        api_key=api_key,
        json=payload,
    )

    if not isinstance(response, dict):
        raise PluggyApiError(
            "Resposta inesperada ao criar o Connect Token."
        )

    token = (
        response.get("accessToken")
        or response.get("connectToken")
        or response.get("token")
    )

    if not isinstance(token, str) or not token.strip():
        raise PluggyApiError(
            "A Pluggy não retornou o Connect Token esperado."
        )

    return token.strip()


def retrieve_item(configuration: PluggyConfiguration, item_id: str) -> dict[str, Any]:
    api_key = authenticate(configuration)
    payload = _request_json("GET", f"/items/{item_id}", api_key=api_key)
    if not isinstance(payload, dict):
        raise PluggyApiError("Resposta inesperada ao consultar a conexão Pluggy.")
    return payload


def retrieve_identity(
    configuration: PluggyConfiguration,
    item_id: str,
) -> dict[str, Any]:
    api_key = authenticate(configuration)
    try:
        payload = _request_json(
            "GET",
            "/identity",
            api_key=api_key,
            params={"itemId": item_id},
        )
    except PluggyApiError as exc:
        # Identity is not covered by every institution/product. A 404 means
        # simply that this Item has no Identity product available.
        if exc.status_code == 404:
            return {}
        raise
    return payload if isinstance(payload, dict) else {}


def trigger_item_update(configuration: PluggyConfiguration, item_id: str) -> dict[str, Any]:
    api_key = authenticate(configuration)
    payload = _request_json(
        "PATCH",
        f"/items/{item_id}",
        api_key=api_key,
        json={},
    )
    return payload if isinstance(payload, dict) else {}


def list_accounts(configuration: PluggyConfiguration, item_id: str) -> list[dict[str, Any]]:
    api_key = authenticate(configuration)
    payload = _request_json(
        "GET",
        "/accounts",
        api_key=api_key,
        params={"itemId": item_id, "type": "BANK"},
    )
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("results", "accounts", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def list_all_transactions(
    configuration: PluggyConfiguration,
    account_id: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    api_key = authenticate(configuration)
    params: dict[str, Any] = {"accountId": account_id}
    if date_from:
        params["dateFrom"] = date_from
    if date_to:
        params["dateTo"] = date_to

    results: list[dict[str, Any]] = []
    path = "/v2/transactions"
    seen_next: set[str] = set()

    for _ in range(200):
        payload = _request_json("GET", path, api_key=api_key, params=params)
        if not isinstance(payload, dict):
            raise PluggyApiError("Resposta inesperada ao listar transações Pluggy.")

        page = payload.get("results")
        if isinstance(page, list):
            results.extend(x for x in page if isinstance(x, dict))

        next_value = payload.get("next")
        if not isinstance(next_value, str) or not next_value.strip():
            break
        if next_value in seen_next:
            raise PluggyApiError("A paginação da Pluggy repetiu o mesmo cursor.")
        seen_next.add(next_value)

        parsed = urlparse(next_value)
        if parsed.path:
            path = parsed.path
        else:
            path = "/v2/transactions"
        parsed_params = parse_qs(parsed.query, keep_blank_values=True)
        params = {
            key: values[-1] if len(values) == 1 else values
            for key, values in parsed_params.items()
        }
    else:
        raise PluggyApiError("A paginação da Pluggy excedeu o limite de segurança.")

    return results
