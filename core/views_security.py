from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.forms.utils import ErrorDict
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.decorators.csrf import csrf_protect

from .access import active_system_admin_exists
from .forms import AccountProfileForm
from .forms import InitialAdminSetupForm
from .forms import LoginForm
from .forms import RecoveryPasswordResetForm
from .models import AuditEvent
from .models import SecurityEvent
from .models import UserAccessProfile
from .security import clear_username_failures
from .security import client_is_loopback
from .security import _protected_hash
from .security import client_ip
from .security import login_is_blocked
from .security import record_security_event
from .security import register_login_failure
from .security import sensitive_operation_allowed


@csrf_protect
def initial_admin_setup(request):
    """Cria o primeiro administrador exclusivamente a partir do próprio PC."""
    if not client_is_loopback(request):
        return render(
            request,
            "registration/initial_admin_forbidden.html",
            status=403,
        )

    if active_system_admin_exists():
        if request.user.is_authenticated:
            return redirect("home")
        return redirect("login")

    if request.method == "POST":
        form = InitialAdminSetupForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                # Revalida imediatamente antes de gravar para evitar a criação
                # acidental de um segundo administrador em abas concorrentes.
                if active_system_admin_exists():
                    messages.warning(
                        request,
                        "Um administrador já foi criado. Faça login para continuar.",
                    )
                    return redirect("login")

                user = form.save()

                request_id = (
                    getattr(request, "audit_request_id", "")
                    or "initial-admin"
                )
                ip_value = client_ip(request)
                AuditEvent.objects.create(
                    actor=user,
                    action="initial_admin_setup",
                    method="POST",
                    path=request.path[:500],
                    status_code=302,
                    success=True,
                    request_id=str(request_id)[:36],
                    ip_hash=(
                        _protected_hash("audit-ip", ip_value)
                        if ip_value
                        else ""
                    ),
                    detail={
                        "operation": {
                            "first_administrator_created": True,
                            "target_user_id": user.pk,
                            "target_role": UserAccessProfile.Role.ADMIN,
                        }
                    },
                )

            login(request, user)

            messages.success(
                request,
                (
                    "Administrador inicial criado com sucesso. "
                    "O Financeiro OFX está pronto para uso."
                ),
            )
            return redirect("home")
    else:
        form = InitialAdminSetupForm()

    return render(
        request,
        "registration/initial_admin_setup.html",
        {"form": form},
    )


class SecureLoginView(
    auth_views.LoginView
):
    template_name = (
        "registration/login.html"
    )
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if not active_system_admin_exists():
            return redirect("initial_admin_setup")
        return super().dispatch(request, *args, **kwargs)

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
                record_security_event(
                    self.request,
                    event_type=(
                        SecurityEvent.EventType.LOGIN_FAILURE
                    ),
                    success=False,
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


class SecurePasswordChangeView(
    auth_views.PasswordChangeView
):
    template_name = (
        "registration/password_change_form.html"
    )
    success_url = reverse_lazy(
        "password_change_done"
    )

    def dispatch(
        self,
        request,
        *args,
        **kwargs,
    ):
        if not sensitive_operation_allowed(request):
            messages.error(
                request,
                (
                    "Por segurança, a alteração de senha só pode "
                    "ser realizada neste computador ou através de HTTPS."
                ),
            )
            return redirect("account_profile")

        return super().dispatch(
            request,
            *args,
            **kwargs,
        )


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
    if (
        request.method == "POST"
        and not sensitive_operation_allowed(request)
    ):
        messages.error(
            request,
            (
                "Por segurança, a alteração do e-mail de recuperação "
                "só pode ser realizada neste computador ou através de HTTPS."
            ),
        )
        return redirect("account_profile")

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
