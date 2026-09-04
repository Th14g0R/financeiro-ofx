from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include
from django.urls import path

from core.views import home
from core.views_security import SecureLoginView


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
