from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.forms import UsernameField


class LoginForm(AuthenticationForm):
    error_messages = {
        "invalid_login": (
            "Usuário ou senha inválidos."
        ),
        "inactive": (
            "Esta conta está desativada."
        ),
    }

    username = UsernameField(
        label="Usuário",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "username",
                "autofocus": True,
                "placeholder": "Informe seu usuário",
            }
        ),
    )

    password = forms.CharField(
        label="Senha",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "current-password",
                "placeholder": "Informe sua senha",
            }
        ),
    )

    def clean_username(self):
        value = (
            self.cleaned_data.get(
                "username",
                "",
            )
            or ""
        ).strip()

        if not value:
            return value

        # O User padrão do Django pode buscar o username com a mesma
        # capitalização gravada no banco. Para evitar que "Thiago" e
        # "thiago" produzam falha de login, resolvemos o nome real de
        # forma case-insensitive antes de chamar authenticate().
        user_model = get_user_model()
        matches = list(
            user_model._default_manager.filter(
                **{
                    f"{user_model.USERNAME_FIELD}__iexact": value
                }
            ).values_list(
                user_model.USERNAME_FIELD,
                flat=True,
            )[:2]
        )

        if len(matches) == 1:
            return matches[0]

        return value


class RecoveryPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label="E-mail de recuperação",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "autocomplete": "email",
                "placeholder": "seuemail@exemplo.com",
            }
        ),
    )


class AccountProfileForm(forms.Form):
    email = forms.EmailField(
        label="E-mail de recuperação",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "autocomplete": "email",
            }
        ),
    )
    current_password = forms.CharField(
        label="Senha atual",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "current-password",
                "placeholder": (
                    "Confirme sua senha para alterar o e-mail"
                ),
            }
        ),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        if not self.is_bound:
            self.fields["email"].initial = (
                user.email
                or ""
            )

    def clean_email(self):
        email = (
            self.cleaned_data["email"]
            .strip()
        )
        user_model = get_user_model()

        duplicate = (
            user_model._default_manager.filter(
                email__iexact=email,
                is_active=True,
            )
            .exclude(pk=self.user.pk)
            .exists()
        )

        if duplicate:
            raise forms.ValidationError(
                (
                    "Este e-mail já está associado a outra "
                    "conta ativa."
                )
            )

        return email

    def clean_current_password(self):
        password = self.cleaned_data[
            "current_password"
        ]

        if not self.user.check_password(
            password
        ):
            raise forms.ValidationError(
                "Senha atual inválida."
            )

        return password
