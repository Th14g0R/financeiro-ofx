from __future__ import annotations

from django.conf import settings


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
