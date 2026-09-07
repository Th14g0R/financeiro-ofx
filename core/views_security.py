from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.forms.utils import ErrorDict
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse_lazy

from .forms import AccountProfileForm
from .forms import LoginForm
from .forms import RecoveryPasswordResetForm
from .models import SecurityEvent
from .security import clear_username_failures
from .security import login_is_blocked
from .security import record_security_event
from .security import register_login_failure
from .security import sensitive_operation_allowed


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
            form._errors = ErrorDict()
            form.cleaned_data = {}
            lock_minutes = max(
                1,
                (
                    settings.LOGIN_THROTTLE_LOCK_SECONDS
                    + 59
                )
                // 60,
            )
            form.add_error(
                None,
                (
                    "Muitas tentativas de acesso. "
                    f"Aguarde cerca de {lock_minutes} minuto(s) "
                    "ou use a recuperação de senha."
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
            form.cleaned_data.get(
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


class SecurePasswordResetView(
    auth_views.PasswordResetView
):
    template_name = (
        "registration/password_reset_form.html"
    )
    email_template_name = (
        "registration/password_reset_email.txt"
    )
    subject_template_name = (
        "registration/password_reset_subject.txt"
    )
    form_class = RecoveryPasswordResetForm
    success_url = reverse_lazy(
        "password_reset_done"
    )

    def dispatch(
        self,
        request,
        *args,
        **kwargs,
    ):
        if not sensitive_operation_allowed(
            request
        ):
            messages.error(
                request,
                (
                    "Por segurança, a recuperação de senha só pode "
                    "ser solicitada neste computador ou através "
                    "de HTTPS."
                ),
            )
            return redirect("login")

        return super().dispatch(
            request,
            *args,
            **kwargs,
        )

    def form_valid(self, form):
        if not settings.PASSWORD_RECOVERY_EMAIL_ENABLED:
            form.add_error(
                None,
                (
                    "O envio de e-mail ainda não foi configurado. "
                    "Use o Gerenciador → Usuários / recuperação "
                    "para redefinir a senha localmente e configurar "
                    "o e-mail SMTP."
                ),
            )
            return self.form_invalid(form)

        try:
            return super().form_valid(
                form
            )
        except Exception:
            form.add_error(
                None,
                (
                    "Não foi possível enviar o e-mail de recuperação. "
                    "Verifique a configuração SMTP no Gerenciador."
                ),
            )
            return self.form_invalid(form)


class SecurePasswordResetConfirmView(
    auth_views.PasswordResetConfirmView
):
    template_name = (
        "registration/password_reset_confirm.html"
    )
    success_url = reverse_lazy(
        "password_reset_complete"
    )

    def dispatch(
        self,
        request,
        *args,
        **kwargs,
    ):
        if not sensitive_operation_allowed(
            request
        ):
            messages.error(
                request,
                (
                    "Por segurança, a troca de senha por link "
                    "só pode ser concluída neste computador ou "
                    "através de HTTPS."
                ),
            )
            return redirect("login")

        return super().dispatch(
            request,
            *args,
            **kwargs,
        )


@login_required
def account_profile(request):
    if request.method == "POST":
        form = AccountProfileForm(
            request.POST,
            user=request.user,
        )

        if form.is_valid():
            request.user.email = (
                form.cleaned_data[
                    "email"
                ]
            )
            request.user.save(
                update_fields=[
                    "email",
                ]
            )

            SecurityEvent.objects.create(
                event_type=(
                    SecurityEvent.EventType.PROFILE_UPDATED
                ),
                user=request.user,
                success=True,
                detail={
                    "recovery_email_updated": True,
                },
            )

            messages.success(
                request,
                "E-mail de recuperação atualizado.",
            )
            return redirect(
                "account_profile"
            )
    else:
        form = AccountProfileForm(
            user=request.user,
        )

    return render(
        request,
        "registration/account_profile.html",
        {
            "form": form,
            "recovery_email_enabled": (
                settings.PASSWORD_RECOVERY_EMAIL_ENABLED
            ),
        },
    )
