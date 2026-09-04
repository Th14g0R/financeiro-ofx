from __future__ import annotations

from django.contrib.auth import views as auth_views
from django.forms.utils import ErrorDict

from .forms import LoginForm
from .models import SecurityEvent
from .security import clear_username_failures
from .security import login_is_blocked
from .security import record_security_event
from .security import register_login_failure


class SecureLoginView(
    auth_views.LoginView
):
    template_name = (
        "registration/login.html"
    )
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def post(
        self,
        request,
        *args,
        **kwargs,
    ):
        username = (
            request.POST.get(
                "username",
                "",
            )
            or ""
        ).strip()

        if login_is_blocked(
            request,
            username,
        ):
            form = self.get_form_class()(
                request=request,
                initial={
                    "username": username,
                },
            )
            # Evita chamar full_clean()/authenticate em uma requisição
            # que já foi bloqueada pelo rate limiter.
            form._errors = ErrorDict()
            form.cleaned_data = {}
            form.add_error(
                None,
                (
                    "Usuário ou senha inválidos. "
                    "Aguarde alguns minutos "
                    "antes de tentar novamente."
                ),
            )

            record_security_event(
                request,
                event_type=(
                    SecurityEvent.EventType.LOGIN_BLOCKED
                ),
                success=False,
            )

            response = self.form_invalid(
                form
            )
            response.status_code = 429
            return response

        return super().post(
            request,
            *args,
            **kwargs,
        )

    def form_invalid(
        self,
        form,
    ):
        if self.request.method == "POST":
            username = (
                self.request.POST.get(
                    "username",
                    "",
                )
                or ""
            ).strip()

            if not login_is_blocked(
                self.request,
                username,
            ):
                register_login_failure(
                    self.request,
                    username,
                )

        return super().form_invalid(
            form
        )

    def form_valid(
        self,
        form,
    ):
        username = (
            self.request.POST.get(
                "username",
                "",
            )
            or ""
        ).strip()

        clear_username_failures(
            username
        )

        response = super().form_valid(
            form
        )

        record_security_event(
            self.request,
            event_type=(
                SecurityEvent.EventType.LOGIN_SUCCESS
            ),
            success=True,
        )

        return response
