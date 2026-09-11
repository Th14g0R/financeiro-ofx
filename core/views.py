from __future__ import annotations

from collections import defaultdict
from datetime import date
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.db.models import Sum
from django.db.models.functions import TruncDay
from django.db.models.functions import TruncMonth
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from finance.models import Account
from finance.models import Bank
from finance.models import InternalTransfer
from finance.models import Transaction
from services.internal_transfers import annotate_financial_scope


MONTH_NAMES = {
    1: "Jan",
    2: "Fev",
    3: "Mar",
    4: "Abr",
    5: "Mai",
    6: "Jun",
    7: "Jul",
    8: "Ago",
    9: "Set",
    10: "Out",
    11: "Nov",
    12: "Dez",
}


def _month_bounds(
    value: str,
) -> tuple[date, date] | None:
    try:
        year_text, month_text = value.split(
            "-",
            1,
        )
        year = int(year_text)
        month = int(month_text)
        start = date(year, month, 1)
    except (
        AttributeError,
        ValueError,
    ):
        return None

    if month == 12:
        next_month = date(
            year + 1,
            1,
            1,
        )
    else:
        next_month = date(
            year,
            month + 1,
            1,
        )

    return (
        start,
        next_month
        - timedelta(days=1),
    )


def _safe_date(
    value: str,
) -> date | None:
    try:
        return date.fromisoformat(
            value
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


def _safe_year(
    value: str,
) -> int | None:
    try:
        year = int(value)
    except (
        TypeError,
        ValueError,
    ):
        return None

    if not 2000 <= year <= 2200:
        return None

    return year


def _resolve_period(request):
    today = timezone.localdate()

    date_from = _safe_date(
        request.GET.get(
            "date_from",
            "",
        ).strip()
    )
    date_to = _safe_date(
        request.GET.get(
            "date_to",
            "",
        ).strip()
    )

    month_raw = request.GET.get(
        "month",
        "",
    ).strip()

    year_raw = request.GET.get(
        "year",
        "",
    ).strip()

    if date_from or date_to:
        start = date_from or date_to
        end = date_to or date_from

        if start > end:
            start, end = end, start

        return {
            "start": start,
            "end": end,
            "label": (
                f"{start:%d/%m/%Y} a "
                f"{end:%d/%m/%Y}"
                if start != end
                else f"{start:%d/%m/%Y}"
            ),
            "mode": "period",
            "selected_month": "",
            "selected_year": start.year,
        }

    month_bounds = _month_bounds(
        month_raw
    )

    if month_bounds:
        start, end = month_bounds

        return {
            "start": start,
            "end": end,
            "label": (
                f"{MONTH_NAMES[start.month]}/"
                f"{start.year}"
            ),
            "mode": "month",
            "selected_month": month_raw,
            "selected_year": start.year,
        }

    selected_year = _safe_year(
        year_raw
    )

    if selected_year:
        return {
            "start": date(
                selected_year,
                1,
                1,
            ),
            "end": date(
                selected_year,
                12,
                31,
            ),
            "label": str(
                selected_year
            ),
            "mode": "year",
            "selected_month": "",
            "selected_year": (
                selected_year
            ),
        }

    # Padrão: mês corrente.
    month_raw = (
        f"{today.year:04d}-"
        f"{today.month:02d}"
    )
    start, end = _month_bounds(
        month_raw
    )

    return {
        "start": start,
        "end": end,
        "label": (
            f"{MONTH_NAMES[start.month]}/"
            f"{start.year}"
        ),
        "mode": "month",
        "selected_month": month_raw,
        "selected_year": today.year,
    }


def _next_month(
    value: date,
) -> date:
    if value.month == 12:
        return date(
            value.year + 1,
            1,
            1,
        )

    return date(
        value.year,
        value.month + 1,
        1,
    )


def _build_period_chart(
    queryset,
    start: date,
    end: date,
    *,
    selected_bank_id: int | None = None,
):
    current_tz = (
        timezone.get_current_timezone()
    )
    days = (
        end - start
    ).days + 1

    if days <= 62:
        rows = (
            queryset.annotate(
                bucket=TruncDay(
                    "posted_at",
                    tzinfo=current_tz,
                )
            )
            .values(
                "bucket",
                "direction",
            )
            .annotate(
                total=Sum("amount")
            )
            .order_by("bucket")
        )

        values = defaultdict(
            lambda: {
                Transaction.Direction.CREDIT: (
                    Decimal("0.00")
                ),
                Transaction.Direction.DEBIT: (
                    Decimal("0.00")
                ),
            }
        )

        for row in rows:
            key = timezone.localtime(
                row["bucket"]
            ).date()
            values[
                key
            ][
                row["direction"]
            ] = row["total"]

        labels = []
        credits = []
        debits = []

        current = start

        while current <= end:
            labels.append(
                current.strftime(
                    "%d/%m"
                )
            )
            credits.append(
                float(
                    values[
                        current
                    ][
                        Transaction.Direction.CREDIT
                    ]
                )
            )
            debits.append(
                float(
                    values[
                        current
                    ][
                        Transaction.Direction.DEBIT
                    ]
                )
            )
            current += timedelta(
                days=1
            )

        return {
            "labels": labels,
            "credits": credits,
            "debits": debits,
            "grouping": "day",
            "drilldown_urls": [],
        }

    rows = (
        queryset.annotate(
            bucket=TruncMonth(
                "posted_at",
                tzinfo=current_tz,
            )
        )
        .values(
            "bucket",
            "direction",
        )
        .annotate(
            total=Sum("amount")
        )
        .order_by("bucket")
    )

    values = defaultdict(
        lambda: {
            Transaction.Direction.CREDIT: (
                Decimal("0.00")
            ),
            Transaction.Direction.DEBIT: (
                Decimal("0.00")
            ),
        }
    )

    for row in rows:
        localized = timezone.localtime(
            row["bucket"]
        )
        key = date(
            localized.year,
            localized.month,
            1,
        )
        values[
            key
        ][
            row["direction"]
        ] = row["total"]

    labels = []
    credits = []
    debits = []
    drilldown_urls = []

    current = date(
        start.year,
        start.month,
        1,
    )
    final = date(
        end.year,
        end.month,
        1,
    )

    while current <= final:
        labels.append(
            f"{MONTH_NAMES[current.month]}/"
            f"{str(current.year)[2:]}"
        )
        credits.append(
            float(
                values[
                    current
                ][
                    Transaction.Direction.CREDIT
                ]
            )
        )
        debits.append(
            float(
                values[
                    current
                ][
                    Transaction.Direction.DEBIT
                ]
            )
        )
        query = {
            "month": (
                f"{current.year:04d}-"
                f"{current.month:02d}"
            ),
        }

        if selected_bank_id:
            query["bank"] = str(
                selected_bank_id
            )

        drilldown_urls.append(
            "?" + urlencode(query)
        )
        current = _next_month(
            current
        )

    return {
        "labels": labels,
        "credits": credits,
        "debits": debits,
        "grouping": "month",
        "drilldown_urls": (
            drilldown_urls
        ),
    }


def _available_years():
    current_year = (
        timezone.localdate().year
    )

    years = {
        value.year
        for value in (
            Transaction.objects.filter(
                is_financially_ignored=False,
            ).dates(
                "posted_at",
                "year",
                order="DESC",
            )
        )
    }

    years.add(
        current_year
    )

    return sorted(
        years,
        reverse=True,
    )


@login_required
def home(request):
    selection = _resolve_period(
        request
    )
    start = selection["start"]
    end = selection["end"]

    selected_bank = None
    bank_raw = request.GET.get(
        "bank",
        "",
    ).strip()

    if bank_raw.isdigit():
        selected_bank = (
            Bank.objects.filter(
                pk=int(bank_raw),
                is_active=True,
            )
            .order_by("name")
            .first()
        )

    period_transactions = (
        annotate_financial_scope(
            Transaction.objects.filter(
                posted_at__date__gte=start,
                posted_at__date__lte=end,
                is_financially_ignored=False,
            )
        )
    )

    if selected_bank:
        period_transactions = (
            period_transactions.filter(
                account__bank=selected_bank
            )
        )

    # Visão bancária bruta preserva tudo que veio dos extratos.
    gross_credit = (
        period_transactions.filter(
            direction=(
                Transaction.Direction.CREDIT
            )
        )
        .aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )

    gross_debit = (
        period_transactions.filter(
            direction=(
                Transaction.Direction.DEBIT
            )
        )
        .aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )

    # Dashboard financeiro: vínculos CONFIRMADOS entre contas próprias
    # deixam de ser tratados como receita/despesa externa.
    external_transactions = (
        period_transactions.filter(
            is_internal_transfer=False
        )
    )

    period_credit = (
        external_transactions.filter(
            direction=(
                Transaction.Direction.CREDIT
            )
        )
        .aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )

    period_debit = (
        external_transactions.filter(
            direction=(
                Transaction.Direction.DEBIT
            )
        )
        .aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )

    period_net = (
        period_credit
        - period_debit
    )

    internal_received = (
        period_transactions.filter(
            direction=(
                Transaction.Direction.CREDIT
            )
        )
        .filter(
            is_internal_transfer=True
        )
        .aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )

    internal_sent = (
        period_transactions.filter(
            direction=(
                Transaction.Direction.DEBIT
            )
        )
        .filter(
            is_internal_transfer=True
        )
        .aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )

    internal_net = (
        internal_received
        - internal_sent
    )

    internal_balance_transactions = period_transactions.filter(
        is_internal_balance_movement=True
    )
    internal_balance_received = (
        internal_balance_transactions.filter(
            direction=Transaction.Direction.CREDIT
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    internal_balance_sent = (
        internal_balance_transactions.filter(
            direction=Transaction.Direction.DEBIT
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    internal_balance_count = internal_balance_transactions.count()

    between_accounts_transactions = period_transactions.filter(
        is_internal_transfer=True,
        is_internal_balance_movement=False,
    )
    between_accounts_received = (
        between_accounts_transactions.filter(
            direction=Transaction.Direction.CREDIT
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    between_accounts_sent = (
        between_accounts_transactions.filter(
            direction=Transaction.Direction.DEBIT
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )

    transfer_period_filter = Q(
        debit_transaction__posted_at__date__gte=start,
        debit_transaction__posted_at__date__lte=end,
    )

    if selected_bank:
        transfer_period_filter = (
            Q(
                debit_transaction__posted_at__date__gte=start,
                debit_transaction__posted_at__date__lte=end,
                debit_transaction__account__bank=selected_bank,
            )
            | Q(
                credit_transaction__posted_at__date__gte=start,
                credit_transaction__posted_at__date__lte=end,
                credit_transaction__account__bank=selected_bank,
            )
        )

    confirmed_transfer_links = (
        InternalTransfer.objects.filter(
            status=(
                InternalTransfer.Status.CONFIRMED
            ),
            debit_transaction__is_financially_ignored=False,
            credit_transaction__is_financially_ignored=False,
        )
        .filter(
            transfer_period_filter
        )
        .distinct()
    )

    internal_transfer_count = (
        confirmed_transfer_links.count()
    )

    # Na visão consolidada contamos cada transferência uma única vez,
    # usando a perna de saída como referência.
    internal_volume = (
        confirmed_transfer_links.aggregate(
            total=Sum(
                "debit_transaction__amount"
            )
        )["total"]
        or Decimal("0.00")
    )

    possible_transfer_count = (
        InternalTransfer.objects.filter(
            status=(
                InternalTransfer.Status.POSSIBLE
            ),
            debit_transaction__is_financially_ignored=False,
            credit_transaction__is_financially_ignored=False,
        )
        .filter(
            transfer_period_filter
        )
        .distinct()
        .count()
    )

    if selected_bank:
        expense_rows = list(
            external_transactions.filter(
                direction=(
                    Transaction.Direction.DEBIT
                )
            )
            .values(
                "account__nickname",
                "account__number",
            )
            .annotate(
                total=Sum("amount")
            )
            .order_by("-total")[:10]
        )

        expense_chart = {
            "labels": [
                (
                    item[
                        "account__nickname"
                    ]
                    or item[
                        "account__number"
                    ]
                    or "Conta"
                )
                for item in expense_rows
            ],
            "values": [
                float(item["total"])
                for item in expense_rows
            ],
        }
        expense_chart_title = (
            "Saídas por conta"
        )
    else:
        expense_rows = list(
            external_transactions.filter(
                direction=(
                    Transaction.Direction.DEBIT
                )
            )
            .values(
                "account__bank__name"
            )
            .annotate(
                total=Sum("amount")
            )
            .order_by("-total")[:10]
        )

        expense_chart = {
            "labels": [
                item[
                    "account__bank__name"
                ]
                for item in expense_rows
            ],
            "values": [
                float(item["total"])
                for item in expense_rows
            ],
        }
        expense_chart_title = (
            "Saídas por banco"
        )

    selected_bank_id = (
        selected_bank.pk
        if selected_bank
        else None
    )

    period_chart = (
        _build_period_chart(
            external_transactions,
            start,
            end,
            selected_bank_id=(
                selected_bank_id
            ),
        )
    )

    month_drilldown = []

    if selection["mode"] == "year":
        for month in range(
            1,
            13,
        ):
            month_drilldown.append(
                {
                    "label": (
                        MONTH_NAMES[month]
                    ),
                    "value": (
                        f"{selection['selected_year']:04d}-"
                        f"{month:02d}"
                    ),
                }
            )

    bank_scope_label = (
        selected_bank.name
        if selected_bank
        else "Todos os bancos"
    )

    period_label = (
        f"{selection['label']} · "
        f"{bank_scope_label}"
    )

    transaction_list_query = {
        "date_from": (
            start.isoformat()
        ),
        "date_to": (
            end.isoformat()
        ),
    }

    if selected_bank_id:
        transaction_list_query[
            "bank"
        ] = str(selected_bank_id)

    transaction_list_url = (
        reverse(
            "finance:transaction-list"
        )
        + "?"
        + urlencode(
            transaction_list_query
        )
    )

    external_transaction_query = dict(
        transaction_list_query
    )
    external_transaction_query[
        "scope"
    ] = "external"

    external_transaction_list_url = (
        reverse(
            "finance:transaction-list"
        )
        + "?"
        + urlencode(
            external_transaction_query
        )
    )

    def build_category_chart(direction):
        rows = list(
            external_transactions.filter(direction=direction)
            .values("category_id", "category__name")
            .annotate(total=Sum("amount"))
            .order_by("-total", "category__name")[:12]
        )

        labels = []
        values = []
        drilldown_urls = []
        for row in rows:
            category_id = row["category_id"]
            labels.append(row["category__name"] or "Sem categoria")
            values.append(float(row["total"]))

            query = dict(external_transaction_query)
            query["direction"] = direction
            query["category"] = (
                str(category_id) if category_id is not None else "uncategorized"
            )
            drilldown_urls.append(
                reverse("finance:transaction-list") + "?" + urlencode(query)
            )

        return {
            "labels": labels,
            "values": values,
            "drilldown_urls": drilldown_urls,
        }

    category_expense_chart = build_category_chart(Transaction.Direction.DEBIT)
    category_income_chart = build_category_chart(Transaction.Direction.CREDIT)

    internal_transfer_url = (
        reverse(
            "finance:internal-transfer-list"
        )
    )

    context = {
        "bank_count": (
            period_transactions.values(
                "account__bank_id"
            )
            .distinct()
            .count()
        ),
        "account_count": (
            period_transactions.values(
                "account_id"
            )
            .distinct()
            .count()
        ),
        "transaction_count": (
            period_transactions.count()
        ),
        "period_credit": period_credit,
        "period_debit": period_debit,
        "period_net": period_net,
        "gross_credit": gross_credit,
        "gross_debit": gross_debit,
        "internal_received": (
            internal_received
        ),
        "internal_sent": (
            internal_sent
        ),
        "internal_net": (
            internal_net
        ),
        "internal_balance_received": internal_balance_received,
        "internal_balance_sent": internal_balance_sent,
        "internal_balance_count": internal_balance_count,
        "between_accounts_received": between_accounts_received,
        "between_accounts_sent": between_accounts_sent,
        "internal_volume": (
            internal_volume
        ),
        "internal_transfer_count": (
            internal_transfer_count
        ),
        "possible_transfer_count": (
            possible_transfer_count
        ),
        "external_transaction_count": (
            external_transactions.count()
        ),
        "period_label": period_label,
        "period_mode": (
            selection["mode"]
        ),
        "period_start": (
            start.isoformat()
        ),
        "period_end": (
            end.isoformat()
        ),
        "selected_month": (
            selection[
                "selected_month"
            ]
        ),
        "selected_year": (
            selection[
                "selected_year"
            ]
        ),
        "available_years": (
            _available_years()
        ),
        "month_drilldown": (
            month_drilldown
        ),
        "period_chart": (
            period_chart
        ),
        "expense_chart": (
            expense_chart
        ),
        "expense_chart_title": (
            expense_chart_title
        ),
        "category_expense_chart": category_expense_chart,
        "category_income_chart": category_income_chart,
        "available_banks": (
            Bank.objects.filter(
                is_active=True,
                accounts__transactions__isnull=False,
            )
            .distinct()
            .order_by("name")
        ),
        "selected_bank": (
            selected_bank
        ),
        "selected_bank_id": (
            selected_bank_id
        ),
        "bank_scope_label": (
            bank_scope_label
        ),
        "transaction_list_url": (
            transaction_list_url
        ),
        "external_transaction_list_url": (
            external_transaction_list_url
        ),
        "internal_transfer_url": (
            internal_transfer_url
        ),
    }

    return render(
        request,
        "core/home.html",
        context,
    )

