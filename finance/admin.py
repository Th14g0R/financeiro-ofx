from django.contrib import admin

from .models import Account
from .models import Bank
from .models import Category
from .models import Counterparty
from .models import CounterpartyAlias
from .models import InternalTransfer
from .models import Transaction


@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "ofx_bank_id",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active",)
    search_fields = (
        "name",
        "code",
        "ofx_bank_id",
    )
    ordering = ("name",)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = (
        "nickname",
        "bank",
        "branch",
        "formatted_number",
        "account_type",
        "currency",
        "ofx_account_id",
        "is_own_account",
        "is_active",
    )
    list_filter = (
        "is_active",
        "is_own_account",
        "account_type",
        "bank",
    )
    search_fields = (
        "nickname",
        "bank__name",
        "branch",
        "number",
        "ofx_account_id",
    )
    autocomplete_fields = ("bank",)
    ordering = (
        "bank__name",
        "nickname",
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category_type",
        "is_active",
        "updated_at",
    )
    list_filter = (
        "is_active",
        "category_type",
    )
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "posted_at",
        "account",
        "direction",
        "amount",
        "transaction_type",
        "source_type",
        "counterparty",
        "category",
        "fitid",
    )
    list_filter = (
        "direction",
        "transaction_type",
        "source_type",
        "account__bank",
        "account",
        "category",
    )
    search_fields = (
        "raw_description",
        "normalized_description",
        "document",
        "reference",
        "fitid",
        "fingerprint",
        "account__nickname",
        "account__bank__name",
    )
    autocomplete_fields = (
        "account",
        "counterparty",
        "category",
        "created_by",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    ordering = (
        "-posted_at",
        "-id",
    )



class CounterpartyAliasInline(admin.TabularInline):
    model = CounterpartyAlias
    extra = 0


@admin.register(Counterparty)
class CounterpartyAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "kind",
        "tax_id",
        "is_active",
        "updated_at",
    )
    list_filter = (
        "kind",
        "is_active",
    )
    search_fields = (
        "display_name",
        "normalized_name",
        "tax_id",
        "aliases__alias",
        "aliases__normalized_alias",
    )
    inlines = (CounterpartyAliasInline,)


@admin.register(CounterpartyAlias)
class CounterpartyAliasAdmin(admin.ModelAdmin):
    list_display = (
        "alias",
        "counterparty",
        "alias_type",
        "created_at",
    )
    list_filter = ("alias_type",)
    search_fields = (
        "alias",
        "normalized_alias",
        "counterparty__display_name",
    )



@admin.register(InternalTransfer)
class InternalTransferAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "status",
        "source_account",
        "target_account",
        "amount",
        "confidence",
        "match_method",
        "reviewed_by",
    )
    list_filter = (
        "status",
        "match_method",
        "debit_transaction__account__bank",
        "credit_transaction__account__bank",
    )
    search_fields = (
        "debit_transaction__raw_description",
        "credit_transaction__raw_description",
        "debit_transaction__fitid",
        "credit_transaction__fitid",
        "debit_transaction__account__nickname",
        "credit_transaction__account__nickname",
    )
    autocomplete_fields = (
        "debit_transaction",
        "credit_transaction",
        "reviewed_by",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
