from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.forms import UsernameField


class LoginForm(AuthenticationForm):
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
