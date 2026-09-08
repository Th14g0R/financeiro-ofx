from __future__ import annotations

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.http import HttpResponseForbidden
import uuid

from .models import AuditEvent
from .security import _protected_hash
from .security import client_ip
from .security import sensitive_operation_allowed


class SensitiveSurfaceMiddleware:
    """Bloqueia superfícies administrativas em HTTP remoto/LAN."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.path.startswith("/admin/")
            and not sensitive_operation_allowed(request)
        ):
            return HttpResponseForbidden(
                "Área administrativa disponível somente em localhost ou HTTPS."
            )

        return self.get_response(request)


class SecurityHeadersMiddleware:
    """
    Headers complementares para reduzir XSS, framing, vazamento de dados
    financeiros em cache e acesso a recursos do navegador desnecessários.
    """

    def __init__(
        self,
        get_response,
    ):
        self.get_response = (
            get_response
        )

    def __call__(
        self,
        request,
    ):
        response = self.get_response(
            request
        )

        if request.path.startswith(
            "/admin/"
        ):
            # O Django Admin usa alguns blocos inline próprios.
            # Mantemos a política restrita ao self e liberamos inline
            # somente nessa área administrativa.
            csp = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "font-src 'self' data:; "
                "connect-src 'self'; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "frame-ancestors 'none'; "
                "form-action 'self'"
            )
        elif (
            request.path.startswith(
                "/integrations/pluggy/"
            )
            and settings.PLUGGY_EMBEDDED_CONNECT_ENABLED
        ):
            # Exceção mínima e restrita ao Pluggy Connect quando a
            # integração embutida estiver explicitamente habilitada.
            csp = (
                "default-src 'self'; "
                "script-src 'self' "
                "https://cdn.jsdelivr.net "
                "https://cdn.pluggy.ai; "
                "script-src-attr 'none'; "
                "style-src 'self' https://cdn.jsdelivr.net; "
                "style-src-elem 'self' https://cdn.jsdelivr.net; "
                "style-src-attr 'unsafe-inline'; "
                "img-src 'self' data:; "
                "font-src 'self' data:; "
                "connect-src 'self' https://*.pluggy.ai; "
                "frame-src https://*.pluggy.ai; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "frame-ancestors 'none'; "
                "form-action 'self'"
            )
        else:
            csp = (
                "default-src 'self'; "
                "script-src 'self' https://cdn.jsdelivr.net; "
                "script-src-attr 'none'; "
                "style-src 'self' https://cdn.jsdelivr.net; "
                "style-src-elem 'self' https://cdn.jsdelivr.net; "
                "style-src-attr 'unsafe-inline'; "
                "img-src 'self' data:; "
                "font-src 'self' data:; "
                "connect-src 'self'; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "frame-ancestors 'none'; "
                "form-action 'self'"
            )

        if settings.SECURE_MODE:
            csp += (
                "; upgrade-insecure-requests"
            )

        response.headers.setdefault(
            "Content-Security-Policy",
            csp,
        )

        if (
            request.path.startswith(
                "/integrations/pluggy/"
            )
            and settings.PLUGGY_EMBEDDED_CONNECT_ENABLED
        ):
            # OAuth pode abrir uma janela externa quando o widget estiver
            # habilitado. A exceção não é aplicada ao fluxo manual.
            response.headers[
                "Cross-Origin-Opener-Policy"
            ] = "same-origin-allow-popups"

        response.headers.setdefault(
            "Permissions-Policy",
            (
                "camera=(), microphone=(), "
                "geolocation=(), payment=(), "
                "usb=(), serial=(), "
                "bluetooth=()"
            ),
        )

        response.headers.setdefault(
            "Cross-Origin-Resource-Policy",
            "same-origin",
        )

        response.headers.setdefault(
            "X-Permitted-Cross-Domain-Policies",
            "none",
        )

        if (
            getattr(
                request,
                "user",
                None,
            )
            and request.user.is_authenticated
        ):
            response.headers[
                "Cache-Control"
            ] = (
                "no-store, no-cache, "
                "must-revalidate, private"
            )
            response.headers[
                "Pragma"
            ] = "no-cache"

        return response



class AuditTrailMiddleware:
    """
    Registra toda requisição autenticada que possa alterar estado.

    Não grava valores de formulário, senhas, tokens ou conteúdo de arquivos.
    Somente usuário, rota, método, resultado, campos envolvidos e identificadores
    de rota não sensíveis.
    """

    UNSAFE_METHODS = {
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    }

    SENSITIVE_FIELD_MARKERS = (
        "password",
        "senha",
        "token",
        "secret",
        "credential",
        "client_secret",
        "access_token",
        "csrf",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def _safe_post_field_names(self, request):
        result = []
        for key in request.POST.keys():
            lowered = key.casefold()
            if any(marker in lowered for marker in self.SENSITIVE_FIELD_MARKERS):
                continue
            result.append(key[:80])
        return sorted(set(result))[:100]

    def _safe_route_kwargs(self, request):
        match = getattr(request, "resolver_match", None)
        if not match:
            return {}

        result = {}
        for key, value in (match.kwargs or {}).items():
            lowered = str(key).casefold()
            if any(marker in lowered for marker in self.SENSITIVE_FIELD_MARKERS):
                continue
            if isinstance(value, (str, int)):
                result[str(key)[:60]] = str(value)[:160]
        return result

    def _safe_explicit_detail(self, request):
        raw = getattr(request, "audit_detail", None)
        if not isinstance(raw, dict):
            return {}

        result = {}
        for key, value in raw.items():
            key_text = str(key)[:60]
            lowered = key_text.casefold()
            if any(marker in lowered for marker in self.SENSITIVE_FIELD_MARKERS):
                continue
            if isinstance(value, bool):
                result[key_text] = value
            elif isinstance(value, int):
                result[key_text] = value
            elif isinstance(value, str):
                result[key_text] = value[:160]
        return result

    def __call__(self, request):
        request_id = str(uuid.uuid4())
        request.audit_request_id = request_id

        actor_id = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            actor_id = user.pk

        try:
            response = self.get_response(request)
        except PermissionDenied:
            if actor_id:
                self._record(
                    request,
                    actor_id=actor_id,
                    request_id=request_id,
                    status_code=403,
                    success=False,
                )
            raise
        except Exception:
            if actor_id and request.method.upper() in self.UNSAFE_METHODS:
                self._record(
                    request,
                    actor_id=actor_id,
                    request_id=request_id,
                    status_code=500,
                    success=False,
                )
            raise

        should_audit = (
            request.method.upper() in self.UNSAFE_METHODS
            or response.status_code in {401, 403}
        )

        if actor_id and should_audit:
            self._record(
                request,
                actor_id=actor_id,
                request_id=request_id,
                status_code=response.status_code,
                success=(200 <= response.status_code < 400),
            )

        response.headers.setdefault(
            "X-Request-ID",
            request_id,
        )
        return response

    def _record(
        self,
        request,
        *,
        actor_id,
        request_id,
        status_code,
        success,
    ):
        match = getattr(request, "resolver_match", None)
        action = (
            match.view_name
            if match and match.view_name
            else request.path
        )
        ip_value = client_ip(request)

        detail = {
            "route_kwargs": self._safe_route_kwargs(request),
            "form_fields": self._safe_post_field_names(request),
            "file_fields": sorted(request.FILES.keys())[:50],
            "operation": self._safe_explicit_detail(request),
        }

        try:
            AuditEvent.objects.create(
                actor_id=actor_id,
                action=str(action)[:160],
                method=request.method.upper()[:10],
                path=request.path[:500],
                status_code=int(status_code),
                success=bool(success),
                request_id=request_id,
                ip_hash=(
                    _protected_hash("audit-ip", ip_value)
                    if ip_value
                    else ""
                ),
                detail=detail,
            )
        except DatabaseError:
            # A auditoria nunca deve mascarar a resposta original caso o banco
            # esteja indisponível. O erro do banco principal será tratado pela
            # própria operação que o causou.
            pass
