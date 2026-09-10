from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.forms import UsernameField
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.forms import SetPasswordForm

from .models import UserAccessProfile


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



class InitialAdminSetupForm(UserCreationForm):
    first_name = forms.CharField(
        label="Nome",
        max_length=150,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "given-name",
                "autofocus": True,
            }
        ),
    )
    last_name = forms.CharField(
        label="Sobrenome",
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "family-name",
            }
        ),
    )
    email = forms.EmailField(
        label="E-mail de recuperação",
        max_length=254,
        required=True,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "autocomplete": "email",
            }
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "password1",
            "password2",
        )
        widgets = {
            "username": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "autocomplete": "username",
                    "autocapitalize": "none",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "new-password",
            }
        )
        self.fields["password2"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "new-password",
            }
        )

    def clean_username(self):
        username = super().clean_username().strip()
        user_model = get_user_model()
        if user_model._default_manager.filter(
            username__iexact=username
        ).exists():
            raise forms.ValidationError(
                "Já existe um usuário com este nome, inclusive com outra capitalização."
            )
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        user_model = get_user_model()
        if user_model._default_manager.filter(
            email__iexact=email,
            is_active=True,
        ).exists():
            raise forms.ValidationError(
                "Este e-mail já está associado a outra conta ativa."
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.email = self.cleaned_data["email"].strip()
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True

        if commit:
            user.save()
            profile, _created = UserAccessProfile.objects.get_or_create(
                user=user
            )
            if profile.role != UserAccessProfile.Role.ADMIN:
                profile.role = UserAccessProfile.Role.ADMIN
                profile.save(update_fields=["role", "updated_at"])

        return user


class ManagedUserCreateForm(UserCreationForm):
    administrator_password = forms.CharField(
        label="Sua senha de administrador",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "current-password",
            }
        ),
    )
    first_name = forms.CharField(
        label="Nome",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    last_name = forms.CharField(
        label="Sobrenome",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        label="E-mail de recuperação",
        max_length=254,
        required=True,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "autocomplete": "email",
            }
        ),
    )
    role = forms.ChoiceField(
        label="Perfil",
        choices=UserAccessProfile.Role.choices,
        initial=UserAccessProfile.Role.OPERATOR,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "role",
            "password1",
            "password2",
        )
        widgets = {
            "username": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "autocomplete": "username",
                    "autocapitalize": "none",
                }
            ),
        }

    def __init__(self, *args, administrator, **kwargs):
        self.administrator = administrator
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs.update(
            {"class": "form-control", "autocomplete": "new-password"}
        )
        self.fields["password2"].widget.attrs.update(
            {"class": "form-control", "autocomplete": "new-password"}
        )

    def clean_administrator_password(self):
        value = self.cleaned_data["administrator_password"]
        if not self.administrator.check_password(value):
            raise forms.ValidationError("Sua senha de administrador está incorreta.")
        return value

    def clean_username(self):
        username = super().clean_username().strip()
        user_model = get_user_model()
        if user_model._default_manager.filter(username__iexact=username).exists():
            raise forms.ValidationError(
                "Já existe um usuário com este nome, inclusive com outra capitalização."
            )
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        user_model = get_user_model()
        if user_model._default_manager.filter(email__iexact=email, is_active=True).exists():
            raise forms.ValidationError(
                "Este e-mail já está associado a outra conta ativa."
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.email = self.cleaned_data["email"].strip()
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.save()
            profile, _created = UserAccessProfile.objects.get_or_create(user=user)
            profile.role = self.cleaned_data["role"]
            profile.save(update_fields=["role", "updated_at"])
        return user


class ManagedUserUpdateForm(forms.Form):
    administrator_password = forms.CharField(
        label="Sua senha de administrador",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "current-password",
            }
        ),
    )
    first_name = forms.CharField(
        label="Nome",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    last_name = forms.CharField(
        label="Sobrenome",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        label="E-mail de recuperação",
        max_length=254,
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )
    role = forms.ChoiceField(
        label="Perfil",
        choices=UserAccessProfile.Role.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    is_active = forms.BooleanField(
        label="Usuário ativo",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, user_obj, administrator, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_obj = user_obj
        self.administrator = administrator
        profile, _created = UserAccessProfile.objects.get_or_create(
            user=user_obj,
            defaults={
                "role": (
                    UserAccessProfile.Role.ADMIN
                    if user_obj.is_superuser
                    else UserAccessProfile.Role.OPERATOR
                )
            },
        )
        self.profile = profile

        if not self.is_bound:
            self.initial.update(
                {
                    "first_name": user_obj.first_name,
                    "last_name": user_obj.last_name,
                    "email": user_obj.email,
                    "role": profile.role,
                    "is_active": user_obj.is_active,
                }
            )

    def clean_administrator_password(self):
        value = self.cleaned_data["administrator_password"]
        if not self.administrator.check_password(value):
            raise forms.ValidationError("Sua senha de administrador está incorreta.")
        return value

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        user_model = get_user_model()
        duplicate = (
            user_model._default_manager.filter(
                email__iexact=email,
                is_active=True,
            )
            .exclude(pk=self.user_obj.pk)
            .exists()
        )
        if duplicate:
            raise forms.ValidationError(
                "Este e-mail já está associado a outra conta ativa."
            )
        return email

    def save(self):
        user = self.user_obj
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.email = self.cleaned_data["email"].strip()
        user.is_active = self.cleaned_data["is_active"]
        user.save(
            update_fields=[
                "first_name",
                "last_name",
                "email",
                "is_active",
            ]
        )
        self.profile.role = self.cleaned_data["role"]
        self.profile.save(update_fields=["role", "updated_at"])
        return user


class ManagedUserPasswordResetForm(SetPasswordForm):
    administrator_password = forms.CharField(
        label="Sua senha de administrador",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "current-password",
            }
        ),
    )

    def __init__(self, *args, administrator, **kwargs):
        self.administrator = administrator
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].widget.attrs.update(
            {"class": "form-control", "autocomplete": "new-password"}
        )
        self.fields["new_password2"].widget.attrs.update(
            {"class": "form-control", "autocomplete": "new-password"}
        )

    def clean_administrator_password(self):
        value = self.cleaned_data["administrator_password"]
        if not self.administrator.check_password(value):
            raise forms.ValidationError("Sua senha de administrador está incorreta.")
        return value
