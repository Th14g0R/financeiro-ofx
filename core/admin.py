from django.contrib import admin

from .models import AuditEvent
from .models import LoginThrottleBucket
from .models import UserAccessProfile
from .models import SecurityEvent


@admin.register(LoginThrottleBucket)
class LoginThrottleBucketAdmin(
    admin.ModelAdmin
):
    list_display = (
        "scope",
        "failures",
        "locked_until",
        "updated_at",
    )
    list_filter = (
        "scope",
    )
    readonly_fields = (
        "scope",
        "key_hash",
        "failures",
        "window_started_at",
        "locked_until",
        "updated_at",
    )

    def has_add_permission(
        self,
        request,
    ):
        return False


@admin.register(SecurityEvent)
class SecurityEventAdmin(
    admin.ModelAdmin
):
    list_display = (
        "created_at",
        "event_type",
        "user",
        "success",
    )
    list_filter = (
        "event_type",
        "success",
        "created_at",
    )
    search_fields = (
        "user__username",
    )
    readonly_fields = (
        "event_type",
        "user",
        "success",
        "ip_hash",
        "detail",
        "created_at",
    )

    def has_add_permission(
        self,
        request,
    ):
        return False

    def has_change_permission(
        self,
        request,
        obj=None,
    ):
        return False

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        return False


@admin.register(UserAccessProfile)
class UserAccessProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "updated_at")
    list_filter = ("role",)
    search_fields = ("user__username", "user__email")


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "method", "status_code", "success")
    list_filter = ("success", "method", "created_at")
    search_fields = ("actor__username", "action", "path", "request_id")
    readonly_fields = ("actor", "action", "method", "path", "status_code", "success", "request_id", "ip_hash", "detail", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
