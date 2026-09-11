from collections import Counter
from dataclasses import replace
from datetime import date
from urllib.parse import urlencode
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.db.models import Count
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.core.paginator import Paginator
from django.urls import reverse
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_http_methods
from django.views.generic import CreateView
from django.views.generic import ListView
from django.views.generic import UpdateView

from .forms import AccountForm
from .forms import BankForm
from .forms import CounterpartyAliasForm
from .forms import CounterpartyMergeConfirmForm
from .forms import CounterpartyMergeSelectionForm
from .forms import TransactionForm
from .forms import DuplicateBulkReviewForm
from .forms import DuplicateGroupBulkReviewForm
from .forms import DuplicateGroupReviewForm
from .forms import DuplicateReviewForm
from .models import Account
from .models import Bank
from .models import Category
from .models import Counterparty
from .models import CounterpartyAlias
from .models import InternalTransfer
from .models import Transaction
from .models import TransactionDuplicateReview
from services.counterparties import analyze_manual_counterparty_merge
from services.counterparties import merge_counterparties_manually
from services.counterparties import normalize_identity_text
from services.counterparties import rebuild_counterparty_links
from services.internal_transfers import analyze_internal_transfers
from services.internal_transfers import analyze_internal_balance_movements
from services.internal_transfers import annotate_financial_scope
from services.internal_transfers import confirm_internal_transfer
from services.internal_transfers import deactivate_account_internal_links
from services.internal_transfers import reject_internal_transfer
from services.internal_transfers import reopen_internal_transfer
from services.duplicates import analyze_duplicates
from services.duplicates import build_duplicate_review_groups
from services.duplicates import review_duplicate_group
from services.duplicates import review_duplicate_pair
from core.sorting import apply_sorting


class BankListView(LoginRequiredMixin, ListView):
    model = Bank
    template_name = "finance/bank_list.html"
    context_object_name = "banks"
    paginate_by = 25

    def get_queryset(self):
        queryset = Bank.objects.all()

        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "active")

        if query:
            queryset = queryset.filter(
                Q(name__icontains=query)
                | Q(code__icontains=query)
                | Q(ofx_bank_id__icontains=query)
            )

        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)

        return apply_sorting(
            self.request,
            queryset,
            allowed={
                "name": "name",
                "code": "code",
                "ofx": "ofx_bank_id",
                "status": "is_active",
            },
            default="name",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["query"] = self.request.GET.get("q", "").strip()
        context["status_filter"] = self.request.GET.get(
            "status",
            "active",
        )
        return context


class BankCreateView(
    LoginRequiredMixin,
    SuccessMessageMixin,
    CreateView,
):
    model = Bank
    form_class = BankForm
    template_name = "finance/bank_form.html"
    success_url = reverse_lazy("finance:bank-list")
    success_message = "Banco cadastrado com sucesso."


class BankUpdateView(
    LoginRequiredMixin,
    SuccessMessageMixin,
    UpdateView,
):
    model = Bank
    form_class = BankForm
    template_name = "finance/bank_form.html"
    success_url = reverse_lazy("finance:bank-list")
    success_message = "Banco atualizado com sucesso."


@login_required
@require_POST
def bank_toggle_active(request, pk):
    bank = get_object_or_404(Bank, pk=pk)
    bank.is_active = not bank.is_active
    bank.save(update_fields=["is_active", "updated_at"])

    status = "ativado" if bank.is_active else "desativado"
    messages.success(
        request,
        f'Banco "{bank.name}" {status} com sucesso.',
    )

    return redirect("finance:bank-list")


class AccountListView(LoginRequiredMixin, ListView):
    model = Account
    template_name = "finance/account_list.html"
    context_object_name = "accounts"
    paginate_by = 25

    def get_queryset(self):
        queryset = Account.objects.select_related("bank")

        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "active")
        bank_id = self.request.GET.get("bank", "").strip()
        ownership = self.request.GET.get(
            "ownership",
            "all",
        ).strip()

        if query:
            queryset = queryset.filter(
                Q(nickname__icontains=query)
                | Q(bank__name__icontains=query)
                | Q(branch__icontains=query)
                | Q(number__icontains=query)
                | Q(ofx_account_id__icontains=query)
                | Q(holder_name__icontains=query)
                | Q(holder_tax_id__icontains=query)
            )

        if bank_id.isdigit():
            queryset = queryset.filter(bank_id=int(bank_id))

        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)

        if ownership == "own":
            queryset = queryset.filter(
                is_own_account=True
            )
        elif ownership == "other":
            queryset = queryset.filter(
                is_own_account=False
            )

        return apply_sorting(
            self.request,
            queryset,
            allowed={
                "nickname": "nickname",
                "bank": "bank__name",
                "branch": "branch",
                "number": "number",
                "type": "account_type",
                "ofx": "ofx_account_id",
                "ownership": "is_own_account",
                "status": "is_active",
            },
            default="bank",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["banks"] = Bank.objects.order_by("name")
        context["query"] = self.request.GET.get("q", "").strip()
        context["status_filter"] = self.request.GET.get(
            "status",
            "active",
        )
        context["bank_filter"] = self.request.GET.get(
            "bank",
            "",
        )
        context["ownership_filter"] = self.request.GET.get(
            "ownership",
            "all",
        )
        return context


class AccountCreateView(
    LoginRequiredMixin,
    SuccessMessageMixin,
    CreateView,
):
    model = Account
    form_class = AccountForm
    template_name = "finance/account_form.html"
    success_url = reverse_lazy("finance:account-list")
    success_message = "Conta cadastrada com sucesso."


class AccountUpdateView(
    LoginRequiredMixin,
    SuccessMessageMixin,
    UpdateView,
):
    model = Account
    form_class = AccountForm
    template_name = "finance/account_form.html"
    success_url = reverse_lazy("finance:account-list")
    success_message = "Conta atualizada com sucesso."

    def form_valid(self, form):
        was_own = (
            Account.objects.filter(
                pk=self.object.pk
            )
            .values_list(
                "is_own_account",
                flat=True,
            )
            .first()
        )

        response = super().form_valid(
            form
        )

        if (
            was_own
            and not self.object.is_own_account
        ):
            affected = (
                deactivate_account_internal_links(
                    account_id=self.object.pk,
                    user=self.request.user,
                )
            )

            if affected:
                messages.warning(
                    self.request,
                    (
                        f"{affected} vínculo(s) interno(s) foram "
                        "desativados porque a conta deixou de ser marcada "
                        "como conta própria."
                    ),
                )

        elif (
            not was_own
            and self.object.is_own_account
        ):
            transaction_ids = tuple(
                self.object.transactions.values_list(
                    "pk",
                    flat=True,
                )
            )

            if transaction_ids:
                db_transaction.on_commit(
                    lambda: analyze_internal_transfers(
                        transaction_ids=(
                            transaction_ids
                        )
                    ),
                    robust=True,
                )

        return response


@login_required
@require_POST
def account_toggle_active(request, pk):
    account = get_object_or_404(Account, pk=pk)
    account.is_active = not account.is_active
    account.save(update_fields=["is_active", "updated_at"])

    status = "ativada" if account.is_active else "desativada"
    messages.success(
        request,
        f'Conta "{account.nickname}" {status} com sucesso.',
    )

    return redirect("finance:account-list")


class TransactionListView(LoginRequiredMixin, ListView):
    model = Transaction
    template_name = "finance/transaction_list.html"
    context_object_name = "transactions"
    paginate_by = 50

    def get_queryset(self):
        pending_duplicate = TransactionDuplicateReview.objects.filter(
            status=TransactionDuplicateReview.Status.PENDING,
        ).filter(
            Q(first_transaction_id=OuterRef("pk"))
            | Q(second_transaction_id=OuterRef("pk"))
        )
        queryset = annotate_financial_scope(
            Transaction.objects.select_related(
                "account",
                "account__bank",
                "category",
                "counterparty",
                "created_by",
                "canonical_transaction",
            ).annotate(
                has_pending_duplicate=Exists(pending_duplicate),
            )
        )

        query = self.request.GET.get("q", "").strip()
        bank_id = self.request.GET.get("bank", "").strip()
        account_id = self.request.GET.get("account", "").strip()
        direction = self.request.GET.get("direction", "").strip()
        transaction_type = self.request.GET.get("type", "").strip()
        source_type = self.request.GET.get("source", "").strip()
        category_id = self.request.GET.get("category", "").strip()
        financial_scope = self.request.GET.get(
            "scope",
            "",
        ).strip()
        date_from = self.request.GET.get("date_from", "").strip()
        date_to = self.request.GET.get("date_to", "").strip()
        visibility = self.request.GET.get("visibility", "active").strip()

        if query:
            normalized_query = normalize_identity_text(query)

            queryset = queryset.filter(
                Q(raw_description__icontains=query)
                | Q(normalized_description__icontains=query)
                | Q(document__icontains=query)
                | Q(reference__icontains=query)
                | Q(fitid__icontains=query)
                | Q(account__nickname__icontains=query)
                | Q(account__bank__name__icontains=query)
                | Q(category__name__icontains=query)
                | Q(source_category_name__icontains=query)
                | Q(
                    counterparty__normalized_name__icontains=(
                        normalized_query
                    )
                )
                | Q(
                    counterparty__aliases__normalized_alias__icontains=(
                        normalized_query
                    )
                )
            ).distinct()

        if bank_id.isdigit():
            queryset = queryset.filter(account__bank_id=int(bank_id))

        if account_id.isdigit():
            queryset = queryset.filter(account_id=int(account_id))

        valid_directions = {
            value
            for value, _label in Transaction.Direction.choices
        }
        if direction in valid_directions:
            queryset = queryset.filter(direction=direction)

        valid_types = {
            value
            for value, _label in Transaction.TransactionType.choices
        }
        if transaction_type in valid_types:
            queryset = queryset.filter(
                transaction_type=transaction_type
            )

        valid_sources = {
            value
            for value, _label in Transaction.SourceType.choices
        }
        if source_type in valid_sources:
            queryset = queryset.filter(source_type=source_type)

        if category_id == "uncategorized":
            queryset = queryset.filter(category__isnull=True)
        elif category_id.isdigit():
            queryset = queryset.filter(category_id=int(category_id))

        if financial_scope == "internal_balance":
            queryset = queryset.filter(
                is_internal_balance_movement=True
            )
        elif financial_scope == "internal":
            queryset = queryset.filter(
                is_internal_transfer=True
            )
        elif financial_scope == "possible":
            queryset = queryset.filter(
                is_possible_internal_transfer=True
            )
        elif financial_scope == "external":
            queryset = queryset.filter(
                is_internal_transfer=False,
                is_possible_internal_transfer=False,
            )

        try:
            parsed_date_from = (
                date.fromisoformat(date_from)
                if date_from
                else None
            )
        except ValueError:
            parsed_date_from = None

        try:
            parsed_date_to = (
                date.fromisoformat(date_to)
                if date_to
                else None
            )
        except ValueError:
            parsed_date_to = None

        if parsed_date_from:
            queryset = queryset.filter(
                posted_at__date__gte=parsed_date_from
            )

        if parsed_date_to:
            queryset = queryset.filter(
                posted_at__date__lte=parsed_date_to
            )

        if visibility == "ignored":
            queryset = queryset.filter(is_financially_ignored=True)
        elif visibility != "all":
            queryset = queryset.filter(is_financially_ignored=False)

        self.summary_queryset = queryset

        return apply_sorting(
            self.request,
            queryset,
            allowed={
                "date": "posted_at",
                "bank": "account__bank__name",
                "account": "account__nickname",
                "description": "raw_description",
                "type": "transaction_type",
                "source": "source_type",
                "category": "category__name",
                "counterparty": "counterparty__display_name",
                "scope": "financial_scope_rank",
                "amount": "amount",
            },
            default="date",
            default_direction="desc",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        summary_queryset = getattr(self, "summary_queryset", None)
        if summary_queryset is None:
            summary_queryset = self.get_queryset()
        financial_queryset = summary_queryset.filter(is_financially_ignored=False)
        total_credit = (
            financial_queryset.filter(direction=Transaction.Direction.CREDIT)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        total_debit = (
            financial_queryset.filter(direction=Transaction.Direction.DEBIT)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        context.update(
            {
                "filtered_credit": total_credit,
                "filtered_debit": total_debit,
                "filtered_net": total_credit - total_debit,
                "filtered_count": financial_queryset.count(),
                "ignored_in_filter_count": summary_queryset.filter(is_financially_ignored=True).count(),
                "pending_duplicate_count": TransactionDuplicateReview.objects.filter(
                    status=TransactionDuplicateReview.Status.PENDING
                ).count(),
            }
        )

        context.update(
            {
                "banks": Bank.objects.order_by("name"),
                "accounts": Account.objects.select_related(
                    "bank"
                ).order_by("bank__name", "nickname"),
                "direction_choices": Transaction.Direction.choices,
                "type_choices": Transaction.TransactionType.choices,
                "source_choices": Transaction.SourceType.choices,
                "categories": Category.objects.filter(is_active=True).order_by("name"),
                "query": self.request.GET.get("q", "").strip(),
                "bank_filter": self.request.GET.get("bank", "").strip(),
                "account_filter": self.request.GET.get(
                    "account",
                    "",
                ).strip(),
                "direction_filter": self.request.GET.get(
                    "direction",
                    "",
                ).strip(),
                "type_filter": self.request.GET.get("type", "").strip(),
                "source_filter": self.request.GET.get(
                    "source",
                    "",
                ).strip(),
                "category_filter": self.request.GET.get(
                    "category",
                    "",
                ).strip(),
                "scope_filter": self.request.GET.get(
                    "scope",
                    "",
                ).strip(),
                "scope_choices": [
                    ("external", "Externa"),
                    (
                        "internal",
                        "Movimentação interna",
                    ),
                    (
                        "internal_balance",
                        "Cofrinho/reserva da mesma conta",
                    ),
                    (
                        "possible",
                        "Possível transferência interna",
                    ),
                ],
                "date_from": self.request.GET.get(
                    "date_from",
                    "",
                ).strip(),
                "date_to": self.request.GET.get(
                    "date_to",
                    "",
                ).strip(),
                "visibility_filter": self.request.GET.get(
                    "visibility",
                    "active",
                ).strip(),
            }
        )

        return context


@login_required
@require_POST
def transaction_category_update(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk)
    category_value = (request.POST.get("category") or "").strip()

    if category_value:
        if not category_value.isdigit():
            messages.error(request, "Categoria inválida.")
            return redirect("finance:transaction-list")
        category = get_object_or_404(Category, pk=int(category_value), is_active=True)
        if category.category_type not in {
            Category.CategoryType.BOTH,
            (
                Category.CategoryType.INCOME
                if transaction.direction == Transaction.Direction.CREDIT
                else Category.CategoryType.EXPENSE
            ),
        }:
            messages.error(request, "A categoria escolhida não é compatível com a natureza da movimentação.")
            return redirect("finance:transaction-list")
    else:
        category = None

    transaction.category = category
    transaction.category_assignment_source = Transaction.CategoryAssignmentSource.MANUAL
    transaction.save(update_fields=["category", "category_assignment_source", "updated_at"])
    messages.success(
        request,
        f"Categoria da movimentação #{transaction.pk} atualizada.",
    )

    next_url = (request.POST.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("finance:transaction-list")


@login_required
@require_POST
def duplicate_analyze(request):
    analyzed = analyze_duplicates()
    pending = TransactionDuplicateReview.objects.filter(
        status=TransactionDuplicateReview.Status.PENDING
    ).count()
    messages.success(
        request,
        f"Análise concluída: {analyzed} par(es) comparado(s)/atualizado(s); {pending} pendente(s) para revisão.",
    )
    return redirect("finance:duplicate-review-list")


def _all_pending_duplicate_reviews():
    return list(
        TransactionDuplicateReview.objects.filter(
            status=TransactionDuplicateReview.Status.PENDING
        )
        .select_related(
            "first_transaction",
            "first_transaction__account",
            "first_transaction__account__bank",
            "first_transaction__counterparty",
            "first_transaction__category",
            "second_transaction",
            "second_transaction__account",
            "second_transaction__account__bank",
            "second_transaction__counterparty",
            "second_transaction__category",
        )
        .order_by("pk")
    )


def _duplicate_groups_for_filtered_review_ids(filtered_review_ids):
    filtered_ids = set(filtered_review_ids)
    if not filtered_ids:
        return []
    groups = build_duplicate_review_groups(_all_pending_duplicate_reviews())
    result = []
    for group in groups:
        if not filtered_ids.intersection(group.review_ids):
            continue
        result.append(
            replace(
                group,
                fully_matches_filter=set(group.review_ids).issubset(filtered_ids),
            )
        )
    return result


def _sort_duplicate_groups(groups, sort):
    if sort == "confidence_asc":
        return sorted(groups, key=lambda group: (group.min_confidence, group.seed_review_id))
    if sort == "newest":
        return sorted(
            groups,
            key=lambda group: max(review.created_at for review in group.reviews),
            reverse=True,
        )
    if sort == "oldest":
        return sorted(
            groups,
            key=lambda group: min(review.created_at for review in group.reviews),
        )
    return sorted(groups, key=lambda group: (-group.max_confidence, group.seed_review_id))


@login_required
def duplicate_review_list(request):
    filters = _duplicate_review_filter_state(request.GET)
    queryset = _duplicate_review_queryset(filters)
    pending_pair_count = TransactionDuplicateReview.objects.filter(
        status=TransactionDuplicateReview.Status.PENDING
    ).count()
    pending_groups_all = build_duplicate_review_groups(_all_pending_duplicate_reviews())
    pending_group_count = len(pending_groups_all)

    if filters["status"] == "pending":
        filtered_review_ids = list(queryset.values_list("pk", flat=True))
        groups = _sort_duplicate_groups(
            _duplicate_groups_for_filtered_review_ids(filtered_review_ids),
            filters["sort"],
        )
        filtered_pair_count = len(filtered_review_ids)
        filtered_count = len(groups)
        paginator = Paginator(groups, filters["page_size"])
        page_obj = paginator.get_page(request.GET.get("page"))
        context_items = page_obj.object_list
        grouped_mode = True
    else:
        filtered_pair_count = queryset.count()
        filtered_count = filtered_pair_count
        paginator = Paginator(queryset, filters["page_size"])
        page_obj = paginator.get_page(request.GET.get("page"))
        context_items = page_obj.object_list
        grouped_mode = False

    return render(
        request,
        "finance/duplicate_review_list.html",
        {
            "groups": context_items if grouped_mode else [],
            # Mantém compatibilidade com testes/extensões que ainda inspecionam
            # os pares, embora a UI pendente seja agrupada por componente.
            "reviews": (
                [review for group in context_items for review in group.reviews]
                if grouped_mode
                else context_items
            ),
            "grouped_mode": grouped_mode,
            "page_obj": page_obj,
            "is_paginated": page_obj.has_other_pages(),
            "status_filter": filters["status"],
            "pending_count": pending_pair_count,
            "pending_pair_count": pending_pair_count,
            "pending_group_count": pending_group_count,
            "filtered_count": filtered_count,
            "filtered_pair_count": filtered_pair_count,
            "bulk_filtered_count": filtered_count if grouped_mode else 0,
            "duplicate_filters": filters,
            "banks": Bank.objects.order_by("name"),
            "categories": Category.objects.filter(is_active=True).order_by("name"),
            "source_filter_choices": _duplicate_source_filter_choices(),
            "classification_choices": TransactionDuplicateReview.Classification.choices,
            "bulk_action_choices": DuplicateGroupBulkReviewForm.ACTIONS,
            "group_action_choices": DuplicateGroupReviewForm.ACTIONS,
        },
    )


def _duplicate_source_filter_choices():
    return [
        ("", "Todas"),
        ("PLUGGY", "Pluggy"),
        (Transaction.SourceType.OFX, "OFX/QFX"),
        (Transaction.SourceType.PDF, "PDF"),
        ("API_OTHER", "API (exceto Pluggy)"),
        (Transaction.SourceType.IMPORT, "Importação"),
        (Transaction.SourceType.MANUAL, "Manual"),
    ]


def _duplicate_bounded_int(value, *, minimum, maximum, default=None):
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _duplicate_review_filter_state(params):
    status = (params.get("status") or "pending").strip().lower()
    if status not in {"pending", "reviewed", "all"}:
        status = "pending"

    classification = (params.get("classification") or "").strip().upper()
    valid_classifications = {value for value, _label in TransactionDuplicateReview.Classification.choices}
    if classification not in valid_classifications:
        classification = ""

    confidence_min = _duplicate_bounded_int(
        params.get("confidence_min"), minimum=0, maximum=100, default=None
    )
    confidence_max = _duplicate_bounded_int(
        params.get("confidence_max"), minimum=0, maximum=100, default=None
    )

    try:
        bank_id = int(params.get("bank") or 0) or None
    except (TypeError, ValueError):
        bank_id = None

    try:
        category_id = int(params.get("category") or 0) or None
    except (TypeError, ValueError):
        category_id = None

    valid_sources = {value for value, _label in _duplicate_source_filter_choices()}
    source_a = (params.get("source_a") or "").strip().upper()
    source_b = (params.get("source_b") or "").strip().upper()
    if source_a not in valid_sources:
        source_a = ""
    if source_b not in valid_sources:
        source_b = ""

    sort = (params.get("sort") or "confidence_desc").strip().lower()
    if sort not in {"confidence_desc", "confidence_asc", "newest", "oldest"}:
        sort = "confidence_desc"

    page_size = _duplicate_bounded_int(
        params.get("page_size"), minimum=30, maximum=200, default=30
    )
    if page_size not in {30, 50, 100, 200}:
        page_size = 30

    return {
        "status": status,
        "classification": classification,
        "confidence_min": confidence_min,
        "confidence_max": confidence_max,
        "bank_id": bank_id,
        "category_id": category_id,
        "source_a": source_a,
        "source_b": source_b,
        "sort": sort,
        "page_size": page_size,
        "q": (params.get("q") or "").strip(),
    }


def _duplicate_source_q(path: str, source: str):
    source_path = f"{path}__source_type"
    fitid_path = f"{path}__fitid__istartswith"
    if source == "PLUGGY":
        return Q(**{source_path: Transaction.SourceType.API}) & (
            Q(**{fitid_path: "PLUGGY:"})
            | Q(**{fitid_path: "PLUGGY-PROVIDER:"})
        )
    if source == "API_OTHER":
        return (
            Q(**{source_path: Transaction.SourceType.API})
            & ~Q(**{fitid_path: "PLUGGY:"})
            & ~Q(**{fitid_path: "PLUGGY-PROVIDER:"})
        )
    if source:
        return Q(**{source_path: source})
    return Q()


def _duplicate_review_queryset(filters):
    queryset = TransactionDuplicateReview.objects.select_related(
        "first_transaction",
        "first_transaction__account",
        "first_transaction__account__bank",
        "first_transaction__counterparty",
        "first_transaction__category",
        "second_transaction",
        "second_transaction__account",
        "second_transaction__account__bank",
        "second_transaction__counterparty",
        "second_transaction__category",
        "reviewed_by",
    )

    status = filters["status"]
    if status == "pending":
        queryset = queryset.filter(status=TransactionDuplicateReview.Status.PENDING)
    elif status == "reviewed":
        queryset = queryset.exclude(status=TransactionDuplicateReview.Status.PENDING)

    if filters["classification"]:
        queryset = queryset.filter(classification=filters["classification"])
    if filters["confidence_min"] is not None:
        queryset = queryset.filter(confidence__gte=filters["confidence_min"])
    if filters["confidence_max"] is not None:
        queryset = queryset.filter(confidence__lte=filters["confidence_max"])
    if filters["bank_id"]:
        queryset = queryset.filter(
            Q(first_transaction__account__bank_id=filters["bank_id"])
            | Q(second_transaction__account__bank_id=filters["bank_id"])
        )
    if filters["category_id"]:
        queryset = queryset.filter(
            Q(first_transaction__category_id=filters["category_id"])
            | Q(second_transaction__category_id=filters["category_id"])
        )
    if filters["source_a"]:
        queryset = queryset.filter(_duplicate_source_q("first_transaction", filters["source_a"]))
    if filters["source_b"]:
        queryset = queryset.filter(_duplicate_source_q("second_transaction", filters["source_b"]))

    query = filters["q"]
    if query:
        queryset = queryset.filter(
            Q(first_transaction__raw_description__icontains=query)
            | Q(second_transaction__raw_description__icontains=query)
            | Q(first_transaction__fitid__icontains=query)
            | Q(second_transaction__fitid__icontains=query)
            | Q(first_transaction__counterparty__display_name__icontains=query)
            | Q(second_transaction__counterparty__display_name__icontains=query)
        )

    ordering = {
        "confidence_desc": ("-confidence", "-created_at", "-pk"),
        "confidence_asc": ("confidence", "-created_at", "-pk"),
        "newest": ("-created_at", "-confidence", "-pk"),
        "oldest": ("created_at", "-confidence", "pk"),
    }[filters["sort"]]
    return queryset.order_by(*ordering)


def _duplicate_review_redirect_url(params):
    filters = _duplicate_review_filter_state(params)
    query = {}
    for key in (
        "status",
        "classification",
        "confidence_min",
        "confidence_max",
        "source_a",
        "source_b",
        "sort",
        "page_size",
        "q",
    ):
        value = filters[key]
        if value not in (None, ""):
            query[key] = value
    if filters["bank_id"]:
        query["bank"] = filters["bank_id"]
    if filters["category_id"]:
        query["category"] = filters["category_id"]
    page = _duplicate_bounded_int(params.get("return_page"), minimum=1, maximum=999999, default=None)
    if page:
        query["page"] = page
    base = reverse("finance:duplicate-review-list")
    return f"{base}?{urlencode(query)}" if query else base


def _duplicate_review_form_error_message(form):
    messages_list = []
    for field_errors in form.errors.values():
        messages_list.extend(str(error) for error in field_errors)
    return " ".join(messages_list) or "Não foi possível validar a decisão em lote."


def _is_pluggy_transaction(transaction):
    return (
        transaction.source_type == Transaction.SourceType.API
        and (
            (transaction.fitid or "").startswith("PLUGGY:")
            or (transaction.fitid or "").startswith("PLUGGY-PROVIDER:")
        )
    )


def _bulk_group_resolution(group, action):
    transactions = list(group.transactions)
    if action == "keep_all":
        return "keep_all", None

    if action in {"keep_first", "keep_second", "merge_first", "merge_second"}:
        if len(transactions) != 2:
            return None
        index = 0 if action.endswith("first") else 1
        group_action = "merge_one" if action.startswith("merge") else "keep_one"
        return group_action, transactions[index].pk

    if action in {"prefer_pluggy", "merge_pluggy"}:
        candidates = [tx for tx in transactions if _is_pluggy_transaction(tx)]
        if len(candidates) != 1:
            return None
        return ("merge_one" if action == "merge_pluggy" else "keep_one"), candidates[0].pk

    if action in {"prefer_ofx", "merge_ofx"}:
        candidates = [tx for tx in transactions if tx.source_type == Transaction.SourceType.OFX]
        if len(candidates) != 1:
            return None
        return ("merge_one" if action == "merge_ofx" else "keep_one"), candidates[0].pk

    return None


@login_required
@require_POST
def duplicate_review_bulk(request):
    return_url = _duplicate_review_redirect_url(request.POST)
    form = DuplicateGroupBulkReviewForm(request.POST, user=request.user)
    if not form.is_valid():
        messages.error(request, _duplicate_review_form_error_message(form))
        return redirect(return_url)

    filters = _duplicate_review_filter_state(request.POST)
    filters["status"] = "pending"
    eligible_review_ids = list(
        _duplicate_review_queryset(filters).values_list("pk", flat=True)
    )
    filtered_groups = _sort_duplicate_groups(
        _duplicate_groups_for_filtered_review_ids(eligible_review_ids),
        filters["sort"],
    )

    if form.cleaned_data["apply_all_filtered"]:
        selected_groups = filtered_groups
        selection_label = "grupos filtrados"
    else:
        raw_seed_ids = request.POST.getlist("group_seed_ids")
        # Compatibilidade com o formulário anterior: um review_id selecionado
        # é convertido para o grupo ao qual pertence.
        raw_review_ids = request.POST.getlist("review_ids")
        selected_values = []
        for value in [*raw_seed_ids, *raw_review_ids]:
            try:
                selected_values.append(int(value))
            except (TypeError, ValueError):
                continue
        selected_set = set(selected_values)
        selected_groups = [
            group
            for group in filtered_groups
            if group.seed_review_id in selected_set
            or bool(selected_set.intersection(group.review_ids))
        ]
        selection_label = "grupos selecionados"

    if not selected_groups:
        messages.warning(
            request,
            "Selecione ao menos um grupo de duplicidade compatível com os filtros atuais.",
        )
        return redirect(return_url)

    action = form.cleaned_data["action"]
    plans = []
    skipped = 0
    for group in selected_groups:
        # Um filtro pode atingir apenas parte das relações de um grupo conectado.
        # Nunca aplique uma ação em lote ao componente inteiro nesse caso, pois
        # isso faria uma faixa de 100% decidir também relações de confiança menor.
        if not getattr(group, "fully_matches_filter", True):
            skipped += 1
            continue
        resolution = _bulk_group_resolution(group, action)
        if resolution is None:
            skipped += 1
            continue
        group_action, canonical_id = resolution
        plans.append((group.seed_review_id, group_action, canonical_id))

    if not plans:
        messages.warning(
            request,
            "Nenhum grupo pôde receber essa decisão. Para 'primeira/segunda', o grupo precisa ter exatamente duas movimentações; para preferir uma origem, deve existir exatamente uma movimentação daquela origem no grupo.",
        )
        return redirect(return_url)

    applied = 0
    ignored = 0
    review_count = 0
    try:
        with db_transaction.atomic():
            for seed_review_id, group_action, canonical_id in plans:
                result = review_duplicate_group(
                    seed_review_id,
                    action=group_action,
                    canonical_transaction_id=canonical_id,
                    user=request.user,
                )
                applied += 1
                ignored += result["ignored"]
                review_count += result["reviews"]
    except (IntegrityError, ValueError) as exc:
        messages.error(
            request,
            f"A decisão em lote foi cancelada sem alterações parciais: {exc}",
        )
        return redirect(return_url)

    request.audit_detail = {
        "bulk_duplicate_group_review": True,
        "decision": action,
        "applied_groups": applied,
        "resolved_reviews": review_count,
        "ignored_transactions": ignored,
        "skipped_groups": skipped,
        "selection": selection_label,
        "group_seed_ids": [seed for seed, _action, _canonical in plans[:200]],
    }
    message = (
        f"Decisão em lote aplicada a {applied} grupo(s), resolvendo {review_count} sugestão(ões) "
        f"e desconsiderando {ignored} movimentação(ões) duplicada(s)."
    )
    if skipped:
        message += f" {skipped} grupo(s) foram preservados para revisão individual por serem ambíguos para a ação escolhida."
    messages.success(request, message)
    return redirect(return_url)


@login_required
@require_POST
def duplicate_review_group(request, seed_review_id):
    form = DuplicateGroupReviewForm(request.POST, user=request.user)
    if not form.is_valid():
        messages.error(request, _duplicate_review_form_error_message(form))
        return redirect("finance:duplicate-review-list")

    try:
        result = review_duplicate_group(
            seed_review_id,
            action=form.cleaned_data["action"],
            canonical_transaction_id=form.cleaned_data.get("canonical_transaction_id"),
            user=request.user,
        )
    except (IntegrityError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect("finance:duplicate-review-list")

    request.audit_detail = {
        "duplicate_group_review": True,
        "seed_review_id": seed_review_id,
        "decision": form.cleaned_data["action"],
        "canonical_transaction_id": form.cleaned_data.get("canonical_transaction_id"),
        **result,
    }
    messages.success(
        request,
        f"Grupo resolvido: {result['transactions']} movimentação(ões), {result['reviews']} sugestão(ões) de duplicidade tratadas.",
    )
    return redirect("finance:duplicate-review-list")


@login_required
@require_http_methods(["GET", "POST"])
def duplicate_review_detail(request, pk):
    review = get_object_or_404(
        TransactionDuplicateReview.objects.select_related(
            "first_transaction",
            "first_transaction__account",
            "first_transaction__account__bank",
            "first_transaction__counterparty",
            "first_transaction__category",
            "second_transaction",
            "second_transaction__account",
            "second_transaction__account__bank",
            "second_transaction__counterparty",
        ),
        pk=pk,
    )
    if request.method == "POST":
        form = DuplicateReviewForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                review = review_duplicate_pair(
                    review,
                    action=form.cleaned_data["action"],
                    user=request.user,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                request.audit_detail = {
                    "duplicate_review_id": review.pk,
                    "first_transaction_id": review.first_transaction_id,
                    "second_transaction_id": review.second_transaction_id,
                    "decision": review.status,
                    "confidence": review.confidence,
                }
                messages.success(
                    request,
                    "Decisão aplicada. Lançamentos desconsiderados permanecem no banco para auditoria, mas deixam de compor os totais.",
                )
                return redirect("finance:duplicate-review-list")
    else:
        form = DuplicateReviewForm(user=request.user)
    return render(
        request,
        "finance/duplicate_review_detail.html",
        {"review": review, "form": form},
    )


class TransactionCreateView(
    LoginRequiredMixin,
    SuccessMessageMixin,
    CreateView,
):
    model = Transaction
    form_class = TransactionForm
    template_name = "finance/transaction_form.html"
    success_url = reverse_lazy("finance:transaction-list")
    success_message = "Movimentação cadastrada com sucesso."

    def form_valid(self, form):
        form.instance.source_type = Transaction.SourceType.MANUAL
        form.instance.created_by = self.request.user
        response = super().form_valid(
            form
        )

        transaction_id = (
            self.object.pk
        )

        db_transaction.on_commit(
            lambda: analyze_internal_transfers(
                transaction_ids=[
                    transaction_id
                ]
            ),
            robust=True,
        )

        return response


class TransactionUpdateView(
    LoginRequiredMixin,
    SuccessMessageMixin,
    UpdateView,
):
    model = Transaction
    form_class = TransactionForm
    template_name = "finance/transaction_form.html"
    success_url = reverse_lazy("finance:transaction-list")
    success_message = "Movimentação atualizada com sucesso."

    def get_queryset(self):
        return Transaction.objects.filter(
            source_type=Transaction.SourceType.MANUAL
        )

    def form_valid(self, form):
        response = super().form_valid(
            form
        )

        transaction_id = (
            self.object.pk
        )

        db_transaction.on_commit(
            lambda: analyze_internal_transfers(
                transaction_ids=[
                    transaction_id
                ]
            ),
            robust=True,
        )

        return response


class CounterpartyListView(LoginRequiredMixin, ListView):
    model = Counterparty
    template_name = "finance/counterparty_list.html"
    context_object_name = "counterparties"
    paginate_by = 40

    def get_queryset(self):
        queryset = (
            Counterparty.objects.filter(is_active=True)
            .annotate(
                transaction_count=Count(
                    "transactions",
                    distinct=True,
                ),
            )
        )

        query = self.request.GET.get("q", "").strip()

        if query:
            normalized_query = normalize_identity_text(query)

            queryset = queryset.filter(
                Q(normalized_name__icontains=normalized_query)
                | Q(
                    aliases__normalized_alias__icontains=normalized_query
                )
                | Q(display_name__icontains=query)
            ).distinct()

        return apply_sorting(
            self.request,
            queryset,
            allowed={
                "name": "display_name",
                "kind": "kind",
                "transactions": "transaction_count",
            },
            default="name",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["query"] = self.request.GET.get("q", "").strip()
        return context


@login_required
@require_POST
def counterparty_rebuild(request):
    result = rebuild_counterparty_links()

    messages.success(
        request,
        (
            "Associações reanalisadas: "
            f"{result['linked']} movimentação(ões) vinculada(s), "
            f"{result['reassigned']} reatribuída(s), "
            f"{result['renamed']} nome(s) saneado(s), "
            f"{result['merged'] + result['truncated_merged']} "
            "cadastro(s) mesclado(s)."
        ),
    )

    return redirect(
        "finance:counterparty-list"
    )




def _counterparty_merge_context(
    *,
    counterparties,
    confirm_form=None,
):
    items = list(
        Counterparty.objects.filter(
            pk__in=[
                item.pk
                for item in counterparties
            ],
            is_active=True,
        )
        .annotate(
            transaction_count=Count(
                "transactions",
                distinct=True,
            ),
            alias_count=Count(
                "aliases",
                distinct=True,
            ),
        )
        .prefetch_related(
            "aliases"
        )
        .order_by(
            "display_name",
            "id",
        )
    )

    if len(items) < 2:
        raise ValueError(
            "Selecione pelo menos duas contrapartes ativas."
        )

    analysis = (
        analyze_manual_counterparty_merge(
            items
        )
    )

    recommended_target = max(
        items,
        key=lambda item: (
            item.transaction_count,
            len(
                normalize_identity_text(
                    item.display_name
                )
            ),
            -item.pk,
        ),
    )

    suggested_name = max(
        (
            item.display_name
            for item in items
        ),
        key=lambda value: (
            len(
                normalize_identity_text(
                    value
                )
            ),
            len(value),
        ),
    )

    prepared_items = []

    identity_types = {
        CounterpartyAlias.AliasType.NAME,
        CounterpartyAlias.AliasType.PIX,
        CounterpartyAlias.AliasType.TAX_ID,
        CounterpartyAlias.AliasType.BANK_ID,
    }

    for item in items:
        identity_aliases = [
            alias
            for alias in item.aliases.all()
            if alias.alias_type
            in identity_types
        ]

        prepared_items.append(
            {
                "counterparty": item,
                "identity_aliases": (
                    identity_aliases
                ),
            }
        )

    return {
        "merge_items": prepared_items,
        "counterparties": items,
        "analysis": analysis,
        "recommended_target_id": (
            recommended_target.pk
        ),
        "suggested_name": (
            suggested_name
        ),
        "confirm_form": confirm_form,
    }


@login_required
@require_POST
def counterparty_merge_preview(
    request,
):
    form = CounterpartyMergeSelectionForm(
        request.POST
    )

    if not form.is_valid():
        messages.error(
            request,
            (
                form.errors.get(
                    "counterparties",
                    [
                        "Selecione pelo menos dois nomes."
                    ],
                )[0]
            ),
        )
        return redirect(
            "finance:counterparty-list"
        )

    counterparties = list(
        form.cleaned_data[
            "counterparties"
        ]
    )

    context = _counterparty_merge_context(
        counterparties=counterparties
    )

    return render(
        request,
        "finance/counterparty_merge_confirm.html",
        context,
    )


@login_required
@require_POST
def counterparty_merge_apply(
    request,
):
    selected_ids = request.POST.getlist(
        "counterparties"
    )

    form = CounterpartyMergeConfirmForm(
        request.POST,
        selected_ids=selected_ids,
    )

    selected_queryset = (
        Counterparty.objects.filter(
            pk__in=[
                value
                for value in selected_ids
                if str(value).isdigit()
            ],
            is_active=True,
        )
    )

    form_is_valid = form.is_valid()

    if form_is_valid:
        counterparties = list(
            form.cleaned_data[
                "counterparties"
            ]
        )

        analysis = (
            analyze_manual_counterparty_merge(
                counterparties
            )
        )

        if (
            analysis[
                "has_strong_conflicts"
            ]
            and not form.cleaned_data.get(
                "confirm_strong_conflicts"
            )
        ):
            form.add_error(
                "confirm_strong_conflicts",
                (
                    "Confirme explicitamente os conflitos "
                    "de identidade antes de unificar."
                ),
            )
            form_is_valid = False

    if not form_is_valid:
        try:
            context = (
                _counterparty_merge_context(
                    counterparties=(
                        selected_queryset
                    ),
                    confirm_form=form,
                )
            )
        except ValueError:
            messages.error(
                request,
                (
                    "A seleção não é mais válida. "
                    "Escolha novamente os registros."
                ),
            )
            return redirect(
                "finance:counterparty-list"
            )

        return render(
            request,
            "finance/counterparty_merge_confirm.html",
            context,
            status=400,
        )

    counterparties = list(
        form.cleaned_data[
            "counterparties"
        ]
    )
    target = form.cleaned_data[
        "target"
    ]

    try:
        result = (
            merge_counterparties_manually(
                counterparty_ids=[
                    item.pk
                    for item in counterparties
                ],
                target_id=target.pk,
                final_display_name=(
                    form.cleaned_data[
                        "final_display_name"
                    ]
                ),
                allow_strong_conflicts=bool(
                    form.cleaned_data.get(
                        "confirm_strong_conflicts"
                    )
                ),
            )
        )
    except ValueError as exc:
        messages.error(
            request,
            str(exc),
        )
        return redirect(
            "finance:counterparty-list"
        )

    messages.success(
        request,
        (
            f"{result.merged_records + 1} cadastros foram "
            f"unificados em “{result.final_display_name}”. "
            f"{result.moved_transactions} movimentação(ões) "
            "foram transferidas para o registro principal."
        ),
    )

    return redirect(
        "finance:counterparty-detail",
        pk=result.target_id,
    )

@login_required
def counterparty_detail(request, pk):
    counterparty = get_object_or_404(
        Counterparty,
        pk=pk,
        is_active=True,
    )

    transactions = (
        Transaction.objects.select_related(
            "account",
            "account__bank",
        )
        .filter(counterparty=counterparty)
    )

    bank_id = request.GET.get("bank", "").strip()
    direction = request.GET.get("direction", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    if bank_id.isdigit():
        transactions = transactions.filter(
            account__bank_id=int(bank_id)
        )

    valid_directions = {
        value
        for value, _label in Transaction.Direction.choices
    }

    if direction in valid_directions:
        transactions = transactions.filter(
            direction=direction
        )

    try:
        parsed_date_from = (
            date.fromisoformat(date_from)
            if date_from
            else None
        )
    except ValueError:
        parsed_date_from = None

    try:
        parsed_date_to = (
            date.fromisoformat(date_to)
            if date_to
            else None
        )
    except ValueError:
        parsed_date_to = None

    if parsed_date_from:
        transactions = transactions.filter(
            posted_at__date__gte=parsed_date_from
        )

    if parsed_date_to:
        transactions = transactions.filter(
            posted_at__date__lte=parsed_date_to
        )

    transactions = apply_sorting(
        request,
        transactions,
        allowed={
            "date": "posted_at",
            "bank": "account__bank__name",
            "description": "raw_description",
            "fitid": "fitid",
            "amount": "amount",
        },
        default="date",
        default_direction="desc",
    )

    totals = (
        transactions.order_by()
        .values("direction")
        .annotate(
            total=Sum("amount")
        )
    )

    total_credit = 0
    total_debit = 0

    for item in totals:
        if item["direction"] == Transaction.Direction.CREDIT:
            total_credit = item["total"]
        elif item["direction"] == Transaction.Direction.DEBIT:
            total_debit = item["total"]

    if request.method == "POST":
        alias_form = CounterpartyAliasForm(request.POST)

        if alias_form.is_valid():
            alias = alias_form.save(commit=False)
            alias.counterparty = counterparty
            alias.normalized_alias = normalize_identity_text(
                alias.alias
            )

            try:
                alias.full_clean()
                alias.save()
            except (ValidationError, IntegrityError):
                alias_form.add_error(
                    "alias",
                    "Este alias já está associado ou não é válido.",
                )
            else:
                messages.success(
                    request,
                    "Alias adicionado à contraparte.",
                )
                return redirect(
                    "finance:counterparty-detail",
                    pk=counterparty.pk,
                )
    else:
        alias_form = CounterpartyAliasForm()

    context = {
        "counterparty": counterparty,
        "transactions": transactions[:500],
        "transaction_count": transactions.count(),
        "total_credit": total_credit,
        "total_debit": total_debit,
        "aliases": counterparty.aliases.order_by(
            "alias_type",
            "alias",
        ),
        "identity_aliases": counterparty.aliases.exclude(
            alias_type=(
                CounterpartyAlias.AliasType.BANK_TEXT
            )
        ).order_by(
            "alias_type",
            "alias",
        ),
        "bank_text_aliases": counterparty.aliases.filter(
            alias_type=(
                CounterpartyAlias.AliasType.BANK_TEXT
            )
        ).order_by(
            "-created_at",
        )[:50],
        "alias_form": alias_form,
        "banks": Bank.objects.filter(
            accounts__transactions__counterparty=counterparty
        ).distinct().order_by("name"),
        "bank_filter": bank_id,
        "direction_filter": direction,
        "date_from": date_from,
        "date_to": date_to,
        "direction_choices": Transaction.Direction.choices,
    }

    return render(
        request,
        "finance/counterparty_detail.html",
        context,
    )



@login_required
def internal_transfer_list(request):
    status = request.GET.get(
        "status",
        InternalTransfer.Status.POSSIBLE,
    ).strip()

    valid_statuses = {
        value
        for value, _label
        in InternalTransfer.Status.choices
    }

    if status not in valid_statuses:
        status = InternalTransfer.Status.POSSIBLE

    bank_id = request.GET.get("bank", "").strip()
    try:
        parsed_bank_id = int(bank_id) if bank_id else None
    except (TypeError, ValueError):
        parsed_bank_id = None

    transfers = (
        InternalTransfer.objects.select_related(
            "debit_transaction",
            "debit_transaction__account",
            "debit_transaction__account__bank",
            "debit_transaction__counterparty",
            "credit_transaction",
            "credit_transaction__account",
            "credit_transaction__account__bank",
            "credit_transaction__counterparty",
            "reviewed_by",
        )
        .filter(status=status)
    )
    if parsed_bank_id:
        transfers = transfers.filter(
            Q(debit_transaction__account__bank_id=parsed_bank_id)
            | Q(credit_transaction__account__bank_id=parsed_bank_id)
        )

    transfers = transfers.order_by("-confidence", "-created_at")[:500]

    counts_queryset = InternalTransfer.objects.all()
    if parsed_bank_id:
        counts_queryset = counts_queryset.filter(
            Q(debit_transaction__account__bank_id=parsed_bank_id)
            | Q(credit_transaction__account__bank_id=parsed_bank_id)
        )
    counts = {
        item["status"]: item["total"]
        for item in counts_queryset.values("status").annotate(total=Count("id"))
    }

    internal_balance_queryset = Transaction.objects.filter(
        is_internal_balance_movement=True,
        is_financially_ignored=False,
    )
    if parsed_bank_id:
        internal_balance_queryset = internal_balance_queryset.filter(
            account__bank_id=parsed_bank_id
        )

    return render(
        request,
        "finance/internal_transfer_list.html",
        {
            "transfers": transfers,
            "status_filter": status,
            "status_choices": InternalTransfer.Status.choices,
            "possible_count": counts.get(InternalTransfer.Status.POSSIBLE, 0),
            "confirmed_count": counts.get(InternalTransfer.Status.CONFIRMED, 0),
            "rejected_count": counts.get(InternalTransfer.Status.REJECTED, 0),
            "banks": Bank.objects.order_by("name"),
            "bank_filter": parsed_bank_id,
            "internal_balance_count": internal_balance_queryset.count(),
        },
    )


@login_required
@require_POST
def internal_transfer_analyze(request):
    # Classify same-account balance movements first so Cofrinho/reserva rows
    # never become candidates for cross-account matching in the same run.
    balance_result = analyze_internal_balance_movements()
    result = analyze_internal_transfers()

    messages.success(
        request,
        (
            "Análise concluída: "
            f"{result['confirmed']} transferência(s) entre contas confirmada(s), "
            f"{result['possible']} possível(is) para revisão, "
            f"{result['skipped_ambiguous']} ambígua(s) sem vínculo e "
            f"{balance_result['detected']} movimentação(ões) entre saldo/cofrinho "
            "classificada(s) como interna(s)."
        ),
    )

    return redirect(
        "finance:internal-transfer-list"
    )


@login_required
@require_POST
def internal_transfer_confirm(
    request,
    pk,
):
    transfer = get_object_or_404(
        InternalTransfer,
        pk=pk,
        status=(
            InternalTransfer.Status.POSSIBLE
        ),
    )

    confirm_internal_transfer(
        transfer=transfer,
        user=request.user,
    )

    messages.success(
        request,
        "Transferência interna confirmada.",
    )

    return redirect(
        "finance:internal-transfer-list"
    )


@login_required
@require_POST
def internal_transfer_reject(
    request,
    pk,
):
    transfer = get_object_or_404(
        InternalTransfer,
        pk=pk,
        status=(
            InternalTransfer.Status.POSSIBLE
        ),
    )

    reject_internal_transfer(
        transfer=transfer,
        user=request.user,
    )

    messages.success(
        request,
        (
            "Par rejeitado. O sistema não voltará a "
            "relacionar automaticamente essas duas movimentações."
        ),
    )

    return redirect(
        "finance:internal-transfer-list"
    )


@login_required
@require_POST
def internal_transfer_undo(
    request,
    pk,
):
    transfer = get_object_or_404(
        InternalTransfer,
        pk=pk,
        status=(
            InternalTransfer.Status.CONFIRMED
        ),
    )

    reopen_internal_transfer(
        transfer=transfer,
        user=request.user,
    )

    messages.success(
        request,
        (
            "Vínculo interno desfeito. As duas movimentações "
            "voltam a ser externas e esse par ficará rejeitado."
        ),
    )

    return redirect(
        (
            reverse(
                "finance:internal-transfer-list"
            )
            + "?status=CONFIRMED"
        )
    )
