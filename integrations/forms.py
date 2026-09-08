from __future__ import annotations

from django import forms
from django.conf import settings

from finance.models import Account

from .models import BankIntegration
from .models import PluggyAccount
from .models import PluggyConfiguration


class BankIntegrationForm(forms.ModelForm):
    current_password = forms.CharField(
        label="Senha atual do Financeiro OFX",
        required=True,
        strip=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={
                "class": "form-control",
                "autocomplete": "current-password",
            },
        ),
        help_text=(
            "Confirme sua senha para criar ou alterar credenciais bancárias."
        ),
    )
    client_secret = forms.CharField(
        label="Client Secret",
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={
                "class": "form-control",
                "autocomplete": "new-password",
            },
        ),
        help_text=(
            "Deixe vazio ao editar para manter o segredo já salvo."
        ),
    )
    access_token = forms.CharField(
        label="Access Token",
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={
                "class": "form-control",
                "autocomplete": "new-password",
            },
        ),
        help_text=(
            "Opcional. Use para autenticação direta por Access Token."
        ),
    )

    class Meta:
        model = BankIntegration
        fields = [
            "name",
            "provider",
            "account",
            "auth_mode",
            "client_id",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "provider": forms.Select(
                attrs={"class": "form-select"}
            ),
            "account": forms.Select(
                attrs={"class": "form-select"}
            ),
            "auth_mode": forms.Select(
                attrs={"class": "form-select"}
            ),
            "client_id": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "is_active": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
        }

    def __init__(
        self,
        *args,
        user=None,
        **kwargs,
    ):
        self.user = user
        self.original_auth_mode = (
            getattr(
                kwargs.get("instance"),
                "auth_mode",
                None,
            )
        )
        self.original_client_id = (
            getattr(
                kwargs.get("instance"),
                "client_id",
                "",
            )
            or ""
        )

        super().__init__(
            *args,
            **kwargs,
        )

        self.fields["account"].queryset = (
            Account.objects.select_related("bank")
            .filter(is_active=True)
            .order_by("bank__name", "nickname")
        )

    def clean(self):
        cleaned = super().clean()

        auth_mode = cleaned.get("auth_mode")
        client_id = (
            cleaned.get("client_id")
            or ""
        ).strip()
        client_secret = (
            cleaned.get("client_secret")
            or ""
        ).strip()
        access_token = (
            cleaned.get("access_token")
            or ""
        ).strip()
        current_password = (
            cleaned.get("current_password")
            or ""
        )

        if settings.DEBUG:
            raise forms.ValidationError(
                (
                    "Credenciais bancárias não podem ser salvas "
                    "com DJANGO_DEBUG=True. Altere o .env para "
                    "DJANGO_DEBUG=False, reinicie o sistema e tente novamente."
                )
            )

        if (
            self.user is None
            or not self.user.is_authenticated
            or not self.user.check_password(
                current_password
            )
        ):
            self.add_error(
                "current_password",
                (
                    "A senha atual não confere."
                ),
            )

        has_saved_secret = bool(
            self.instance.pk
            and self.instance.client_secret_encrypted
        )
        has_saved_token = bool(
            self.instance.pk
            and (
                self.original_auth_mode
                == BankIntegration.AuthMode.ACCESS_TOKEN
            )
            and self.instance.access_token_encrypted
        )

        if (
            auth_mode
            == BankIntegration.AuthMode.CLIENT_CREDENTIALS
        ):
            if not client_id:
                self.add_error(
                    "client_id",
                    "Informe o Client ID.",
                )

            if not (
                client_secret
                or has_saved_secret
            ):
                self.add_error(
                    "client_secret",
                    "Informe o Client Secret.",
                )

        elif (
            auth_mode
            == BankIntegration.AuthMode.ACCESS_TOKEN
        ):
            if not (
                access_token
                or has_saved_token
            ):
                self.add_error(
                    "access_token",
                    "Informe o Access Token.",
                )

        return cleaned

    def save(self, commit=True):
        instance = super().save(
            commit=False
        )

        client_secret = (
            self.cleaned_data.get(
                "client_secret"
            )
            or ""
        ).strip()
        access_token = (
            self.cleaned_data.get(
                "access_token"
            )
            or ""
        ).strip()

        credentials_changed = False

        if client_secret:
            instance.set_client_secret(
                client_secret
            )
            credentials_changed = True

        if (
            self.original_client_id
            != instance.client_id
        ):
            credentials_changed = True

        if (
            self.original_auth_mode
            != instance.auth_mode
        ):
            credentials_changed = True

        if (
            instance.auth_mode
            == BankIntegration.AuthMode.ACCESS_TOKEN
        ):
            # No modo Access Token direto não mantemos Client Secret
            # desnecessariamente armazenado.
            if instance.client_secret_encrypted:
                instance.client_secret_encrypted = ""
                credentials_changed = True

            if access_token:
                instance.set_access_token(
                    access_token
                )
                instance.access_token_expires_at = None
                credentials_changed = True
        else:
            if credentials_changed:
                instance.access_token_encrypted = ""
                instance.access_token_expires_at = None

        if credentials_changed:
            instance.status = (
                BankIntegration.Status.NEW
            )
            instance.last_error = ""

        if commit:
            instance.save()

        return instance


class ReportPeriodForm(forms.Form):
    begin_date = forms.DateField(
        label="Data inicial",
        widget=forms.DateInput(
            attrs={
                "class": "form-control",
                "type": "date",
            }
        ),
    )
    end_date = forms.DateField(
        label="Data final",
        widget=forms.DateInput(
            attrs={
                "class": "form-control",
                "type": "date",
            }
        ),
    )

    def clean(self):
        cleaned = super().clean()
        begin = cleaned.get("begin_date")
        end = cleaned.get("end_date")

        if begin and end and begin > end:
            raise forms.ValidationError(
                "A data inicial não pode ser maior que a final."
            )

        if (
            begin
            and end
            and (end - begin).days > 59
        ):
            raise forms.ValidationError(
                "O relatório Dinheiro em conta do Mercado Pago "
                "aceita no máximo 60 dias por relatório."
            )

        return cleaned



class PluggyConfigurationForm(forms.ModelForm):
    current_password = forms.CharField(
        label="Senha atual do Financeiro OFX",
        strip=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"class": "form-control", "autocomplete": "current-password"},
        ),
        help_text="Confirme sua senha para cadastrar ou alterar as credenciais Pluggy.",
    )
    client_secret = forms.CharField(
        label="Client Secret",
        required=False,
        strip=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"class": "form-control", "autocomplete": "new-password"},
        ),
        help_text="Deixe vazio ao editar para manter o Client Secret já salvo.",
    )

    class Meta:
        model = PluggyConfiguration
        fields = ["name", "client_id", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "client_id": forms.TextInput(attrs={"class": "form-control", "autocomplete": "off"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if settings.DEBUG:
            raise forms.ValidationError(
                "Credenciais Pluggy não podem ser salvas com DJANGO_DEBUG=True."
            )
        password = cleaned.get("current_password") or ""
        if (
            self.user is None
            or not self.user.is_authenticated
            or not self.user.check_password(password)
        ):
            self.add_error("current_password", "A senha atual não confere.")
        if not (cleaned.get("client_id") or "").strip():
            self.add_error("client_id", "Informe o Client ID.")
        if not (
            (cleaned.get("client_secret") or "").strip()
            or (self.instance.pk and self.instance.client_secret_encrypted)
        ):
            self.add_error("client_secret", "Informe o Client Secret.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        secret = (self.cleaned_data.get("client_secret") or "").strip()
        changed = False
        if secret:
            instance.set_client_secret(secret)
            changed = True
        if self.instance.pk and "client_id" in self.changed_data:
            changed = True
        if changed:
            instance.clear_api_key()
            instance.status = PluggyConfiguration.Status.NEW
            instance.last_error = ""
        if commit:
            instance.save()
        return instance


class PluggyItemIdForm(forms.Form):
    item_id = forms.UUIDField(
        label="Item ID da Pluggy",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                "autocomplete": "off",
            }
        ),
        help_text="Use quando quiser registrar uma conexão específica que já pertence à sua aplicação Pluggy.",
    )


class PluggyAccountMappingForm(forms.Form):
    local_account = forms.ModelChoiceField(
        label="Conta local",
        queryset=Account.objects.none(),
        required=False,
        empty_label="— Criar/vincular automaticamente na próxima sincronização —",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["local_account"].queryset = (
            Account.objects.select_related("bank")
            .filter(is_active=True)
            .order_by("bank__name", "nickname")
        )


class PluggyCleanupConfirmationForm(forms.Form):
    delete_empty_local_accounts = forms.BooleanField(
        label=(
            "Excluir também as contas locais e os bancos cadastrados automaticamente "
            "pela Pluggy quando ficarem vazios e sem uso por OFX/PDF, outra integração "
            "ou outro Item Pluggy"
        ),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    remove_item = forms.BooleanField(
        label=(
            "Remover também este Item do Financeiro OFX (não exclui a "
            "conexão no Pluggy Dashboard)"
        ),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    confirmation = forms.CharField(
        label='Digite "EXCLUIR" para confirmar',
        max_length=20,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "placeholder": "EXCLUIR",
            }
        ),
    )
    current_password = forms.CharField(
        label="Senha atual do Financeiro OFX",
        strip=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={
                "class": "form-control",
                "autocomplete": "current-password",
            },
        ),
        help_text=(
            "A exclusão de movimentações financeiras exige confirmação da "
            "senha do usuário atualmente autenticado."
        ),
    )

    def __init__(
        self,
        *args,
        user=None,
        allow_remove_item=True,
        **kwargs,
    ):
        self.user = user
        super().__init__(*args, **kwargs)

        if not allow_remove_item:
            self.fields.pop("remove_item", None)

    def clean_confirmation(self):
        value = (self.cleaned_data.get("confirmation") or "").strip().upper()
        if value != "EXCLUIR":
            raise forms.ValidationError('Digite exatamente "EXCLUIR".')
        return value

    def clean_current_password(self):
        password = self.cleaned_data.get("current_password") or ""
        if (
            self.user is None
            or not self.user.is_authenticated
            or not self.user.check_password(password)
        ):
            raise forms.ValidationError("A senha atual não confere.")
        return password
