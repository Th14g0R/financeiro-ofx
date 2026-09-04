from django.urls import path

from .views import integration_create
from .views import integration_list
from .views import integration_test
from .views import integration_update
from .views import mercado_pago_import_report
from .views import mercado_pago_reports
from .views import mercado_pago_request_report


app_name = "integrations"


urlpatterns = [
    path(
        "",
        integration_list,
        name="list",
    ),
    path(
        "new/",
        integration_create,
        name="create",
    ),
    path(
        "<int:pk>/edit/",
        integration_update,
        name="update",
    ),
    path(
        "<int:pk>/test/",
        integration_test,
        name="test",
    ),
    path(
        "<int:pk>/mercado-pago/reports/",
        mercado_pago_reports,
        name="mercado-pago-reports",
    ),
    path(
        "<int:pk>/mercado-pago/request/",
        mercado_pago_request_report,
        name="mercado-pago-request-report",
    ),
    path(
        "<int:pk>/mercado-pago/import/",
        mercado_pago_import_report,
        name="mercado-pago-import-report",
    ),
]
