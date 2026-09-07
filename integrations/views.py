from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import transaction as db_transaction
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.access import system_admin_required

from core.models import SecurityEvent
from core.security import record_security_event
from core.security import sensitive_operation_allowed
from core.sorting import apply_sorting
from imports.models import ImportBatch
from imports.models import ImportFile
from imports.models import ImportStatement
from services.importing import reclassify_statement
from services.importing import stage_uploaded_file

from .forms import BankIntegrationForm
from .forms import ReportPeriodForm
from .mercado_pago import MercadoPagoApiError
from .mercado_pago import download_report
from .mercado_pago import list_reports
from .mercado_pago import request_report
from .mercado_pago import test_connection
from .models import BankIntegration


def _integration_queryset(request):
    # Integrações pertencem ao Financeiro OFX, não ao usuário que as criou.
    # Operadores de confiança podem consultar/usar relatórios; somente
    # administradores podem criar ou alterar as credenciais.
    return BankIntegration.objects.select_related(
        "account",
        "account__bank",
        "created_by",
    )


def _get_integration(request, pk):
    return get_object_or_404(
        _integration_queryset(request),
        pk=pk,
    )


def _mark_error(
    integration: BankIntegration,
    exc: Exception,
):
    integration.status = (
        BankIntegration.Status.ERROR
    )
    integration.last_error = str(exc)
    integration.save(
        update_fields=[
            "status",
            "last_error",
            "updated_at",
        ]
    )


@login_required
def integration_list(request):
    integrations = apply_sorting(
        request,
        _integration_queryset(request),
        allowed={
            "name": "name",
            "provider": "provider",
            "account": "account__nickname",
            "auth": "auth_mode",
            "status": "status",
            "sync": "last_sync_at",
        },
        default="name",
    )

    return render(
        request,
        "integrations/list.html",
        {
            "integrations": integrations,
        },
    )


@system_admin_required
def integration_create(request):
    if not sensitive_operation_allowed(
        request
    ):
        messages.error(
            request,
            (
                "Por segurança, credenciais bancárias só podem ser "
                "cadastradas no próprio computador ou através de HTTPS. "
                "Acesse o Financeiro OFX localmente em 127.0.0.1."
            ),
        )
        return redirect(
            "integrations:list"
        )
    if request.method == "POST":
        form = BankIntegrationForm(
            request.POST,
            user=request.user,
        )

        if form.is_valid():
            integration = form.save(
                commit=False
            )
            integration.created_by = (
                request.user
            )
            integration.save()

            record_security_event(
                request,
                event_type=(
                    SecurityEvent.EventType.INTEGRATION_CREATED
                ),
                success=True,
                detail={
                    "integration_id": (
                        integration.pk
                    ),
                    "provider": (
                        integration.provider
                    ),
                    "account_id": (
                        integration.account_id
                    ),
                },
            )

            messages.success(
                request,
                "Integração cadastrada.",
            )
            return redirect(
                "integrations:list"
            )
    else:
        form = BankIntegrationForm(
            user=request.user
        )

    return render(
        request,
        "integrations/form.html",
        {
            "form": form,
            "title": "Nova integração",
        },
    )


@system_admin_required
def integration_update(request, pk):
    if not sensitive_operation_allowed(
        request
    ):
        messages.error(
            request,
            (
                "Por segurança, credenciais bancárias só podem ser "
                "alteradas no próprio computador ou através de HTTPS. "
                "Acesse o Financeiro OFX localmente em 127.0.0.1."
            ),
        )
        return redirect(
            "integrations:list"
        )
    integration = _get_integration(
        request,
        pk,
    )

    if request.method == "POST":
        form = BankIntegrationForm(
            request.POST,
            instance=integration,
            user=request.user,
        )

        if form.is_valid():
            integration = form.save()

            record_security_event(
                request,
                event_type=(
                    SecurityEvent.EventType.INTEGRATION_UPDATED
                ),
                success=True,
                detail={
                    "integration_id": (
                        integration.pk
                    ),
                    "provider": (
                        integration.provider
                    ),
                    "account_id": (
                        integration.account_id
                    ),
                },
            )

            messages.success(
                request,
                "Integração atualizada.",
            )
            return redirect(
                "integrations:list"
            )
    else:
        form = BankIntegrationForm(
            instance=integration,
            user=request.user,
        )

    return render(
        request,
        "integrations/form.html",
        {
            "form": form,
            "title": (
                f"Editar {integration.name}"
            ),
            "integration": integration,
        },
    )


@login_required
@require_POST
def integration_test(request, pk):
    integration = _get_integration(
        request,
        pk,
    )

    try:
        test_connection(integration)
    except MercadoPagoApiError as exc:
        _mark_error(
            integration,
            exc,
        )
        record_security_event(
            request,
            event_type=(
                SecurityEvent.EventType.INTEGRATION_TESTED
            ),
            success=False,
            detail={
                "integration_id": (
                    integration.pk
                ),
                "provider": (
                    integration.provider
                ),
            },
        )
        messages.error(
            request,
            str(exc),
        )
    else:
        integration.status = (
            BankIntegration.Status.OK
        )
        integration.last_error = ""
        integration.save(
            update_fields=[
                "status",
                "last_error",
                "updated_at",
            ]
        )
        record_security_event(
            request,
            event_type=(
                SecurityEvent.EventType.INTEGRATION_TESTED
            ),
            success=True,
            detail={
                "integration_id": (
                    integration.pk
                ),
                "provider": (
                    integration.provider
                ),
            },
        )

        messages.success(
            request,
            (
                "Autenticação aceita pelo Mercado Pago. "
                "A conexão está pronta para gerar relatórios."
            ),
        )

    return redirect(
        "integrations:list"
    )


@login_required
def mercado_pago_reports(request, pk):
    integration = _get_integration(
        request,
        pk,
    )

    if (
        integration.provider
        != BankIntegration.Provider.MERCADO_PAGO
    ):
        messages.error(
            request,
            "Provedor não suportado nesta tela.",
        )
        return redirect(
            "integrations:list"
        )

    period_form = ReportPeriodForm()

    reports = []

    try:
        reports = list_reports(
            integration
        )
    except MercadoPagoApiError as exc:
        _mark_error(
            integration,
            exc,
        )
        messages.warning(
            request,
            (
                "Não foi possível consultar relatórios agora: "
                f"{exc}"
            ),
        )

    reports = sorted(
        reports,
        key=lambda item: (
            item.get("date_created")
            or ""
        ),
        reverse=True,
    )[:50]

    return render(
        request,
        "integrations/mercado_pago_reports.html",
        {
            "integration": integration,
            "period_form": period_form,
            "reports": reports,
        },
    )


@login_required
@require_POST
def mercado_pago_request_report(
    request,
    pk,
):
    integration = _get_integration(
        request,
        pk,
    )
    form = ReportPeriodForm(
        request.POST
    )

    if not form.is_valid():
        messages.error(
            request,
            (
                "Período inválido: "
                + "; ".join(
                    error
                    for errors in form.errors.values()
                    for error in errors
                )
            ),
        )
        return redirect(
            "integrations:mercado-pago-reports",
            pk=integration.pk,
        )

    try:
        request_report(
            integration,
            begin_date=(
                form.cleaned_data[
                    "begin_date"
                ]
            ),
            end_date=(
                form.cleaned_data[
                    "end_date"
                ]
            ),
        )
    except MercadoPagoApiError as exc:
        _mark_error(
            integration,
            exc,
        )
        messages.error(
            request,
            str(exc),
        )
    else:
        record_security_event(
            request,
            event_type=(
                SecurityEvent.EventType.REPORT_REQUESTED
            ),
            success=True,
            detail={
                "integration_id": (
                    integration.pk
                ),
                "begin_date": (
                    form.cleaned_data[
                        "begin_date"
                    ].isoformat()
                ),
                "end_date": (
                    form.cleaned_data[
                        "end_date"
                    ].isoformat()
                ),
            },
        )

        messages.success(
            request,
            (
                "Relatório solicitado ao Mercado Pago. "
                "A geração é assíncrona; atualize esta "
                "tela e importe quando o arquivo aparecer."
            ),
        )

    return redirect(
        "integrations:mercado-pago-reports",
        pk=integration.pk,
    )


@login_required
@require_POST
@db_transaction.atomic
def mercado_pago_import_report(
    request,
    pk,
):
    integration = _get_integration(
        request,
        pk,
    )
    file_name = request.POST.get(
        "file_name",
        "",
    ).strip()

    if not file_name:
        messages.error(
            request,
            "Nome do relatório não informado.",
        )
        return redirect(
            "integrations:mercado-pago-reports",
            pk=integration.pk,
        )

    try:
        available_reports = list_reports(
            integration
        )
        allowed_file_names = {
            (
                report.get(
                    "file_name"
                )
                or ""
            ).strip()
            for report in available_reports
        }

        if file_name not in allowed_file_names:
            raise MercadoPagoApiError(
                (
                    "O relatório informado não está "
                    "disponível para esta integração."
                )
            )

        content = download_report(
            integration,
            file_name=file_name,
        )
    except MercadoPagoApiError as exc:
        _mark_error(
            integration,
            exc,
        )
        messages.error(
            request,
            str(exc),
        )
        return redirect(
            "integrations:mercado-pago-reports",
            pk=integration.pk,
        )

    batch = ImportBatch.objects.create(
        created_by=request.user,
        status=ImportBatch.Status.ANALYZING,
    )

    uploaded = ContentFile(
        content,
        name=file_name,
    )

    import_file = stage_uploaded_file(
        batch=batch,
        uploaded_file=uploaded,
    )

    import_file.source_reference = (
        file_name
    )
    import_file.save(
        update_fields=[
            "source_reference",
            "updated_at",
        ]
    )

    if (
        import_file.status
        == ImportFile.Status.FAILED
    ):
        batch.status = (
            ImportBatch.Status.FAILED
        )
        batch.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        messages.error(
            request,
            import_file.error_message,
        )
        return redirect(
            "imports:batch-detail",
            pk=batch.pk,
        )

    if (
        import_file.status
        != ImportFile.Status.DUPLICATE_FILE
    ):
        statements = (
            ImportStatement.objects.filter(
                import_file=import_file
            )
        )

        for statement in statements:
            statement.matched_bank = (
                integration.account.bank
            )
            statement.matched_account = (
                integration.account
            )
            statement.match_method = (
                ImportStatement.MatchMethod.AUTOMATIC
            )
            statement.save(
                update_fields=[
                    "matched_bank",
                    "matched_account",
                    "match_method",
                ]
            )
            reclassify_statement(
                statement
            )

    batch.status = (
        ImportBatch.Status.ANALYZED
    )
    batch.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    integration.last_sync_at = (
        timezone.now()
    )
    integration.status = (
        BankIntegration.Status.OK
    )
    integration.last_error = ""
    integration.save(
        update_fields=[
            "last_sync_at",
            "status",
            "last_error",
            "updated_at",
        ]
    )

    record_security_event(
        request,
        event_type=(
            SecurityEvent.EventType.REPORT_IMPORTED
        ),
        success=True,
        detail={
            "integration_id": (
                integration.pk
            ),
            "import_batch_id": (
                batch.pk
            ),
            "file_name": (
                file_name
            ),
        },
    )

    messages.success(
        request,
        (
            "Relatório baixado pela API e enviado ao staging. "
            "Revise as movimentações antes de gravar."
        ),
    )

    return redirect(
        "imports:batch-detail",
        pk=batch.pk,
    )
