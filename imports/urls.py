from django.urls import path

from .views import assign_statement_account
from .views import batch_delete
from .views import batch_detail
from .views import batch_edit
from .views import commit_import_batch
from .views import commit_import_item
from .views import create_statement_account
from .views import import_history
from .views import import_upload
from .views import ofx_cleanup
from .views import toggle_import_item_exclusion


app_name = "imports"


urlpatterns = [
    path(
        "",
        import_upload,
        name="upload",
    ),
    path(
        "history/",
        import_history,
        name="history",
    ),
    path(
        "ofx-cleanup/",
        ofx_cleanup,
        name="ofx-cleanup",
    ),
    path(
        "<int:pk>/",
        batch_detail,
        name="batch-detail",
    ),
    path(
        "<int:pk>/edit/",
        batch_edit,
        name="batch-edit",
    ),
    path(
        "<int:pk>/delete/",
        batch_delete,
        name="batch-delete",
    ),
    path(
        "<int:pk>/commit/",
        commit_import_batch,
        name="batch-commit",
    ),
    path(
        "<int:pk>/items/<int:item_pk>/commit/",
        commit_import_item,
        name="item-commit",
    ),
    path(
        "<int:pk>/items/<int:item_pk>/toggle-exclusion/",
        toggle_import_item_exclusion,
        name="item-toggle-exclusion",
    ),
    path(
        "<int:pk>/statements/<int:statement_pk>/assign-account/",
        assign_statement_account,
        name="statement-assign-account",
    ),
    path(
        "<int:pk>/statements/<int:statement_pk>/create-account/",
        create_statement_account,
        name="statement-create-account",
    ),
]
