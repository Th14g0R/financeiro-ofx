from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from core.sorting import apply_sorting
from finance.models import Account
from finance.models import Bank
from imports.forms import CreateAccountFromOfxForm
from imports.forms import ImportReprocessForm
from imports.forms import MultipleOfxUploadForm
from imports.models import ImportBatch
from imports.models import ImportFile
from imports.models import ImportItem
from imports.models import ImportStatement
from services.importing import ImportCommitError
from services.importing import ImportRollbackError
from services.importing import commit_batch
from services.importing import commit_item
from services.importing import create_and_assign_account_from_ofx
from services.importing import delete_batch
from services.importing import reclassify_import_item
from services.importing import reclassify_statement
from services.importing import reprocess_batch
from services.importing import stage_uploaded_file
from services.importing import suggested_account_values
from services.importing.commit import refresh_batch_status


def _batch_queryset_for_user(request):
    queryset = ImportBatch.objects.all()

    if request.user.is_superuser:
        return queryset

    return queryset.filter(created_by=request.user)


def _get_batch(request, pk):
    return get_object_or_404(
        _batch_queryset_for_user(request),
        pk=pk,
    )


@login_required
@require_http_methods(["GET", "POST"])
def import_upload(request):
    if request.method == "POST":
        form = MultipleOfxUploadForm(
            request.POST,
            request.FILES,
        )

        if form.is_valid():
            batch = ImportBatch.objects.create(
                created_by=request.user,
                status=ImportBatch.Status.ANALYZING,
            )

            analyzed_files = 0
            failed_files = 0

            for uploaded_file in form.cleaned_data["files"]:
                import_file = stage_uploaded_file(
                    batch=batch,
                    uploaded_file=uploaded_file,
                )

                if import_file.status == ImportFile.Status.FAILED:
                    failed_files += 1
                else:
                    analyzed_files += 1

            batch.status = (
                ImportBatch.Status.ANALYZED
                if analyzed_files
                else ImportBatch.Status.FAILED
            )
            batch.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            if failed_files:
                messages.warning(
                    request,
                    (
                        f"{failed_files} arquivo(s) apresentaram erro. "
                        "Os demais foram analisados normalmente."
                    ),
                )

            return redirect(
                "imports:batch-detail",
                pk=batch.pk,
            )
    else:
        form = MultipleOfxUploadForm()

    recent_batches = _batch_queryset_for_user(
        request
    ).order_by("-created_at")[:10]

    return render(
        request,
        "imports/upload.html",
        {
            "form": form,
            "recent_batches": recent_batches,
        },
    )


@login_required
def import_history(request):
    batches = (
        _batch_queryset_for_user(request)
        .annotate(
            file_count=Count(
                "files",
                distinct=True,
            )
        )
        .prefetch_related("files")
    )

    batches = apply_sorting(
        request,
        batches,
        allowed={
            "batch": "id",
            "date": "created_at",
            "files": "file_count",
            "status": "status",
            "reprocessed": "reprocessed_at",
        },
        default="date",
        default_direction="desc",
    )

    return render(
        request,
        "imports/history.html",
        {
            "batches": batches,
        },
    )


@login_required
def batch_detail(request, pk):
    batch = _get_batch(request, pk)

    statements_queryset = (
        ImportStatement.objects.select_related(
            "matched_bank",
            "matched_account",
        )
        .prefetch_related(
            Prefetch(
                "items",
                queryset=ImportItem.objects.select_related(
                    "existing_transaction",
                    "imported_transaction",
                ).order_by("sequence"),
            )
        )
        .order_by("sequence")
    )

    files = (
        batch.files.prefetch_related(
            Prefetch(
                "statements",
                queryset=statements_queryset,
            )
        )
        .select_related("duplicate_of")
        .order_by("id")
    )

    items = ImportItem.objects.filter(
        statement__import_file__batch=batch
    )

    counts = {
        "total": items.count(),
        "new": items.filter(
            classification=ImportItem.Classification.NEW
        ).count(),
        "duplicate": items.filter(
            classification=ImportItem.Classification.DUPLICATE
        ).count(),
        "possible_duplicate": items.filter(
            classification=(
                ImportItem.Classification.POSSIBLE_DUPLICATE
            )
        ).count(),
        "divergent": items.filter(
            classification=ImportItem.Classification.DIVERGENT
        ).count(),
        "divergent_pending": items.filter(
            classification=ImportItem.Classification.DIVERGENT,
            commit_status=ImportItem.CommitStatus.PENDING,
        ).count(),
        "unresolved": items.filter(
            classification=(
                ImportItem.Classification.UNRESOLVED_ACCOUNT
            )
        ).count(),
        "invalid": items.filter(
            classification=ImportItem.Classification.INVALID
        ).count(),
        "created": items.filter(
            commit_status=ImportItem.CommitStatus.CREATED
        ).count(),
        "updated": items.filter(
            commit_status=ImportItem.CommitStatus.UPDATED
        ).count(),
        "skipped": items.filter(
            commit_status=ImportItem.CommitStatus.SKIPPED
        ).count(),
        "pending": items.filter(
            commit_status=ImportItem.CommitStatus.PENDING,
            is_excluded=False,
        ).count(),
        "errors": items.exclude(
            commit_error_message=""
        ).filter(
            is_excluded=False,
        ).count(),
        "excluded": items.filter(
            is_excluded=True
        ).count(),
    }

    pending_committable = (
        items.filter(
            commit_status=ImportItem.CommitStatus.PENDING,
            is_excluded=False,
        )
        .exclude(
            classification=(
                ImportItem.Classification.UNRESOLVED_ACCOUNT
            )
        )
        .exists()
    )

    accounts = (
        Account.objects.select_related("bank")
        .filter(is_active=True)
        .order_by("bank__name", "nickname")
    )

    return render(
        request,
        "imports/batch_detail.html",
        {
            "batch": batch,
            "files": files,
            "counts": counts,
            "accounts": accounts,
            "pending_committable": pending_committable,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def batch_edit(request, pk):
    batch = _get_batch(request, pk)

    if request.method == "POST":
        form = ImportReprocessForm(
            request.POST,
            request.FILES,
        )

        if form.is_valid():
            try:
                reprocess_batch(
                    batch=batch,
                    replacement_files=form.cleaned_data["files"],
                )
            except ImportRollbackError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    (
                        "Importação reprocessada. Revise a classificação "
                        "e clique em Gravar movimentações para aplicar "
                        "a versão atualizada."
                    ),
                )
                return redirect(
                    "imports:batch-detail",
                    pk=batch.pk,
                )
    else:
        form = ImportReprocessForm()

    return render(
        request,
        "imports/batch_edit.html",
        {
            "batch": batch,
            "form": form,
            "files": batch.files.order_by("id"),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def batch_delete(request, pk):
    batch = _get_batch(request, pk)

    if request.method == "POST":
        try:
            delete_batch(batch)
        except ImportRollbackError as exc:
            messages.error(request, str(exc))
            return redirect(
                "imports:batch-detail",
                pk=batch.pk,
            )

        messages.success(
            request,
            "Importação excluída e seus efeitos financeiros foram desfeitos.",
        )
        return redirect("imports:history")

    return render(
        request,
        "imports/batch_delete.html",
        {
            "batch": batch,
            "files": batch.files.order_by("id"),
        },
    )


@login_required
@require_POST
def assign_statement_account(request, pk, statement_pk):
    batch = _get_batch(request, pk)

    statement = get_object_or_404(
        ImportStatement.objects.select_related(
            "import_file",
        ),
        pk=statement_pk,
        import_file__batch=batch,
    )

    if statement.items.exclude(
        commit_status=ImportItem.CommitStatus.PENDING
    ).exists():
        messages.error(
            request,
            "Não é possível trocar a conta de um extrato que já foi gravado.",
        )
        return redirect(
            "imports:batch-detail",
            pk=batch.pk,
        )

    account = get_object_or_404(
        Account.objects.select_related("bank"),
        pk=request.POST.get("account"),
        is_active=True,
    )

    statement.matched_bank = account.bank
    statement.matched_account = account
    statement.match_method = ImportStatement.MatchMethod.MANUAL
    statement.save(
        update_fields=[
            "matched_bank",
            "matched_account",
            "match_method",
        ]
    )

    if statement.bank_id and not account.bank.ofx_bank_id:
        conflict = Bank.objects.filter(
            ofx_bank_id=statement.bank_id
        ).exclude(pk=account.bank_id).exists()

        if not conflict:
            account.bank.ofx_bank_id = statement.bank_id
            account.bank.save(
                update_fields=[
                    "ofx_bank_id",
                    "updated_at",
                ]
            )

    if statement.account_id and not account.ofx_account_id:
        conflict = Account.objects.filter(
            bank=account.bank,
            ofx_account_id=statement.account_id,
        ).exclude(pk=account.pk).exists()

        if not conflict:
            account.ofx_account_id = statement.account_id
            account.save(
                update_fields=[
                    "ofx_account_id",
                    "updated_at",
                ]
            )

    reclassify_statement(statement)

    messages.success(
        request,
        (
            f'Extrato relacionado à conta "{account.nickname}". '
            "As movimentações foram reclassificadas."
        ),
    )

    return redirect(
        "imports:batch-detail",
        pk=batch.pk,
    )


@login_required
@require_http_methods(["GET", "POST"])
def create_statement_account(request, pk, statement_pk):
    batch = _get_batch(request, pk)

    statement = get_object_or_404(
        ImportStatement.objects.select_related(
            "import_file",
            "matched_bank",
        ),
        pk=statement_pk,
        import_file__batch=batch,
    )

    if statement.matched_account:
        messages.info(
            request,
            "Este extrato já possui uma conta relacionada.",
        )
        return redirect(
            "imports:batch-detail",
            pk=batch.pk,
        )

    initial = suggested_account_values(statement)

    if request.method == "POST":
        form = CreateAccountFromOfxForm(
            request.POST,
            initial=initial,
        )

        if form.is_valid():
            try:
                account = create_and_assign_account_from_ofx(
                    statement=statement,
                    cleaned_data=form.cleaned_data,
                )
            except ValidationError as exc:
                form.add_error(
                    None,
                    "Não foi possível cadastrar banco/conta: "
                    + "; ".join(exc.messages),
                )
            else:
                messages.success(
                    request,
                    (
                        f'Conta "{account.nickname}" cadastrada e '
                        "vinculada aos dados do OFX."
                    ),
                )

                if form.cleaned_data["commit_after_create"]:
                    unresolved_exists = ImportItem.objects.filter(
                        statement__import_file__batch=batch,
                        classification=(
                            ImportItem.Classification.UNRESOLVED_ACCOUNT
                        ),
                        commit_status=ImportItem.CommitStatus.PENDING,
                    ).exists()

                    divergent_exists = ImportItem.objects.filter(
                        statement__import_file__batch=batch,
                        classification=(
                            ImportItem.Classification.DIVERGENT
                        ),
                        commit_status=ImportItem.CommitStatus.PENDING,
                    ).exists()

                    possible_duplicate_exists = ImportItem.objects.filter(
                        statement__import_file__batch=batch,
                        classification=(
                            ImportItem.Classification.POSSIBLE_DUPLICATE
                        ),
                        commit_status=ImportItem.CommitStatus.PENDING,
                    ).exists()

                    if (
                        not unresolved_exists
                        and not divergent_exists
                        and not possible_duplicate_exists
                    ):
                        try:
                            result = commit_batch(
                                batch=batch,
                                user=request.user,
                            )
                        except ImportCommitError as exc:
                            messages.error(request, str(exc))
                        else:
                            messages.success(
                                request,
                                (
                                    "Movimentações gravadas automaticamente: "
                                    f'{result["created"]} nova(s), '
                                    f'{result["updated"]} atualizada(s), '
                                    f'{result["skipped"]} ignorada(s).'
                                ),
                            )
                    else:
                        messages.info(
                            request,
                            (
                                "A conta foi criada, mas o lote ainda possui "
                                "outras pendências, divergências ou possíveis "
                                "duplicidades sem FITID. Revise-as antes de gravar."
                            ),
                        )

                return redirect(
                    "imports:batch-detail",
                    pk=batch.pk,
                )
    else:
        form = CreateAccountFromOfxForm(
            initial=initial,
        )

    return render(
        request,
        "imports/create_account_from_ofx.html",
        {
            "batch": batch,
            "statement": statement,
            "form": form,
        },
    )


@login_required
@require_POST
def commit_import_item(request, pk, item_pk):
    batch = _get_batch(request, pk)

    item = get_object_or_404(
        ImportItem.objects.select_related(
            "statement",
            "statement__import_file",
            "statement__matched_account",
            "existing_transaction",
        ),
        pk=item_pk,
        statement__import_file__batch=batch,
    )

    if item.commit_status in {
        ImportItem.CommitStatus.CREATED,
        ImportItem.CommitStatus.UPDATED,
    }:
        messages.info(
            request,
            "Esta movimentação já foi aplicada.",
        )
        return redirect(
            "imports:batch-detail",
            pk=batch.pk,
        )

    force_possible = (
        request.POST.get("force_possible_duplicate") == "1"
    )

    result = commit_item(
        item=item,
        user=request.user,
        force_possible_duplicate=force_possible,
    )

    refresh_batch_status(batch)

    status = result["status"]

    if status == "created":
        messages.success(
            request,
            "Movimentação gravada com sucesso.",
        )
    elif status == "updated":
        messages.success(
            request,
            "Movimentação atualizada com sucesso.",
        )
    elif status == "skipped":
        messages.info(
            request,
            "A movimentação foi identificada como duplicada/ignorada.",
        )
    elif status == "pending_review":
        messages.warning(
            request,
            (
                "Sem FITID não é possível provar a duplicidade apenas "
                "pelo valor/data/histórico. Use 'Gravar mesmo assim' "
                "se confirmar que é uma operação legítima."
            ),
        )
    elif status == "unresolved":
        messages.warning(
            request,
            "Relacione uma conta antes de gravar esta movimentação.",
        )
    else:
        item.refresh_from_db()
        messages.error(
            request,
            (
                item.commit_error_message
                or "Falha ao gravar esta movimentação."
            ),
        )

    return redirect(
        "imports:batch-detail",
        pk=batch.pk,
    )


@login_required
@require_POST
def toggle_import_item_exclusion(request, pk, item_pk):
    batch = _get_batch(request, pk)

    item = get_object_or_404(
        ImportItem.objects.select_related(
            "statement",
            "statement__import_file",
            "statement__matched_account",
        ),
        pk=item_pk,
        statement__import_file__batch=batch,
    )

    action = request.POST.get("action", "exclude")

    if action == "restore":
        if item.imported_transaction_id and item.commit_status in {
            ImportItem.CommitStatus.CREATED,
            ImportItem.CommitStatus.UPDATED,
        }:
            messages.error(
                request,
                (
                    "Este lançamento já produziu efeito financeiro. "
                    "Use Editar/reprocessar a importação para alterá-lo."
                ),
            )
            return redirect(
                "imports:batch-detail",
                pk=batch.pk,
            )

        item.is_excluded = False
        item.excluded_at = None
        item.excluded_by = None
        item.commit_status = ImportItem.CommitStatus.PENDING
        item.commit_error_code = ""
        item.commit_error_message = ""
        item.commit_error_details = {}
        item.save(
            update_fields=[
                "is_excluded",
                "excluded_at",
                "excluded_by",
                "commit_status",
                "commit_error_code",
                "commit_error_message",
                "commit_error_details",
            ]
        )

        reclassify_import_item(item)
        refresh_batch_status(batch)

        messages.success(
            request,
            "Movimentação restaurada ao staging para nova tentativa.",
        )

    else:
        if item.commit_status in {
            ImportItem.CommitStatus.CREATED,
            ImportItem.CommitStatus.UPDATED,
        }:
            messages.error(
                request,
                (
                    "Este lançamento já foi gravado. "
                    "Para removê-lo, use Editar/reprocessar a importação."
                ),
            )
            return redirect(
                "imports:batch-detail",
                pk=batch.pk,
            )

        removable_classifications = {
            ImportItem.Classification.DUPLICATE,
            ImportItem.Classification.POSSIBLE_DUPLICATE,
            ImportItem.Classification.INVALID,
            ImportItem.Classification.COMMIT_ERROR,
        }

        if (
            item.classification not in removable_classifications
            and not item.commit_error_message
        ):
            messages.error(
                request,
                (
                    "Esta movimentação foi classificada como válida. "
                    "Use 'Gravar esta' ou a gravação do lote."
                ),
            )
            return redirect(
                "imports:batch-detail",
                pk=batch.pk,
            )

        item.is_excluded = True
        item.excluded_at = timezone.now()
        item.excluded_by = request.user
        item.resolution = ImportItem.Resolution.IGNORE
        item.commit_status = ImportItem.CommitStatus.SKIPPED
        item.save(
            update_fields=[
                "is_excluded",
                "excluded_at",
                "excluded_by",
                "resolution",
                "commit_status",
            ]
        )

        refresh_batch_status(batch)

        messages.success(
            request,
            (
                "Movimentação removida desta importação. "
                "O arquivo OFX original foi preservado para auditoria."
            ),
        )

    return redirect(
        "imports:batch-detail",
        pk=batch.pk,
    )


@login_required
@require_POST
def commit_import_batch(request, pk):
    batch = _get_batch(request, pk)

    divergent_items = ImportItem.objects.filter(
        statement__import_file__batch=batch,
        classification=ImportItem.Classification.DIVERGENT,
        commit_status=ImportItem.CommitStatus.PENDING,
    )

    resolutions = {}

    for item in divergent_items:
        value = request.POST.get(
            f"resolution_{item.pk}",
            ImportItem.Resolution.KEEP_CURRENT,
        )
        resolutions[item.pk] = value

    try:
        result = commit_batch(
            batch=batch,
            user=request.user,
            divergent_resolutions=resolutions,
        )
    except ImportCommitError as exc:
        messages.error(
            request,
            str(exc),
        )
        return redirect(
            "imports:batch-detail",
            pk=batch.pk,
        )

    if result["failed"] or result["pending_review"]:
        messages.warning(
            request,
            (
                "Gravação concluída com revisão pendente: "
                f'{result["created"]} nova(s), '
                f'{result["updated"]} atualizada(s), '
                f'{result["skipped"]} ignorada(s), '
                f'{result["failed"]} com erro e '
                f'{result["pending_review"]} possível(is) duplicidade(s) '
                "sem FITID aguardando decisão."
            ),
        )
    else:
        messages.success(
            request,
            (
                "Gravação concluída: "
                f'{result["created"]} nova(s), '
                f'{result["updated"]} atualizada(s), '
                f'{result["skipped"]} ignorada(s).'
            ),
        )

    if result["unresolved"]:
        messages.warning(
            request,
            (
                f'{result["unresolved"]} movimentação(ões) '
                "continuam pendentes porque a conta ainda não "
                "foi relacionada."
            ),
        )

    return redirect(
        "imports:batch-detail",
        pk=batch.pk,
    )
