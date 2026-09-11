from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from finance.category_catalog import translate_pluggy_category
from finance.models import Account, Bank, Category, Transaction


class PluggyCategoryLocalizationTests(TestCase):
    def test_known_pluggy_categories_are_translated_to_clear_pt_br(self):
        self.assertEqual(translate_pluggy_category("Transfers"), "Transferências")
        self.assertEqual(translate_pluggy_category("Shopping"), "Compras")
        self.assertEqual(
            translate_pluggy_category("Proceeds interests and dividends"),
            "Rendimentos, juros e dividendos",
        )

    def test_unknown_category_is_preserved(self):
        self.assertEqual(
            translate_pluggy_category("New Pluggy Category"),
            "New Pluggy Category",
        )


class DashboardCategoryChartTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="dashboard-category-user",
            password="SenhaSegura123!",
        )
        self.client.force_login(self.user)
        self.bank = Bank.objects.create(name="Banco Categorias Dashboard", code="999")
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Conta principal",
            branch="0001",
            number="12345",
            digit="6",
        )
        self.shopping = Category.objects.create(
            name="Compras",
            category_type=Category.CategoryType.BOTH,
        )
        self.income = Category.objects.create(
            name="Receitas",
            category_type=Category.CategoryType.BOTH,
        )
        self.now = timezone.localtime().replace(day=9, hour=12, minute=0, second=0, microsecond=0)

    def make_transaction(self, *, direction, amount, category=None, fitid, internal=False):
        return Transaction.objects.create(
            account=self.account,
            posted_at=self.now,
            amount=Decimal(amount),
            direction=direction,
            transaction_type=Transaction.TransactionType.OTHER,
            source_type=Transaction.SourceType.API,
            fitid=fitid,
            raw_description=fitid,
            category=category,
            is_internal_balance_movement=internal,
        )

    def test_dashboard_builds_income_and_expense_category_charts_for_external_movements(self):
        self.make_transaction(
            direction=Transaction.Direction.DEBIT,
            amount="120.00",
            category=self.shopping,
            fitid="CAT-OUT-1",
        )
        self.make_transaction(
            direction=Transaction.Direction.CREDIT,
            amount="300.00",
            category=self.income,
            fitid="CAT-IN-1",
        )
        self.make_transaction(
            direction=Transaction.Direction.DEBIT,
            amount="50.00",
            category=None,
            fitid="CAT-OUT-UNCATEGORIZED",
        )
        self.make_transaction(
            direction=Transaction.Direction.DEBIT,
            amount="999.00",
            category=self.shopping,
            fitid="CAT-OUT-INTERNAL",
            internal=True,
        )

        response = self.client.get(
            reverse("home"),
            {"month": self.now.strftime("%Y-%m")},
        )

        self.assertEqual(response.status_code, 200)
        expense = response.context["category_expense_chart"]
        income = response.context["category_income_chart"]

        expense_by_label = dict(zip(expense["labels"], expense["values"], strict=True))
        income_by_label = dict(zip(income["labels"], income["values"], strict=True))

        self.assertEqual(expense_by_label["Compras"], 120.0)
        self.assertEqual(expense_by_label["Sem categoria"], 50.0)
        self.assertEqual(income_by_label["Receitas"], 300.0)
        self.assertNotEqual(expense_by_label["Compras"], 1119.0)

    def test_transaction_list_can_filter_uncategorized(self):
        uncategorized = self.make_transaction(
            direction=Transaction.Direction.DEBIT,
            amount="10.00",
            category=None,
            fitid="CAT-UNCATEGORIZED",
        )
        self.make_transaction(
            direction=Transaction.Direction.DEBIT,
            amount="20.00",
            category=self.shopping,
            fitid="CAT-CATEGORIZED",
        )

        response = self.client.get(
            reverse("finance:transaction-list"),
            {"category": "uncategorized"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [transaction.pk for transaction in response.context["transactions"]],
            [uncategorized.pk],
        )
