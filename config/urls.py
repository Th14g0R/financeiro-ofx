from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include
from django.urls import path

from core.views import home
from core.views_security import SecureLoginView
from core.views_security import SecurePasswordResetConfirmView
from core.views_security import SecurePasswordResetView
from core.views_security import account_profile


urlpatterns = [
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
        auth_views.PasswordChangeView.as_view(
            template_name=(
                "registration/password_change_form.html"
            ),
            success_url=(
                "/senha/alterar/concluido/"
            ),
        ),
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
