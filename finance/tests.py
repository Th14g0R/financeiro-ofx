from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import BankForm
from .models import Account
from .models import Bank
from .models import Category
from .models import Transaction


class FinanceAuthenticationTests(TestCase):
    def test_bank_list_requires_authentication(self):
        response = self.client.get(reverse("finance:bank-list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_account_list_requires_authentication(self):
        response = self.client.get(reverse("finance:account-list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_transaction_list_requires_authentication(self):
        response = self.client.get(
            reverse("finance:transaction-list")
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)


class BankFormTests(TestCase):
    def test_compe_code_is_zero_padded(self):
        form = BankForm(
            data={
                "name": "Banco Teste",
                "code": "1",
                "ofx_bank_id": "",
                "is_active": True,
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["code"], "001")


class AccountModelTests(TestCase):
    def setUp(self):
        self.bank = Bank.objects.create(
            name="Banco Teste",
            code="999",
        )

    def test_currency_is_normalized_to_uppercase(self):
        account = Account(
            bank=self.bank,
            nickname="Principal",
            number="12345",
            currency="brl",
        )

        account.full_clean()

        self.assertEqual(account.currency, "BRL")

    def test_same_bank_account_cannot_be_duplicated(self):
        Account.objects.create(
            bank=self.bank,
            nickname="Principal",
            branch="0001",
            number="12345",
            digit="6",
        )

        duplicate = Account(
            bank=self.bank,
            nickname="Cópia",
            branch="0001",
            number="12345",
            digit="6",
        )

        with self.assertRaises(ValidationError):
            duplicate.full_clean()


class TransactionModelTests(TestCase):
    def setUp(self):
        self.bank = Bank.objects.create(
            name="Banco Modelo",
            code="998",
        )
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Principal",
            branch="0001",
            number="10001",
            digit="1",
        )

    def build_transaction(self, **overrides):
        data = {
            "account": self.account,
            "posted_at": timezone.now(),
            "amount": Decimal("100.00"),
            "direction": Transaction.Direction.CREDIT,
            "transaction_type": Transaction.TransactionType.PIX,
            "raw_description": "PIX JOAO DA SILVA",
        }
        data.update(overrides)
        return Transaction(**data)

    def test_credit_signed_amount_is_positive(self):
        item = self.build_transaction()
        item.full_clean()

        self.assertEqual(
            item.signed_amount,
            Decimal("100.00"),
        )

    def test_debit_signed_amount_is_negative(self):
        item = self.build_transaction(
            direction=Transaction.Direction.DEBIT
        )
        item.full_clean()

        self.assertEqual(
            item.signed_amount,
            Decimal("-100.00"),
        )

    def test_amount_must_be_greater_than_zero(self):
        item = self.build_transaction(
            amount=Decimal("0.00")
        )

        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_multiple_blank_fitids_are_allowed(self):
        first = self.build_transaction()
        first.save()

        second = self.build_transaction(
            raw_description="OUTRO PIX"
        )
        second.save()

        self.assertEqual(
            Transaction.objects.count(),
            2,
        )

    def test_fitid_is_unique_per_account_when_present(self):
        first = self.build_transaction(fitid="ABC123")
        first.save()

        duplicate = self.build_transaction(
            fitid="ABC123",
            raw_description="SEGUNDA OPERACAO",
        )

        with self.assertRaises(IntegrityError):
            with db_transaction.atomic():
                duplicate.save()

    def test_same_fitid_is_allowed_on_different_accounts(self):
        other_account = Account.objects.create(
            bank=self.bank,
            nickname="Secundária",
            branch="0001",
            number="10002",
            digit="2",
        )

        self.build_transaction(
            fitid="ABC123"
        ).save()

        self.build_transaction(
            account=other_account,
            fitid="ABC123",
        ).save()

        self.assertEqual(
            Transaction.objects.filter(
                fitid="ABC123"
            ).count(),
            2,
        )

    def test_category_must_match_direction(self):
        expense = Category.objects.create(
            name="Alimentação",
            category_type=Category.CategoryType.EXPENSE,
        )

        item = self.build_transaction(
            direction=Transaction.Direction.CREDIT,
            category=expense,
        )

        with self.assertRaises(ValidationError):
            item.full_clean()


class FinanceAuthenticatedViewsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="tester",
            password="safe-test-password-123",
        )
        self.client.force_login(self.user)

        self.bank = Bank.objects.create(
            name="Banco Web",
            code="997",
        )
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Principal",
            branch="0001",
            number="90001",
            digit="9",
        )

    def test_bank_list_opens(self):
        response = self.client.get(
            reverse("finance:bank-list")
        )

        self.assertEqual(response.status_code, 200)

    def test_account_list_opens(self):
        response = self.client.get(
            reverse("finance:account-list")
        )

        self.assertEqual(response.status_code, 200)

    def test_transaction_list_opens(self):
        response = self.client.get(
            reverse("finance:transaction-list")
        )

        self.assertEqual(response.status_code, 200)

    def test_manual_transaction_creation_sets_source_and_user(self):
        response = self.client.post(
            reverse("finance:transaction-create"),
            data={
                "account": self.account.pk,
                "posted_at": timezone.localtime(
                    timezone.now()
                ).strftime("%Y-%m-%dT%H:%M"),
                "competence_date": "",
                "amount": "125.50",
                "direction": Transaction.Direction.CREDIT,
                "transaction_type": Transaction.TransactionType.PIX,
                "raw_description": "PIX TESTE",
                "document": "",
                "reference": "",
                "category": "",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 302)

        item = Transaction.objects.get()

        self.assertEqual(
            item.source_type,
            Transaction.SourceType.MANUAL,
        )
        self.assertEqual(
            item.created_by,
            self.user,
        )

    def test_ofx_transaction_cannot_be_edited_in_manual_view(self):
        item = Transaction.objects.create(
            account=self.account,
            posted_at=timezone.now(),
            amount=Decimal("10.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.OFX,
            raw_description="OFX TESTE",
        )

        response = self.client.get(
            reverse(
                "finance:transaction-update",
                args=[item.pk],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_invalid_date_filter_does_not_break_list(self):
        response = self.client.get(
            reverse("finance:transaction-list"),
            data={
                "date_from": "data-invalida",
                "date_to": "outra-data-invalida",
            },
        )

        self.assertEqual(response.status_code, 200)
