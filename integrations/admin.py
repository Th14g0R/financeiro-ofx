from django.contrib import admin

from .models import BankIntegration
from .models import PluggyAccount, PluggyConfiguration, PluggyItem, PluggyTransactionLink


@admin.register(BankIntegration)
class BankIntegrationAdmin(
    admin.ModelAdmin
):
    list_display = (
        "name",
        "provider",
        "account",
        "auth_mode",
        "status",
        "is_active",
        "last_sync_at",
    )
    list_filter = (
        "provider",
        "auth_mode",
        "status",
        "is_active",
    )
    search_fields = (
        "name",
        "account__nickname",
        "account__bank__name",
        "client_id",
    )
    readonly_fields = (
        "client_secret_encrypted",
        "access_token_encrypted",
        "access_token_expires_at",
        "last_sync_at",
        "last_error",
        "created_at",
        "updated_at",
    )



@admin.register(PluggyConfiguration)
class PluggyConfigurationAdmin(admin.ModelAdmin):
    list_display = ("name", "client_id", "status", "is_active", "updated_at")
    readonly_fields = ("client_secret_encrypted", "api_key_encrypted", "api_key_expires_at", "last_error", "created_at", "updated_at")


@admin.register(PluggyItem)
class PluggyItemAdmin(admin.ModelAdmin):
    list_display = ("connector_name", "item_id", "status", "execution_status", "last_sync_at", "is_active")
    readonly_fields = ("identity_data", "last_sync_summary", "status_detail", "last_sync_at", "last_updated_at", "created_at", "updated_at")
    search_fields = ("connector_name", "item_id", "client_user_id")
    list_filter = ("status", "execution_status", "is_active")


@admin.register(PluggyAccount)
class PluggyAccountAdmin(admin.ModelAdmin):
    list_display = ("name", "item", "detected_bank_name", "remote_type", "subtype", "local_account", "match_status", "balance", "is_active")
    search_fields = ("name", "masked_number", "pluggy_account_id")
    list_filter = ("remote_type", "subtype", "match_status", "is_active")


@admin.register(PluggyTransactionLink)
class PluggyTransactionLinkAdmin(admin.ModelAdmin):
    list_display = ("remote_transaction_id", "pluggy_account", "provider_id", "transaction", "has_conflict", "last_seen_at")
    search_fields = ("remote_transaction_id", "provider_id")
    list_filter = ("has_conflict",)
