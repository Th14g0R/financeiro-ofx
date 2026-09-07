from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include
from django.urls import path

from core.views import home
from core.views_security import SecureLoginView
from core.views_security import SecurePasswordChangeView
from core.views_security import SecurePasswordResetConfirmView
from core.views_security import SecurePasswordResetView
from core.views_security import account_profile
from core.views_users import audit_list
from core.views_users import user_create
from core.views_users import user_list
from core.views_users import user_password_reset
from core.views_users import user_update


urlpatterns = [
    path(
        "usuarios/",
        user_list,
        name="system_user_list",
    ),
    path(
        "usuarios/novo/",
        user_create,
        name="system_user_create",
    ),
    path(
        "usuarios/<int:pk>/editar/",
        user_update,
        name="system_user_update",
    ),
    path(
        "usuarios/<int:pk>/senha/",
        user_password_reset,
        name="system_user_password_reset",
    ),
    path(
        "auditoria/",
        audit_list,
        name="audit_list",
    ),
    path(
        "",
        home,
        name="home",
    ),
    path(
        "login/",
        SecureLoginView.as_view(),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
    path(
        "minha-conta/",
        account_profile,
        name="account_profile",
    ),
    path(
        "senha/alterar/",
        SecurePasswordChangeView.as_view(),
        name="password_change",
    ),
    path(
        "senha/alterar/concluido/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name=(
                "registration/password_change_done.html"
            )
        ),
        name="password_change_done",
    ),
    path(
        "senha/recuperar/",
        SecurePasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "senha/recuperar/enviado/",
        auth_views.PasswordResetDoneView.as_view(
            template_name=(
                "registration/password_reset_done.html"
            )
        ),
        name="password_reset_done",
    ),
    path(
        "senha/redefinir/<uidb64>/<token>/",
        SecurePasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "senha/redefinir/concluido/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name=(
                "registration/password_reset_complete.html"
            )
        ),
        name="password_reset_complete",
    ),
    path(
        "finance/",
        include("finance.urls"),
    ),
    path(
        "imports/",
        include("imports.urls"),
    ),
    path(
        "integrations/",
        include("integrations.urls"),
    ),
    path(
        "admin/",
        admin.site.urls,
    ),
]
