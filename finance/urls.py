from django.urls import path

from .ofx_views import OfxPreviewView
from .views import AccountCreateView
from .views import AccountListView
from .views import AccountUpdateView
from .views import BankCreateView
from .views import BankListView
from .views import BankUpdateView
from .views import CounterpartyListView
from .views import counterparty_detail
from .views import counterparty_merge_preview
from .views import counterparty_merge_apply
from .views import counterparty_rebuild
from .views import TransactionCreateView
from .views import TransactionListView
from .views import TransactionUpdateView
from .views import transaction_category_update
from .views import duplicate_analyze
from .views import duplicate_review_bulk
from .views import duplicate_review_detail
from .views import duplicate_review_group
from .views import duplicate_review_list
from .views import account_toggle_active
from .views import bank_toggle_active
from .views import internal_transfer_undo
from .views import internal_transfer_reject
from .views import internal_transfer_list
from .views import internal_transfer_confirm
from .views import internal_transfer_analyze


app_name = "finance"


urlpatterns = [

    path(
        "internal-transfers/",
        internal_transfer_list,
        name="internal-transfer-list",
    ),
    path(
        "internal-transfers/analyze/",
        internal_transfer_analyze,
        name="internal-transfer-analyze",
    ),
    path(
        "internal-transfers/<int:pk>/confirm/",
        internal_transfer_confirm,
        name="internal-transfer-confirm",
    ),
    path(
        "internal-transfers/<int:pk>/reject/",
        internal_transfer_reject,
        name="internal-transfer-reject",
    ),
    path(
        "internal-transfers/<int:pk>/undo/",
        internal_transfer_undo,
        name="internal-transfer-undo",
    ),

path(
    "counterparties/merge/preview/",
    counterparty_merge_preview,
    name="counterparty-merge-preview",
),
path(
    "counterparties/merge/apply/",
    counterparty_merge_apply,
    name="counterparty-merge-apply",
),
    path(
        "counterparties/rebuild/",
        counterparty_rebuild,
        name="counterparty-rebuild",
    ),
    path(
        "counterparties/",
        CounterpartyListView.as_view(),
        name="counterparty-list",
    ),
    path(
        "counterparties/<int:pk>/",
        counterparty_detail,
        name="counterparty-detail",
    ),
    path(
        "banks/",
        BankListView.as_view(),
        name="bank-list",
    ),
    path(
        "banks/new/",
        BankCreateView.as_view(),
        name="bank-create",
    ),
    path(
        "banks/<int:pk>/edit/",
        BankUpdateView.as_view(),
        name="bank-update",
    ),
    path(
        "banks/<int:pk>/toggle-active/",
        bank_toggle_active,
        name="bank-toggle-active",
    ),
    path(
        "accounts/",
        AccountListView.as_view(),
        name="account-list",
    ),
    path(
        "accounts/new/",
        AccountCreateView.as_view(),
        name="account-create",
    ),
    path(
        "accounts/<int:pk>/edit/",
        AccountUpdateView.as_view(),
        name="account-update",
    ),
    path(
        "accounts/<int:pk>/toggle-active/",
        account_toggle_active,
        name="account-toggle-active",
    ),
    path(
        "transactions/",
        TransactionListView.as_view(),
        name="transaction-list",
    ),
    path(
        "transactions/duplicates/",
        duplicate_review_list,
        name="duplicate-review-list",
    ),
    path(
        "transactions/duplicates/analyze/",
        duplicate_analyze,
        name="duplicate-analyze",
    ),
    path(
        "transactions/duplicates/bulk/",
        duplicate_review_bulk,
        name="duplicate-review-bulk",
    ),
    path(
        "transactions/duplicates/group/<int:seed_review_id>/",
        duplicate_review_group,
        name="duplicate-review-group",
    ),
    path(
        "transactions/duplicates/<int:pk>/",
        duplicate_review_detail,
        name="duplicate-review-detail",
    ),
    path(
        "transactions/new/",
        TransactionCreateView.as_view(),
        name="transaction-create",
    ),
    path(
        "transactions/<int:pk>/edit/",
        TransactionUpdateView.as_view(),
        name="transaction-update",
    ),
    path(
        "transactions/<int:pk>/category/",
        transaction_category_update,
        name="transaction-category-update",
    ),
    path(
        "ofx/preview/",
        OfxPreviewView.as_view(),
        name="ofx-preview",
    ),
]
