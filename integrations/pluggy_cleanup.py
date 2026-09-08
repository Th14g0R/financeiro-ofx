from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable

from django.db import transaction as db_transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError

from finance.models import Account, InternalTransfer, Transaction

from .models import PluggyAccount, PluggyItem, PluggyTransactionLink


@dataclass(frozen=True, slots=True)
class AccountCleanupCandidate:
    account_id: int
    label: str
    can_delete: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PluggyCleanupPreview:
    scope_label: str
    pluggy_accounts: int
    links: int
    transactions_to_delete: int
    transactions_preserved: int
    internal_transfers_to_delete: int
    local_accounts: tuple[AccountCleanupCandidate, ...]

    @property
    def deletable_local_accounts(self) -> int:
        return sum(1 for account in self.local_accounts if account.can_delete)

    @property
    def blocked_local_accounts(self) -> int:
        return sum(1 for account in self.local_accounts if not account.can_delete)


@dataclass(frozen=True, slots=True)
class PluggyCleanupResult:
    transactions_deleted: int
    transactions_preserved: int
    links_deleted: int
    internal_transfers_deleted: int
    local_accounts_deleted: int
    local_accounts_preserved: int
    item_removed: bool


def _is_pluggy_owned_transaction(transaction: Transaction) -> bool:
    """
    Return True only for movements whose provenance clearly points to the
    Pluggy importer.

    A PluggyTransactionLink by itself is not enough: an existing OFX/PDF/manual
    movement can be linked during deduplication and must never be deleted by a
    Pluggy cleanup.
    """
    raw_data = transaction.raw_data if isinstance(transaction.raw_data, dict) else {}
    provider = str(raw_data.get("provider") or "").strip().upper()
    fitid = str(transaction.fitid or "").strip().upper()

    return (
        transaction.source_type == Transaction.SourceType.API
        and provider == "PLUGGY"
        and (
            fitid.startswith("PLUGGY:")
            or fitid.startswith("PLUGGY-PROVIDER:")
        )
    )


def _scope_accounts(
    *,
    item: PluggyItem,
    pluggy_account: PluggyAccount | None = None,
):
    queryset = PluggyAccount.objects.filter(item=item)
    if pluggy_account is not None:
        queryset = queryset.filter(pk=pluggy_account.pk)
    return queryset


def _owned_transaction_ids_for_links(
    links: Iterable[PluggyTransactionLink],
    *,
    scope_link_ids: set[int],
) -> tuple[set[int], set[int]]:
    candidate_transactions: dict[int, Transaction] = {}

    for link in links:
        if link.transaction_id and link.transaction is not None:
            candidate_transactions.setdefault(link.transaction_id, link.transaction)

    if not candidate_transactions:
        return set(), set()

    outside_scope_ids = set(
        PluggyTransactionLink.objects.filter(
            transaction_id__in=candidate_transactions.keys()
        )
        .exclude(pk__in=scope_link_ids)
        .values_list("transaction_id", flat=True)
    )

    delete_ids: set[int] = set()
    preserve_ids: set[int] = set()

    for transaction_id, transaction in candidate_transactions.items():
        if (
            transaction_id not in outside_scope_ids
            and _is_pluggy_owned_transaction(transaction)
        ):
            delete_ids.add(transaction_id)
        else:
            preserve_ids.add(transaction_id)

    return delete_ids, preserve_ids


def _account_label(account: Account) -> str:
    return (
        f"{account.bank.name} · {account.nickname} · "
        f"{account.branch or 's/ag.'}/{account.formatted_number}"
    )


def _local_account_candidates(
    *,
    scope_accounts: list[PluggyAccount],
    transaction_delete_ids: set[int],
) -> tuple[AccountCleanupCandidate, ...]:
    scope_pluggy_account_ids = {account.pk for account in scope_accounts}
    local_account_ids = {
        account.local_account_id
        for account in scope_accounts
        if account.local_account_id
    }

    candidates: list[AccountCleanupCandidate] = []

    for local_account in (
        Account.objects.select_related("bank")
        .filter(pk__in=local_account_ids)
        .order_by("bank__name", "nickname", "id")
    ):
        reasons: list[str] = []

        related_scope_accounts = [
            account
            for account in scope_accounts
            if account.local_account_id == local_account.pk
        ]
        expected_ofx_ids = {
            f"PLUGGY:{account.pluggy_account_id}"
            for account in related_scope_accounts
        }
        created_near_pluggy_account = any(
            abs(local_account.created_at - account.created_at) <= timedelta(minutes=1)
            for account in related_scope_accounts
        )
        has_pluggy_creation_signature = (
            local_account.ofx_account_id in expected_ofx_ids
            and created_near_pluggy_account
        )

        if not has_pluggy_creation_signature:
            reasons.append(
                "não há evidência suficiente de que a conta local foi criada pela Pluggy"
            )

        if (
            local_account.transactions.exclude(pk__in=transaction_delete_ids)
            .exists()
        ):
            reasons.append("possui movimentações que não serão excluídas")

        if local_account.import_statements.exists():
            reasons.append("é utilizada por importação OFX/PDF")

        if local_account.bank_integrations.exists():
            reasons.append("é utilizada por outra integração bancária")

        if (
            local_account.pluggy_accounts.exclude(pk__in=scope_pluggy_account_ids)
            .exists()
        ):
            reasons.append("também está vinculada a outra conta Pluggy")

        candidates.append(
            AccountCleanupCandidate(
                account_id=local_account.pk,
                label=_account_label(local_account),
                can_delete=not reasons,
                reasons=tuple(reasons),
            )
        )

    return tuple(candidates)


def build_cleanup_preview(
    *,
    item: PluggyItem,
    pluggy_account: PluggyAccount | None = None,
) -> PluggyCleanupPreview:
    scope_accounts = list(
        _scope_accounts(item=item, pluggy_account=pluggy_account)
        .select_related("local_account", "local_account__bank")
        .order_by("id")
    )
    account_ids = [account.pk for account in scope_accounts]

    links = list(
        PluggyTransactionLink.objects.filter(pluggy_account_id__in=account_ids)
        .select_related("transaction")
        .order_by("id")
    )
    scope_link_ids = {link.pk for link in links}
    delete_ids, preserve_ids = _owned_transaction_ids_for_links(
        links,
        scope_link_ids=scope_link_ids,
    )

    internal_transfer_count = 0
    if delete_ids:
        internal_transfer_count = (
            InternalTransfer.objects.filter(
                Q(debit_transaction_id__in=delete_ids)
                | Q(credit_transaction_id__in=delete_ids)
            )
            .distinct()
            .count()
        )

    if pluggy_account is None:
        scope_label = item.connector_name or item.item_id
    else:
        scope_label = (
            f"{item.connector_name or item.item_id} · "
            f"{pluggy_account.name or pluggy_account.masked_number or pluggy_account.pluggy_account_id}"
        )

    return PluggyCleanupPreview(
        scope_label=scope_label,
        pluggy_accounts=len(scope_accounts),
        links=len(links),
        transactions_to_delete=len(delete_ids),
        transactions_preserved=len(preserve_ids),
        internal_transfers_to_delete=internal_transfer_count,
        local_accounts=_local_account_candidates(
            scope_accounts=scope_accounts,
            transaction_delete_ids=delete_ids,
        ),
    )


@db_transaction.atomic
def cleanup_pluggy_data(
    *,
    item_pk: int,
    pluggy_account_pk: int | None = None,
    delete_empty_local_accounts: bool = False,
    remove_item: bool = False,
) -> PluggyCleanupResult:
    item = (
        PluggyItem.objects.select_for_update()
        .select_related("configuration")
        .get(pk=item_pk)
    )

    pluggy_account = None
    if pluggy_account_pk is not None:
        pluggy_account = (
            PluggyAccount.objects.select_for_update()
            .select_related("item")
            .get(pk=pluggy_account_pk, item=item)
        )
        # Removing the entire Item from an account-scoped cleanup would be
        # surprising and could remove unrelated accounts from the same Item.
        remove_item = False

    scope_accounts = list(
        _scope_accounts(item=item, pluggy_account=pluggy_account)
        .select_for_update()
        .select_related("local_account", "local_account__bank")
        .order_by("id")
    )
    scope_account_ids = [account.pk for account in scope_accounts]

    links = list(
        PluggyTransactionLink.objects.select_for_update()
        .filter(pluggy_account_id__in=scope_account_ids)
        .select_related("transaction")
        .order_by("id")
    )
    scope_link_ids = {link.pk for link in links}
    transaction_delete_ids, transaction_preserve_ids = (
        _owned_transaction_ids_for_links(
            links,
            scope_link_ids=scope_link_ids,
        )
    )

    account_candidates = _local_account_candidates(
        scope_accounts=scope_accounts,
        transaction_delete_ids=transaction_delete_ids,
    )

    internal_transfer_count = 0
    if transaction_delete_ids:
        internal_transfer_count = (
            InternalTransfer.objects.filter(
                Q(debit_transaction_id__in=transaction_delete_ids)
                | Q(credit_transaction_id__in=transaction_delete_ids)
            )
            .distinct()
            .count()
        )

    if transaction_delete_ids:
        Transaction.objects.filter(pk__in=transaction_delete_ids).delete()

    if scope_link_ids:
        PluggyTransactionLink.objects.filter(pk__in=scope_link_ids).delete()

    deleted_local_accounts = 0
    preserved_local_accounts = len(account_candidates)

    if delete_empty_local_accounts:
        preserved_local_accounts = 0
        for candidate in account_candidates:
            if not candidate.can_delete:
                preserved_local_accounts += 1
                continue

            try:
                local_account = Account.objects.select_for_update().get(
                    pk=candidate.account_id
                )
            except Account.DoesNotExist:
                continue

            # Re-check the destructive conditions inside the same transaction,
            # immediately before deletion. This protects against stale previews.
            if (
                local_account.transactions.exists()
                or local_account.import_statements.exists()
                or local_account.bank_integrations.exists()
                or local_account.pluggy_accounts.exclude(
                    pk__in=scope_account_ids
                ).exists()
            ):
                preserved_local_accounts += 1
                continue

            try:
                local_account.delete()
            except ProtectedError:
                preserved_local_accounts += 1
            else:
                deleted_local_accounts += 1

    item_removed = False
    if remove_item:
        item.delete()
        item_removed = True
    elif pluggy_account is None:
        # The remote Item remains registered and can be copied again later,
        # but locally there is no longer a completed copy of this Item.
        item.last_sync_at = None
        item.last_error = ""
        item.save(update_fields=["last_sync_at", "last_error", "updated_at"])

    return PluggyCleanupResult(
        transactions_deleted=len(transaction_delete_ids),
        transactions_preserved=len(transaction_preserve_ids),
        links_deleted=len(scope_link_ids),
        internal_transfers_deleted=internal_transfer_count,
        local_accounts_deleted=deleted_local_accounts,
        local_accounts_preserved=preserved_local_accounts,
        item_removed=item_removed,
    )
