from django.contrib import admin

from .models import BankIntegration


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
