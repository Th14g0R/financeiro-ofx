from django.urls import path

from .views import integration_create
from .views import integration_list
from .views import integration_test
from .views import integration_update
from .views import mercado_pago_import_report
from .views import mercado_pago_reports
from .views import mercado_pago_request_report
from .pluggy_views import pluggy_cleanup_account
from .pluggy_views import pluggy_cleanup_item
from .pluggy_views import pluggy_configuration
from .pluggy_views import pluggy_capture_item
from .pluggy_views import pluggy_connect_token
from .pluggy_views import pluggy_map_account
from .pluggy_views import pluggy_overview
from .pluggy_views import pluggy_refresh_item
from .pluggy_views import pluggy_register_item
from .pluggy_views import pluggy_sync_item
from .pluggy_views import pluggy_test
from .pluggy_views import pluggy_trigger_update


app_name = "integrations"


urlpatterns = [
    path("pluggy/", pluggy_overview, name="pluggy-overview"),
    path("pluggy/configurar/", pluggy_configuration, name="pluggy-configuration"),
    path("pluggy/testar/", pluggy_test, name="pluggy-test"),
    path(
        "pluggy/connect-token/",
        pluggy_connect_token,
        name="pluggy-connect-token",
    ),
    path(
        "pluggy/item/capturar/",
        pluggy_capture_item,
        name="pluggy-capture-item",
    ),
    path("pluggy/item/registrar/", pluggy_register_item, name="pluggy-register-item"),
    path("pluggy/item/<int:pk>/situacao/", pluggy_refresh_item, name="pluggy-refresh-item"),
    path("pluggy/item/<int:pk>/sincronizar/", pluggy_sync_item, name="pluggy-sync-item"),
    path("pluggy/item/<int:pk>/excluir-dados/", pluggy_cleanup_item, name="pluggy-cleanup-item"),
    path("pluggy/conta/<int:pk>/excluir-dados/", pluggy_cleanup_account, name="pluggy-cleanup-account"),
    path("pluggy/item/<int:pk>/solicitar-atualizacao/", pluggy_trigger_update, name="pluggy-trigger-update"),
    path("pluggy/conta/<int:pk>/vincular/", pluggy_map_account, name="pluggy-map-account"),
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
