from datetime import datetime
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from finance.models import Account
from finance.models import Bank
from finance.models import InternalTransfer
from finance.models import Transaction
from services.internal_transfers import analyze_internal_transfers
from services.internal_transfers import confirm_internal_transfer
from services.internal_transfers import reject_internal_transfer


class InternalTransferTestBase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="internal-transfer-user",
            password="safe-password-123",
        )

        self.bank_a = Bank.objects.create(
            name="Banco Interno A",
            code="971",
        )
        self.bank_b = Bank.objects.create(
            name="Banco Interno B",
            code="972",
        )
        self.bank_c = Bank.objects.create(
            name="Banco Externo C",
            code="973",
        )

        self.account_a = Account.objects.create(
            bank=self.bank_a,
            nickname="Principal A",
            branch="1",
            number="100",
            is_own_account=True,
        )
        self.account_b = Account.objects.create(
            bank=self.bank_b,
            nickname="Principal B",
            branch="1",
            number="200",
            is_own_account=True,
        )
        self.other_account = Account.objects.create(
            bank=self.bank_c,
            nickname="Terceiro",
            branch="1",
            number="300",
            is_own_account=False,
        )

        self.base_time = timezone.make_aware(
            datetime(
                2026,
                8,
                15,
                10,
                0,
            )
        )

    def make_transaction(
        self,
        *,
        account,
        direction,
        amount="1000.00",
        transaction_type=Transaction.TransactionType.PIX,
        posted_at=None,
        description="Transferência Pix",
        source_type=Transaction.SourceType.MANUAL,
        raw_data=None,
        fitid="",
    ):
        return Transaction.objects.create(
            account=account,
            posted_at=(
                posted_at
                or self.base_time
            ),
            amount=Decimal(amount),
            direction=direction,
            transaction_type=transaction_type,
            source_type=source_type,
            raw_description=description,
            raw_data=raw_data or {},
            fitid=fitid,
            created_by=self.user,
        )


class InternalTransferMatcherTests(
    InternalTransferTestBase
):
    def test_unique_close_pix_pair_is_auto_confirmed(self):
        debit = self.make_transaction(
            account=self.account_a,
            direction=Transaction.Direction.DEBIT,
            fitid="DEBIT-AUTO",
        )
        credit = self.make_transaction(
            account=self.account_b,
            direction=Transaction.Direction.CREDIT,
            posted_at=(
                self.base_time
                + timedelta(
                    seconds=30
                )
            ),
            fitid="CREDIT-AUTO",
        )

        result = (
            analyze_internal_transfers()
        )

        self.assertEqual(
            result["confirmed"],
            1,
        )

        link = (
            InternalTransfer.objects.get()
        )

        self.assertEqual(
            link.status,
            InternalTransfer.Status.CONFIRMED,
        )
        self.assertEqual(
            link.debit_transaction,
            debit,
        )
        self.assertEqual(
            link.credit_transaction,
            credit,
        )
        self.assertGreaterEqual(
            link.confidence,
            90,
        )

    def test_same_amount_non_transfer_is_not_matched(self):
        self.make_transaction(
            account=self.account_a,
            direction=Transaction.Direction.DEBIT,
            transaction_type=(
                Transaction.TransactionType.CARD_PURCHASE
            ),
            description="Compra supermercado",
        )
        self.make_transaction(
            account=self.account_b,
            direction=Transaction.Direction.CREDIT,
            transaction_type=(
                Transaction.TransactionType.CASH_DEPOSIT
            ),
            description="Depósito identificado",
        )

        analyze_internal_transfers()

        self.assertFalse(
            InternalTransfer.objects.exists()
        )

    def test_ambiguous_equal_candidates_are_not_linked(self):
        self.make_transaction(
            account=self.account_a,
            direction=Transaction.Direction.DEBIT,
        )
        self.make_transaction(
            account=self.account_b,
            direction=Transaction.Direction.CREDIT,
            posted_at=(
                self.base_time
                + timedelta(
                    minutes=1
                )
            ),
        )

        bank_d = Bank.objects.create(
            name="Banco Interno D",
            code="974",
        )
        account_d = Account.objects.create(
            bank=bank_d,
            nickname="Principal D",
            branch="1",
            number="400",
            is_own_account=True,
        )

        self.make_transaction(
            account=account_d,
            direction=Transaction.Direction.CREDIT,
            posted_at=(
                self.base_time
                + timedelta(
                    minutes=1
                )
            ),
        )

        result = (
            analyze_internal_transfers()
        )

        self.assertEqual(
            result["confirmed"],
            0,
        )
        self.assertEqual(
            result["possible"],
            0,
        )
        self.assertFalse(
            InternalTransfer.objects.exists()
        )

    def test_pdf_without_time_becomes_possible_not_confirmed(self):
        debit = self.make_transaction(
            account=self.account_a,
            direction=Transaction.Direction.DEBIT,
            source_type=Transaction.SourceType.PDF,
            raw_data={
                "source_format": "PDF",
            },
        )
        credit = self.make_transaction(
            account=self.account_b,
            direction=Transaction.Direction.CREDIT,
            source_type=Transaction.SourceType.PDF,
            raw_data={
                "source_format": "PDF",
            },
        )

        result = (
            analyze_internal_transfers()
        )

        self.assertEqual(
            result["confirmed"],
            0,
        )
        self.assertEqual(
            result["possible"],
            1,
        )

        link = (
            InternalTransfer.objects.get()
        )

        self.assertEqual(
            link.status,
            InternalTransfer.Status.POSSIBLE,
        )
        self.assertEqual(
            link.debit_transaction,
            debit,
        )
        self.assertEqual(
            link.credit_transaction,
            credit,
        )

    def test_rejected_pair_is_not_suggested_again(self):
        debit = self.make_transaction(
            account=self.account_a,
            direction=Transaction.Direction.DEBIT,
            source_type=Transaction.SourceType.PDF,
        )
        credit = self.make_transaction(
            account=self.account_b,
            direction=Transaction.Direction.CREDIT,
            source_type=Transaction.SourceType.PDF,
        )

        analyze_internal_transfers()

        link = (
            InternalTransfer.objects.get()
        )

        reject_internal_transfer(
            transfer=link,
            user=self.user,
        )

        analyze_internal_transfers()

        self.assertEqual(
            InternalTransfer.objects.count(),
            1,
        )
        link.refresh_from_db()
        self.assertEqual(
            link.status,
            InternalTransfer.Status.REJECTED,
        )

    def test_possible_can_be_confirmed_by_user(self):
        self.make_transaction(
            account=self.account_a,
            direction=Transaction.Direction.DEBIT,
            source_type=Transaction.SourceType.PDF,
        )
        self.make_transaction(
            account=self.account_b,
            direction=Transaction.Direction.CREDIT,
            source_type=Transaction.SourceType.PDF,
        )

        analyze_internal_transfers()
        link = (
            InternalTransfer.objects.get()
        )

        confirm_internal_transfer(
            transfer=link,
            user=self.user,
        )

        link.refresh_from_db()

        self.assertEqual(
            link.status,
            InternalTransfer.Status.CONFIRMED,
        )
        self.assertEqual(
            link.reviewed_by,
            self.user,
        )
        self.assertIsNotNone(
            link.reviewed_at
        )

    def test_account_is_own_by_default(self):
        account = Account.objects.create(
            bank=self.bank_a,
            nickname="Nova própria",
            branch="2",
            number="999",
        )

        self.assertTrue(
            account.is_own_account
        )


class InternalTransferDashboardTests(
    InternalTransferTestBase
):
    def setUp(self):
        super().setUp()
        self.client.force_login(
            self.user
        )

        self.internal_debit = (
            self.make_transaction(
                account=self.account_a,
                direction=Transaction.Direction.DEBIT,
                amount="1000.00",
                fitid="INT-D",
            )
        )
        self.internal_credit = (
            self.make_transaction(
                account=self.account_b,
                direction=Transaction.Direction.CREDIT,
                amount="1000.00",
                posted_at=(
                    self.base_time
                    + timedelta(
                        minutes=1
                    )
                ),
                fitid="INT-C",
            )
        )

        analyze_internal_transfers()

        self.external_credit = (
            self.make_transaction(
                account=self.account_a,
                direction=Transaction.Direction.CREDIT,
                amount="500.00",
                transaction_type=(
                    Transaction.TransactionType.OTHER
                ),
                description=(
                    "Recebimento de terceiro"
                ),
                posted_at=(
                    self.base_time
                    + timedelta(
                        hours=1
                    )
                ),
                fitid="EXT-C",
            )
        )

    def test_dashboard_excludes_confirmed_internal_from_external_totals(self):
        response = self.client.get(
            reverse("home"),
            {
                "month": "2026-08",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.context[
                "period_credit"
            ],
            Decimal("500.00"),
        )
        self.assertEqual(
            response.context[
                "period_debit"
            ],
            Decimal("0.00"),
        )
        self.assertEqual(
            response.context[
                "gross_credit"
            ],
            Decimal("1500.00"),
        )
        self.assertEqual(
            response.context[
                "gross_debit"
            ],
            Decimal("1000.00"),
        )
        self.assertEqual(
            response.context[
                "internal_volume"
            ],
            Decimal("1000.00"),
        )
        self.assertEqual(
            response.context[
                "internal_transfer_count"
            ],
            1,
        )

    def test_bank_dashboard_separates_internal_received_and_sent(self):
        response = self.client.get(
            reverse("home"),
            {
                "month": "2026-08",
                "bank": str(
                    self.bank_b.pk
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.context[
                "period_credit"
            ],
            Decimal("0.00"),
        )
        self.assertEqual(
            response.context[
                "internal_received"
            ],
            Decimal("1000.00"),
        )
        self.assertEqual(
            response.context[
                "internal_sent"
            ],
            Decimal("0.00"),
        )
        self.assertEqual(
            response.context[
                "internal_net"
            ],
            Decimal("1000.00"),
        )

    def test_possible_link_remains_external_until_confirmation(self):
        InternalTransfer.objects.all().delete()

        # Cria outro par PDF, que deve ficar POSSIBLE.
        debit = self.make_transaction(
            account=self.account_a,
            direction=Transaction.Direction.DEBIT,
            amount="700.00",
            source_type=Transaction.SourceType.PDF,
            posted_at=(
                self.base_time
                + timedelta(
                    days=2
                )
            ),
            fitid="POSS-D",
        )
        credit = self.make_transaction(
            account=self.account_b,
            direction=Transaction.Direction.CREDIT,
            amount="700.00",
            source_type=Transaction.SourceType.PDF,
            posted_at=(
                self.base_time
                + timedelta(
                    days=2
                )
            ),
            fitid="POSS-C",
        )

        analyze_internal_transfers(
            transaction_ids=[
                debit.pk,
                credit.pk,
            ]
        )

        link = (
            InternalTransfer.objects.get(
                debit_transaction=debit,
                credit_transaction=credit,
            )
        )

        self.assertEqual(
            link.status,
            InternalTransfer.Status.POSSIBLE,
        )

        response = self.client.get(
            reverse("home"),
            {
                "month": "2026-08",
            },
        )

        self.assertGreaterEqual(
            response.context[
                "period_credit"
            ],
            Decimal("1200.00"),
        )
        self.assertGreaterEqual(
            response.context[
                "period_debit"
            ],
            Decimal("700.00"),
        )
        self.assertGreaterEqual(
            response.context[
                "possible_transfer_count"
            ],
            1,
        )


class InternalTransferViewsTests(
    InternalTransferTestBase
):
    def setUp(self):
        super().setUp()
        self.client.force_login(
            self.user
        )

        self.debit = self.make_transaction(
            account=self.account_a,
            direction=Transaction.Direction.DEBIT,
            source_type=Transaction.SourceType.PDF,
        )
        self.credit = self.make_transaction(
            account=self.account_b,
            direction=Transaction.Direction.CREDIT,
            source_type=Transaction.SourceType.PDF,
        )
        analyze_internal_transfers()
        self.link = (
            InternalTransfer.objects.get()
        )

    def test_review_page_opens(self):
        response = self.client.get(
            reverse(
                "finance:internal-transfer-list"
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertContains(
            response,
            "Transferências entre minhas contas",
        )

    def test_confirm_endpoint(self):
        response = self.client.post(
            reverse(
                "finance:internal-transfer-confirm",
                args=[self.link.pk],
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.link.refresh_from_db()
        self.assertEqual(
            self.link.status,
            InternalTransfer.Status.CONFIRMED,
        )

    def test_transaction_list_filters_internal_scope(self):
        confirm_internal_transfer(
            transfer=self.link,
            user=self.user,
        )

        response = self.client.get(
            reverse(
                "finance:transaction-list"
            ),
            {
                "scope": "internal",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            len(
                response.context[
                    "transactions"
                ]
            ),
            2,
        )
        self.assertContains(
            response,
            "Transferência interna",
        )
