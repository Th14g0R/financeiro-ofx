from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.db.models import Count
from django.db.models import Q
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView
from django.views.generic import ListView
from django.views.generic import UpdateView

from .forms import AccountForm
from .forms import BankForm
from .forms import CounterpartyAliasForm
from .forms import CounterpartyMergeConfirmForm
from .forms import CounterpartyMergeSelectionForm
from .forms import TransactionForm
from .models import Account
from .models import Bank
from .models import Counterparty
from .models import CounterpartyAlias
from .models import InternalTransfer
from .models import Transaction
from services.counterparties import analyze_manual_counterparty_merge
from services.counterparties import merge_counterparties_manually
from services.counterparties import normalize_identity_text
from services.counterparties import rebuild_counterparty_links
from services.internal_transfers import analyze_internal_transfers
from services.internal_transfers import annotate_financial_scope
from services.internal_transfers import confirm_internal_transfer
from services.internal_transfers import deactivate_account_internal_links
from services.internal_transfers import reject_internal_transfer
from services.internal_transfers import reopen_internal_transfer
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
        queryset = annotate_financial_scope(
            Transaction.objects.select_related(
                "account",
                "account__bank",
                "category",
                "counterparty",
                "created_by",
            )
        )

        query = self.request.GET.get("q", "").strip()
        bank_id = self.request.GET.get("bank", "").strip()
        account_id = self.request.GET.get("account", "").strip()
        direction = self.request.GET.get("direction", "").strip()
        transaction_type = self.request.GET.get("type", "").strip()
        source_type = self.request.GET.get("source", "").strip()
        financial_scope = self.request.GET.get(
            "scope",
            "",
        ).strip()
        date_from = self.request.GET.get("date_from", "").strip()
        date_to = self.request.GET.get("date_to", "").strip()

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

        if financial_scope == "internal":
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
                "counterparty": "counterparty__display_name",
                "scope": "financial_scope_rank",
                "amount": "amount",
            },
            default="date",
            default_direction="desc",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context.update(
            {
                "banks": Bank.objects.order_by("name"),
                "accounts": Account.objects.select_related(
                    "bank"
                ).order_by("bank__name", "nickname"),
                "direction_choices": Transaction.Direction.choices,
                "type_choices": Transaction.TransactionType.choices,
                "source_choices": Transaction.SourceType.choices,
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
                "scope_filter": self.request.GET.get(
                    "scope",
                    "",
                ).strip(),
                "scope_choices": [
                    ("external", "Externa"),
                    (
                        "internal",
                        "Transferência interna",
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
            }
        )

        return context


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
        status = (
            InternalTransfer.Status.POSSIBLE
        )

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
        .filter(
            status=status
        )
        .order_by(
            "-confidence",
            "-created_at",
        )[:500]
    )

    counts = {
        item["status"]: item["total"]
        for item in (
            InternalTransfer.objects.values(
                "status"
            )
            .annotate(
                total=Count("id")
            )
        )
    }

    return render(
        request,
        "finance/internal_transfer_list.html",
        {
            "transfers": transfers,
            "status_filter": status,
            "status_choices": (
                InternalTransfer.Status.choices
            ),
            "possible_count": counts.get(
                InternalTransfer.Status.POSSIBLE,
                0,
            ),
            "confirmed_count": counts.get(
                InternalTransfer.Status.CONFIRMED,
                0,
            ),
            "rejected_count": counts.get(
                InternalTransfer.Status.REJECTED,
                0,
            ),
        },
    )


@login_required
@require_POST
def internal_transfer_analyze(request):
    result = (
        analyze_internal_transfers()
    )

    messages.success(
        request,
        (
            "Análise concluída: "
            f"{result['confirmed']} confirmada(s) automaticamente, "
            f"{result['possible']} possível(is) para revisão e "
            f"{result['skipped_ambiguous']} candidato(s) ambíguo(s) "
            "mantido(s) sem vínculo."
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
