from django.contrib import admin

from .models import ImportBatch
from .models import ImportEffect
from .models import ImportFile
from .models import ImportItem
from .models import ImportStatement


class ImportFileInline(admin.TabularInline):
    model = ImportFile
    extra = 0
    show_change_link = True
    fields = (
        "original_name",
        "file_hash",
        "status",
        "source_format",
        "provider",
        "created_at",
    )
    readonly_fields = fields


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_by",
        "status",
        "created_at",
        "committed_at",
        "reprocessed_at",
        "cleanup_archived_at",
    )
    list_filter = (
        "status",
        "created_at",
    )
    search_fields = (
        "id",
        "created_by__username",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "committed_at",
        "reprocessed_at",
        "cleanup_archived_at",
        "cleanup_archived_by",
        "cleanup_note",
    )
    inlines = (ImportFileInline,)


@admin.register(ImportFile)
class ImportFileAdmin(admin.ModelAdmin):
    list_display = (
        "original_name",
        "batch",
        "status",
        "source_format",
        "provider",
        "file_size",
        "created_at",
    )
    list_filter = (
        "status",
        "created_at",
    )
    search_fields = (
        "original_name",
        "file_hash",
    )
    readonly_fields = (
        "file_hash",
        "file_size",
        "created_at",
        "updated_at",
    )


@admin.register(ImportStatement)
class ImportStatementAdmin(admin.ModelAdmin):
    list_display = (
        "import_file",
        "sequence",
        "bank_id",
        "account_id",
        "matched_account",
        "match_method",
    )
    list_filter = (
        "match_method",
        "matched_bank",
    )
    search_fields = (
        "import_file__original_name",
        "bank_id",
        "account_id",
        "matched_account__nickname",
    )


@admin.register(ImportItem)
class ImportItemAdmin(admin.ModelAdmin):
    list_display = (
        "posted_at",
        "fitid",
        "amount",
        "direction",
        "classification",
        "resolution",
        "commit_status",
        "is_excluded",
        "commit_error_code",
    )
    list_filter = (
        "classification",
        "resolution",
        "commit_status",
        "direction",
        "is_excluded",
        "commit_error_code",
    )
    search_fields = (
        "fitid",
        "raw_description",
        "fingerprint",
    )
    readonly_fields = (
        "fingerprint",
        "divergence_fields",
        "raw_data",
        "commit_error_details",
        "excluded_at",
        "excluded_by",
    )



@admin.register(ImportEffect)
class ImportEffectAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "import_item",
        "transaction",
        "action",
        "applied_at",
        "reverted_at",
    )
    list_filter = (
        "action",
        "applied_at",
        "reverted_at",
    )
    search_fields = (
        "import_item__fitid",
        "transaction__fitid",
        "transaction__raw_description",
    )
    readonly_fields = (
        "before_data",
        "after_data",
        "cleanup_data",
        "applied_at",
        "reverted_at",
    )
