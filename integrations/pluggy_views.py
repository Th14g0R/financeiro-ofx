from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.access import system_admin_required
from core.security import sensitive_operation_allowed

from .forms import (
    PluggyAccountMappingForm,
    PluggyCleanupConfirmationForm,
    PluggyConfigurationForm,
    PluggyItemIdForm,
)
from .models import PluggyAccount, PluggyConfiguration, PluggyItem
from .pluggy import MEU_PLUGGY_CONNECTOR_ID
from .pluggy import PluggyApiError
from .pluggy import create_connect_token
from .pluggy import retrieve_connector
from .pluggy import retrieve_item
from .pluggy import test_connection
from .pluggy import trigger_item_update
from .pluggy_cleanup import build_cleanup_preview, cleanup_pluggy_data
from .pluggy_sync import sync_item, upsert_item


def _configuration():
    return PluggyConfiguration.objects.order_by("id").first()


def _require_sensitive(request):
    if sensitive_operation_allowed(request):
        return True
    messages.error(
        request,
        "Por segurança, credenciais e novos consentimentos Pluggy só podem ser administrados em 127.0.0.1 ou HTTPS.",
    )
    return False


@login_required
def pluggy_overview(request):
    configuration = _configuration()
    items = PluggyItem.objects.select_related("configuration", "created_by").prefetch_related("accounts__local_account", "accounts__local_account__bank").all()
    conflicts = sum(
        account.transaction_links.filter(has_conflict=True).count()
        for item in items
        for account in item.accounts.all()
    )
    return render(
        request,
        "integrations/pluggy_overview.html",
        {
            "configuration": configuration,
            "items": items,
            "conflicts": conflicts,
            "item_form": PluggyItemIdForm(),
            "embedded_connect_enabled": settings.PLUGGY_EMBEDDED_CONNECT_ENABLED,
        },
    )


@system_admin_required
def pluggy_configuration(request):
    if not _require_sensitive(request):
        return redirect("integrations:pluggy-overview")
    configuration = _configuration()
    if request.method == "POST":
        form = PluggyConfigurationForm(
            request.POST,
            instance=configuration,
            user=request.user,
        )
        if form.is_valid():
            obj = form.save(commit=False)
            if obj.pk is None:
                obj.created_by = request.user
            obj.save()
            messages.success(request, "Credenciais Pluggy salvas de forma criptografada.")
            return redirect("integrations:pluggy-overview")
    else:
        form = PluggyConfigurationForm(instance=configuration, user=request.user)
    return render(request, "integrations/pluggy_configuration.html", {"form": form, "configuration": configuration})


@system_admin_required
@require_POST
def pluggy_test(request):
    if not _require_sensitive(request):
        return redirect("integrations:pluggy-overview")
    configuration = _configuration()
    if configuration is None:
        messages.error(request, "Configure primeiro o Client ID e Client Secret da Pluggy.")
        return redirect("integrations:pluggy-configuration")
    try:
        test_connection(configuration)
    except PluggyApiError as exc:
        configuration.status = PluggyConfiguration.Status.ERROR
        configuration.last_error = str(exc)
        configuration.save(update_fields=["status", "last_error", "updated_at"])
        messages.error(request, f"Falha ao autenticar na Pluggy: {exc}")
    else:
        configuration.status = PluggyConfiguration.Status.OK
        configuration.last_error = ""
        configuration.save(update_fields=["status", "last_error", "updated_at"])
        messages.success(request, "Autenticação Pluggy validada com sucesso.")
    return redirect("integrations:pluggy-overview")


@system_admin_required
@require_POST
def pluggy_connect_token(request):
    if not settings.PLUGGY_EMBEDDED_CONNECT_ENABLED:
        return JsonResponse(
            {
                "error": (
                    "O Pluggy Connect embutido está desativado. "
                    "Para uso pessoal, autorize o Meu Pluggy em "
                    "Pluggy Dashboard > Development > Demo e registre o Item ID."
                )
            },
            status=409,
        )

    if not _require_sensitive(request):
        return JsonResponse(
            {
                "error": (
                    "Novos consentimentos Pluggy só podem ser iniciados "
                    "em localhost ou HTTPS."
                )
            },
            status=403,
        )

    configuration = _configuration()

    if configuration is None:
        return JsonResponse(
            {
                "error": (
                    "Configure primeiro o Client ID e Client Secret "
                    "da Pluggy."
                )
            },
            status=400,
        )

    item = None
    item_pk = str(
        request.POST.get("item_pk")
        or ""
    ).strip()

    if item_pk:
        try:
            item = PluggyItem.objects.get(
                pk=int(item_pk),
                is_active=True,
            )
        except (
            PluggyItem.DoesNotExist,
            TypeError,
            ValueError,
        ):
            return JsonResponse(
                {
                    "error": (
                        "A conexão Pluggy informada não existe "
                        "ou está inativa."
                    )
                },
                status=404,
            )

        if item.configuration_id != configuration.pk:
            return JsonResponse(
                {
                    "error": (
                        "A conexão pertence a outra configuração Pluggy."
                    )
                },
                status=400,
            )

    try:
        # Validação explícita para dar uma mensagem útil quando a
        # Development Application ainda não tem o Meu Pluggy habilitado.
        retrieve_connector(
            configuration,
            MEU_PLUGGY_CONNECTOR_ID,
        )

        token = create_connect_token(
            configuration,
            client_user_id=(
                f"financeiro-user-{request.user.pk}"
            ),
            item_id=(
                item.item_id
                if item is not None
                else None
            ),
        )
    except PluggyApiError as exc:
        if exc.status_code in {
            401,
            403,
            404,
        }:
            message = (
                "O conector Meu Pluggy (ID 200) não está disponível "
                "para esta Development Application. No Pluggy Dashboard, "
                "habilite o conector Meu Pluggy na customização da aplicação "
                "e confirme que o Client ID/Client Secret usados aqui "
                "pertencem a essa aplicação."
            )
        else:
            message = (
                "Não foi possível iniciar a autorização Meu Pluggy: "
                f"{exc}"
            )

        return JsonResponse(
            {
                "error": message,
            },
            status=502,
        )

    response = JsonResponse(
        {
            "accessToken": token,
            "connectorId": (
                MEU_PLUGGY_CONNECTOR_ID
            ),
            "updateItem": (
                item.item_id
                if item is not None
                else ""
            ),
        }
    )
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, private"
    )
    response.headers["Pragma"] = "no-cache"

    return response


@system_admin_required
@require_POST
def pluggy_capture_item(request):
    if not settings.PLUGGY_EMBEDDED_CONNECT_ENABLED:
        return JsonResponse(
            {
                "error": (
                    "A captura automática do Item ID está desativada junto "
                    "com o Pluggy Connect embutido. Use o registro de Item ID "
                    "na tela de integração."
                )
            },
            status=409,
        )

    if not _require_sensitive(request):
        return JsonResponse(
            {
                "error": (
                    "O registro do consentimento Pluggy só pode ser "
                    "concluído em localhost ou HTTPS."
                )
            },
            status=403,
        )

    configuration = _configuration()

    if configuration is None:
        return JsonResponse(
            {
                "error": "Configure primeiro a Pluggy.",
            },
            status=400,
        )

    form = PluggyItemIdForm(
        {
            "item_id": (
                request.POST.get("item_id")
                or ""
            )
        }
    )

    if not form.is_valid():
        return JsonResponse(
            {
                "error": (
                    "A Pluggy concluiu o fluxo, mas não retornou "
                    "um Item ID válido."
                )
            },
            status=400,
        )

    item_id = str(
        form.cleaned_data["item_id"]
    )

    try:
        payload = retrieve_item(
            configuration,
            item_id,
        )
        item = upsert_item(
            configuration,
            payload,
            user=request.user,
        )
    except (
        PluggyApiError,
        ValueError,
    ) as exc:
        return JsonResponse(
            {
                "error": (
                    "A autorização foi concluída, mas o Financeiro "
                    f"não conseguiu registrar o Item: {exc}"
                )
            },
            status=502,
        )

    request.audit_detail = {
        "pluggy_item_id": item.item_id,
        "connector_id": (
            item.connector_id
            or 0
        ),
    }

    response = JsonResponse(
        {
            "ok": True,
            "itemId": item.item_id,
            "connectorName": (
                item.connector_name
                or "Meu Pluggy"
            ),
        }
    )
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, private"
    )
    return response


@system_admin_required
@require_POST
def pluggy_register_item(request):
    if not _require_sensitive(request):
        return redirect("integrations:pluggy-overview")
    configuration = _configuration()
    if configuration is None:
        messages.error(request, "Configure primeiro a Pluggy.")
        return redirect("integrations:pluggy-configuration")
    form = PluggyItemIdForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Informe um Item ID Pluggy válido.")
        return redirect("integrations:pluggy-overview")
    item_id = str(form.cleaned_data["item_id"])
    try:
        payload = retrieve_item(configuration, item_id)
        item = upsert_item(configuration, payload, user=request.user)
    except PluggyApiError as exc:
        messages.error(request, f"Não foi possível registrar o Item: {exc}")
    else:
        messages.success(request, f"Conexão {item.connector_name or item.item_id} registrada.")
    return redirect("integrations:pluggy-overview")


@login_required
@require_POST
def pluggy_refresh_item(request, pk):
    item = get_object_or_404(PluggyItem, pk=pk, is_active=True)
    try:
        payload = retrieve_item(item.configuration, item.item_id)
        item = upsert_item(item.configuration, payload, user=item.created_by)
    except PluggyApiError as exc:
        item.last_error = str(exc)
        item.save(update_fields=["last_error", "updated_at"])
        messages.error(request, f"Falha ao consultar situação: {exc}")
    else:
        messages.success(request, "Situação da conexão atualizada.")
    return redirect("integrations:pluggy-overview")


@login_required
@require_POST
def pluggy_sync_item(request, pk):
    item = get_object_or_404(PluggyItem, pk=pk, is_active=True)
    try:
        result = sync_item(item, user=request.user)
    except (PluggyApiError, ValueError) as exc:
        item.last_error = str(exc)
        item.save(update_fields=["last_error", "updated_at"])
        messages.error(request, f"Falha na sincronização: {exc}")
    else:
        messages.success(
            request,
            (
                f"Sincronização concluída: {result.accounts} conta(s), "
                f"{result.transactions_created} nova(s) movimentação(ões), "
                f"{result.transactions_existing} já existente(s), "
                f"{result.pending_skipped} pendente(s) ignorada(s), "
                f"{result.conflicts} divergência(s) para revisão."
            ),
        )
    return redirect("integrations:pluggy-overview")


@system_admin_required
@require_POST
def pluggy_trigger_update(request, pk):
    if not _require_sensitive(request):
        return redirect("integrations:pluggy-overview")
    item = get_object_or_404(PluggyItem, pk=pk, is_active=True)

    if item.connector_id == MEU_PLUGGY_CONNECTOR_ID:
        messages.info(
            request,
            (
                "Conexões do Meu Pluggy são mantidas pelo próprio Meu Pluggy. "
                "Renove ou gerencie o consentimento no Meu Pluggy e, depois, "
                "use Atualizar situação e Copiar dados no Financeiro."
            ),
        )
        return redirect(
            "integrations:pluggy-overview"
        )

    try:
        trigger_item_update(item.configuration, item.item_id)
    except PluggyApiError as exc:
        messages.error(request, f"A Pluggy não aceitou a solicitação de atualização: {exc}")
    else:
        messages.success(request, "Atualização solicitada à Pluggy. Aguarde o banco concluir e depois sincronize novamente.")
    return redirect("integrations:pluggy-overview")


@system_admin_required
def pluggy_map_account(request, pk):
    account = get_object_or_404(PluggyAccount.objects.select_related("item", "local_account", "local_account__bank"), pk=pk)
    if request.method == "POST":
        form = PluggyAccountMappingForm(request.POST)
        if form.is_valid():
            account.local_account = form.cleaned_data["local_account"]
            account.save(update_fields=["local_account", "updated_at"])
            messages.success(request, "Vínculo da conta Pluggy atualizado.")
            return redirect("integrations:pluggy-overview")
    else:
        form = PluggyAccountMappingForm(initial={"local_account": account.local_account_id})
    return render(request, "integrations/pluggy_map_account.html", {"account": account, "form": form})


@system_admin_required
def pluggy_cleanup_item(request, pk):
    if not _require_sensitive(request):
        return redirect("integrations:pluggy-overview")

    item = get_object_or_404(
        PluggyItem.objects.select_related("configuration"),
        pk=pk,
    )
    preview = build_cleanup_preview(item=item)

    if request.method == "POST":
        form = PluggyCleanupConfirmationForm(
            request.POST,
            user=request.user,
            allow_remove_item=True,
        )
        if form.is_valid():
            result = cleanup_pluggy_data(
                item_pk=item.pk,
                delete_empty_local_accounts=form.cleaned_data[
                    "delete_empty_local_accounts"
                ],
                remove_item=form.cleaned_data.get("remove_item", False),
            )
            request.audit_detail = {
                "pluggy_cleanup_scope": "item",
                "pluggy_item_id": item.item_id,
                "transactions_deleted": result.transactions_deleted,
                "transactions_preserved": result.transactions_preserved,
                "links_deleted": result.links_deleted,
                "internal_transfers_deleted": result.internal_transfers_deleted,
                "local_accounts_deleted": result.local_accounts_deleted,
                "item_removed": result.item_removed,
            }

            message = (
                "Limpeza concluída: "
                f"{result.transactions_deleted} movimentação(ões) criada(s) pela Pluggy excluída(s), "
                f"{result.links_deleted} vínculo(s) Pluggy removido(s) e "
                f"{result.internal_transfers_deleted} transferência(s) interna(s) derivada(s) removida(s)."
            )
            if result.transactions_preserved:
                message += (
                    f" {result.transactions_preserved} movimentação(ões) existente(s) de outra origem "
                    "foi(ram) preservada(s)."
                )
            if form.cleaned_data["delete_empty_local_accounts"]:
                message += (
                    f" {result.local_accounts_deleted} conta(s) local(is) vazia(s) excluída(s); "
                    f"{result.local_accounts_preserved} preservada(s) por segurança."
                )
            if result.item_removed:
                message += " O Item também foi removido somente do Financeiro OFX."

            messages.success(request, message)
            return redirect("integrations:pluggy-overview")
    else:
        form = PluggyCleanupConfirmationForm(
            user=request.user,
            allow_remove_item=True,
        )

    return render(
        request,
        "integrations/pluggy_cleanup_confirm.html",
        {
            "item": item,
            "pluggy_account": None,
            "preview": preview,
            "form": form,
            "scope_type": "item",
        },
    )


@system_admin_required
def pluggy_cleanup_account(request, pk):
    if not _require_sensitive(request):
        return redirect("integrations:pluggy-overview")

    pluggy_account = get_object_or_404(
        PluggyAccount.objects.select_related(
            "item",
            "item__configuration",
            "local_account",
            "local_account__bank",
        ),
        pk=pk,
    )
    item = pluggy_account.item
    preview = build_cleanup_preview(
        item=item,
        pluggy_account=pluggy_account,
    )

    if request.method == "POST":
        form = PluggyCleanupConfirmationForm(
            request.POST,
            user=request.user,
            allow_remove_item=False,
        )
        if form.is_valid():
            result = cleanup_pluggy_data(
                item_pk=item.pk,
                pluggy_account_pk=pluggy_account.pk,
                delete_empty_local_accounts=form.cleaned_data[
                    "delete_empty_local_accounts"
                ],
            )
            request.audit_detail = {
                "pluggy_cleanup_scope": "account",
                "pluggy_item_id": item.item_id,
                "pluggy_account_id": pluggy_account.pluggy_account_id,
                "transactions_deleted": result.transactions_deleted,
                "transactions_preserved": result.transactions_preserved,
                "links_deleted": result.links_deleted,
                "internal_transfers_deleted": result.internal_transfers_deleted,
                "local_accounts_deleted": result.local_accounts_deleted,
            }

            message = (
                "Limpeza da conta concluída: "
                f"{result.transactions_deleted} movimentação(ões) criada(s) pela Pluggy excluída(s) e "
                f"{result.links_deleted} vínculo(s) removido(s)."
            )
            if result.transactions_preserved:
                message += (
                    f" {result.transactions_preserved} movimentação(ões) de outra origem "
                    "foi(ram) preservada(s)."
                )
            if form.cleaned_data["delete_empty_local_accounts"]:
                message += (
                    f" {result.local_accounts_deleted} conta local vazia excluída; "
                    f"{result.local_accounts_preserved} preservada(s) por segurança."
                )

            messages.success(request, message)
            return redirect("integrations:pluggy-overview")
    else:
        form = PluggyCleanupConfirmationForm(
            user=request.user,
            allow_remove_item=False,
        )

    return render(
        request,
        "integrations/pluggy_cleanup_confirm.html",
        {
            "item": item,
            "pluggy_account": pluggy_account,
            "preview": preview,
            "form": form,
            "scope_type": "account",
        },
    )
