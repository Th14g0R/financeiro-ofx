from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import update_session_auth_hash
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render

from .access import system_admin_required
from .forms import ManagedUserCreateForm
from .forms import ManagedUserPasswordResetForm
from .forms import ManagedUserUpdateForm
from .models import AuditEvent
from .models import UserAccessProfile
from .security import sensitive_operation_allowed
from .session_security import invalidate_user_sessions


def _ensure_profile(user):
    profile, _created = UserAccessProfile.objects.get_or_create(
        user=user,
        defaults={
            "role": (
                UserAccessProfile.Role.ADMIN
                if (user.is_superuser or user.is_staff)
                else UserAccessProfile.Role.OPERATOR
            )
        },
    )
    return profile


def _active_admin_count(*, exclude_user_id=None):
    queryset = UserAccessProfile.objects.filter(
        role=UserAccessProfile.Role.ADMIN,
        user__is_active=True,
    )
    if exclude_user_id is not None:
        queryset = queryset.exclude(user_id=exclude_user_id)
    return queryset.count()


def _sensitive_user_management_allowed(request):
    if sensitive_operation_allowed(request):
        return True

    messages.error(
        request,
        (
            "Por segurança, cadastro, alteração de perfil e "
            "redefinição administrativa de senha só podem ser "
            "realizados neste computador ou através de HTTPS."
        ),
    )
    return False


@system_admin_required
def user_list(request):
    query = (request.GET.get("q", "") or "").strip()
    status = (request.GET.get("status", "active") or "active").strip()

    user_model = get_user_model()
    users = user_model._default_manager.select_related("access_profile").order_by(
        "username"
    )

    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
        )

    if status == "active":
        users = users.filter(is_active=True)
    elif status == "inactive":
        users = users.filter(is_active=False)

    users = list(users)
    for user in users:
        profile = _ensure_profile(user)
        user.system_access_role = profile.role

    return render(
        request,
        "core/user_list.html",
        {
            "users": users,
            "query": query,
            "status_filter": status,
        },
    )


@system_admin_required
@transaction.atomic
def user_create(request):
    if not _sensitive_user_management_allowed(request):
        return redirect("system_user_list")

    if request.method == "POST":
        form = ManagedUserCreateForm(request.POST, administrator=request.user)
        if form.is_valid():
            user = form.save()
            request.audit_detail = {
                "target_user_id": user.pk,
                "target_role": user.access_profile.role,
                "target_active": user.is_active,
            }
            messages.success(
                request,
                (
                    f"Usuário {user.get_username()} criado. "
                    "As operações realizadas por esta conta passarão "
                    "a ser registradas na auditoria."
                ),
            )
            return redirect("system_user_list")
    else:
        form = ManagedUserCreateForm(administrator=request.user)

    return render(
        request,
        "core/user_form.html",
        {
            "form": form,
            "page_heading": "Novo usuário",
            "editing_user": None,
        },
    )


@system_admin_required
@transaction.atomic
def user_update(request, pk):
    if not _sensitive_user_management_allowed(request):
        return redirect("system_user_list")

    user_model = get_user_model()
    target = get_object_or_404(user_model, pk=pk)
    current_profile = _ensure_profile(target)
    was_active = target.is_active

    if request.method == "POST":
        form = ManagedUserUpdateForm(
            request.POST,
            user_obj=target,
            administrator=request.user,
        )
        if form.is_valid():
            new_role = form.cleaned_data["role"]
            new_active = form.cleaned_data["is_active"]

            if target.pk == request.user.pk and not new_active:
                form.add_error(
                    "is_active",
                    "Você não pode desativar a própria conta.",
                )
            elif target.is_superuser and new_role != UserAccessProfile.Role.ADMIN:
                form.add_error(
                    "role",
                    "Uma conta superusuária permanece administradora.",
                )
            elif (
                current_profile.role == UserAccessProfile.Role.ADMIN
                and (
                    new_role != UserAccessProfile.Role.ADMIN
                    or not new_active
                )
                and _active_admin_count(exclude_user_id=target.pk) == 0
            ):
                form.add_error(
                    None,
                    "O sistema precisa manter pelo menos um administrador ativo.",
                )

            if not form.errors:
                user = form.save()
                if was_active and not user.is_active:
                    invalidate_user_sessions(user.pk)

                if user.is_superuser:
                    profile = _ensure_profile(user)
                    if profile.role != UserAccessProfile.Role.ADMIN:
                        profile.role = UserAccessProfile.Role.ADMIN
                        profile.save(update_fields=["role", "updated_at"])
                request.audit_detail = {
                    "target_user_id": user.pk,
                    "target_role": _ensure_profile(user).role,
                    "target_active": user.is_active,
                }
                messages.success(request, "Usuário atualizado com sucesso.")
                return redirect("system_user_list")
    else:
        form = ManagedUserUpdateForm(user_obj=target, administrator=request.user)

    return render(
        request,
        "core/user_form.html",
        {
            "form": form,
            "page_heading": f"Editar usuário: {target.get_username()}",
            "editing_user": target,
        },
    )


@system_admin_required
@transaction.atomic
def user_password_reset(request, pk):
    if not _sensitive_user_management_allowed(request):
        return redirect("system_user_list")

    user_model = get_user_model()
    target = get_object_or_404(user_model, pk=pk, is_active=True)

    if request.method == "POST":
        form = ManagedUserPasswordResetForm(
            target,
            request.POST,
            administrator=request.user,
        )
        if form.is_valid():
            user = form.save()
            if user.pk == request.user.pk:
                invalidate_user_sessions(
                    user.pk,
                    exclude_session_key=request.session.session_key,
                )
                update_session_auth_hash(request, user)
            else:
                invalidate_user_sessions(user.pk)
            request.audit_detail = {
                "target_user_id": user.pk,
                "password_reset": True,
            }
            messages.success(
                request,
                f"Senha de {user.get_username()} redefinida com sucesso.",
            )
            return redirect("system_user_list")
    else:
        form = ManagedUserPasswordResetForm(
            target,
            administrator=request.user,
        )

    return render(
        request,
        "core/user_password_reset.html",
        {
            "form": form,
            "target_user": target,
        },
    )


def _safe_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@system_admin_required
def audit_list(request):
    query = (request.GET.get("q", "") or "").strip()
    user_id = (request.GET.get("user", "") or "").strip()
    result = (request.GET.get("result", "") or "").strip()
    date_from = _safe_date((request.GET.get("date_from", "") or "").strip())
    date_to = _safe_date((request.GET.get("date_to", "") or "").strip())

    events = AuditEvent.objects.select_related("actor").all()

    if query:
        events = events.filter(
            Q(action__icontains=query)
            | Q(path__icontains=query)
            | Q(actor__username__icontains=query)
        )

    if user_id.isdigit():
        events = events.filter(actor_id=int(user_id))

    if result == "success":
        events = events.filter(success=True)
    elif result == "failure":
        events = events.filter(success=False)

    if date_from:
        events = events.filter(created_at__date__gte=date_from)
    if date_to:
        events = events.filter(created_at__date__lte=date_to)

    paginator = Paginator(events, 100)
    page_obj = paginator.get_page(request.GET.get("page"))

    users = get_user_model()._default_manager.order_by("username")

    return render(
        request,
        "core/audit_list.html",
        {
            "page_obj": page_obj,
            "events": page_obj.object_list,
            "users": users,
            "query": query,
            "selected_user": user_id,
            "result_filter": result,
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
        },
    )
