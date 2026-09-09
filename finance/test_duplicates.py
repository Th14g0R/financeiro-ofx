from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from finance.models import Account, Bank, Transaction, TransactionDuplicateReview
from services.duplicates import analyze_duplicates, review_duplicate_pair


class TransactionDuplicateReviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="duplicate-reviewer",
            password="Senha-Muito-Forte-123!",
        )
        self.bank = Bank.objects.create(name="Nubank", code="260")
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Nubank",
            branch="0001",
            number="530540",
            digit="6",
        )
        self.posted_at = timezone.now().replace(hour=11, minute=0, second=0, microsecond=0)

    def _transaction(self, *, source, fitid, description, document=""):
        return Transaction.objects.create(
            account=self.account,
            posted_at=self.posted_at,
            competence_date=self.posted_at.date(),
            amount=Decimal("14.00"),
            direction=Transaction.Direction.DEBIT,
            transaction_type=Transaction.TransactionType.OTHER,
            source_type=source,
            fitid=fitid,
            raw_description=description,
            document=document,
        )

    def test_cross_source_same_operation_is_quarantined_for_review(self):
        original = self._transaction(
            source=Transaction.SourceType.OFX,
            fitid="OFX-ABC",
            description="Compra no débito - LAV60 MINUTOS - CE55",
        )
        pluggy = self._transaction(
            source=Transaction.SourceType.API,
            fitid="PLUGGY:123",
            description="Compra no débito|LAV60 MINUTOS - CE55",
        )

        analyze_duplicates(transaction_ids=[pluggy.pk], quarantine_new=True)

        pluggy.refresh_from_db()
        review = TransactionDuplicateReview.objects.get()
        self.assertEqual(review.classification, TransactionDuplicateReview.Classification.EXACT)
        self.assertTrue(pluggy.is_financially_ignored)
        self.assertEqual(pluggy.canonical_transaction_id, original.pk)

    def test_keep_both_restores_quarantined_transaction(self):
        original = self._transaction(
            source=Transaction.SourceType.OFX,
            fitid="OFX-ABC",
            description="Compra no débito - LAV60 MINUTOS - CE55",
        )
        pluggy = self._transaction(
            source=Transaction.SourceType.API,
            fitid="PLUGGY:123",
            description="Compra no débito|LAV60 MINUTOS - CE55",
        )
        analyze_duplicates(transaction_ids=[pluggy.pk], quarantine_new=True)
        review = TransactionDuplicateReview.objects.get()

        review_duplicate_pair(review, action="keep_both", user=self.user)

        original.refresh_from_db()
        pluggy.refresh_from_db()
        self.assertFalse(original.is_financially_ignored)
        self.assertFalse(pluggy.is_financially_ignored)
        self.assertIsNone(pluggy.canonical_transaction_id)

    def test_merge_keeps_auditable_loser_and_copies_missing_metadata(self):
        original = self._transaction(
            source=Transaction.SourceType.OFX,
            fitid="OFX-ABC",
            description="Compra no débito - LAV60 MINUTOS - CE55",
        )
        pluggy = self._transaction(
            source=Transaction.SourceType.API,
            fitid="PLUGGY:123",
            description="Compra no débito|LAV60 MINUTOS - CE55 - Fortaleza",
            document="123456",
        )
        analyze_duplicates(transaction_ids=[pluggy.pk], quarantine_new=True)
        review = TransactionDuplicateReview.objects.get()

        review_duplicate_pair(review, action="merge_first", user=self.user)

        original.refresh_from_db()
        pluggy.refresh_from_db()
        review.refresh_from_db()
        self.assertEqual(original.document, "123456")
        self.assertIn("Fortaleza", original.raw_description)
        self.assertTrue(pluggy.is_financially_ignored)
        self.assertEqual(pluggy.canonical_transaction_id, original.pk)
        self.assertEqual(review.status, TransactionDuplicateReview.Status.MERGED_FIRST)
        self.assertTrue(original.raw_data.get("_merged_sources"))


class TransactionDuplicateBulkReviewTests(TestCase):
    def setUp(self):
        self.password = "Senha-Muito-Forte-123!"
        self.user = get_user_model().objects.create_user(
            username="duplicate-bulk-reviewer",
            password=self.password,
        )
        self.client.force_login(self.user)
        self.bank = Bank.objects.create(name="Banco Teste", code="999")
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Conta Teste",
            branch="0001",
            number="12345",
            digit="6",
        )
        self.posted_at = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)

    def _tx(self, *, index, source=Transaction.SourceType.OFX):
        return Transaction.objects.create(
            account=self.account,
            posted_at=self.posted_at,
            competence_date=self.posted_at.date(),
            amount=Decimal(f"{10 + index}.00"),
            direction=Transaction.Direction.DEBIT,
            transaction_type=Transaction.TransactionType.OTHER,
            source_type=source,
            fitid=f"{source}-{index}",
            raw_description=f"Movimento {index}",
        )

    def _review(self, first, second, *, confidence=100):
        return TransactionDuplicateReview.objects.create(
            first_transaction=first,
            second_transaction=second,
            classification=(
                TransactionDuplicateReview.Classification.EXACT
                if confidence >= 90
                else TransactionDuplicateReview.Classification.POSSIBLE
            ),
            confidence=confidence,
            match_reasons=["Teste"],
        )

    def test_list_filters_by_confidence_range(self):
        tx1 = self._tx(index=1)
        tx2 = self._tx(index=2, source=Transaction.SourceType.API)
        tx3 = self._tx(index=3)
        tx4 = self._tx(index=4, source=Transaction.SourceType.API)
        review_100 = self._review(tx1, tx2, confidence=100)
        review_93 = self._review(tx3, tx4, confidence=93)

        response = self.client.get(
            "/finance/transactions/duplicates/",
            {"confidence_min": "100", "confidence_max": "100"},
        )

        self.assertEqual(response.status_code, 200)
        reviews = list(response.context["reviews"])
        self.assertEqual([review.pk for review in reviews], [review_100.pk])
        self.assertNotIn(review_93.pk, [review.pk for review in reviews])

    def test_bulk_keep_second_applies_to_selected_disjoint_pairs(self):
        tx1 = self._tx(index=1)
        tx2 = self._tx(index=2, source=Transaction.SourceType.API)
        tx3 = self._tx(index=3)
        tx4 = self._tx(index=4, source=Transaction.SourceType.API)
        review1 = self._review(tx1, tx2, confidence=100)
        review2 = self._review(tx3, tx4, confidence=100)

        response = self.client.post(
            "/finance/transactions/duplicates/bulk/",
            {
                "review_ids": [str(review1.pk), str(review2.pk)],
                "action": "keep_second",
                "current_password": self.password,
                "status": "pending",
                "confidence_min": "100",
                "confidence_max": "100",
                "page_size": "100",
            },
        )

        self.assertEqual(response.status_code, 302)
        review1.refresh_from_db()
        review2.refresh_from_db()
        tx1.refresh_from_db()
        tx3.refresh_from_db()
        self.assertEqual(review1.status, TransactionDuplicateReview.Status.KEEP_SECOND)
        self.assertEqual(review2.status, TransactionDuplicateReview.Status.KEEP_SECOND)
        self.assertTrue(tx1.is_financially_ignored)
        self.assertTrue(tx3.is_financially_ignored)

    def test_bulk_requires_current_password(self):
        tx1 = self._tx(index=1)
        tx2 = self._tx(index=2, source=Transaction.SourceType.API)
        review = self._review(tx1, tx2, confidence=100)

        response = self.client.post(
            "/finance/transactions/duplicates/bulk/",
            {
                "review_ids": [str(review.pk)],
                "action": "keep_second",
                "current_password": "senha-incorreta",
                "status": "pending",
            },
        )

        self.assertEqual(response.status_code, 302)
        review.refresh_from_db()
        self.assertEqual(review.status, TransactionDuplicateReview.Status.PENDING)

    def test_apply_all_filtered_only_affects_matching_confidence(self):
        tx1 = self._tx(index=1)
        tx2 = self._tx(index=2, source=Transaction.SourceType.API)
        tx3 = self._tx(index=3)
        tx4 = self._tx(index=4, source=Transaction.SourceType.API)
        review_100 = self._review(tx1, tx2, confidence=100)
        review_93 = self._review(tx3, tx4, confidence=93)

        response = self.client.post(
            "/finance/transactions/duplicates/bulk/",
            {
                "action": "keep_second",
                "current_password": self.password,
                "apply_all_filtered": "1",
                "status": "pending",
                "confidence_min": "100",
                "confidence_max": "100",
            },
        )

        self.assertEqual(response.status_code, 302)
        review_100.refresh_from_db()
        review_93.refresh_from_db()
        self.assertEqual(review_100.status, TransactionDuplicateReview.Status.KEEP_SECOND)
        self.assertEqual(review_93.status, TransactionDuplicateReview.Status.PENDING)

    def test_bulk_skips_pairs_that_share_a_transaction(self):
        tx1 = self._tx(index=1)
        tx2 = self._tx(index=2, source=Transaction.SourceType.API)
        tx3 = self._tx(index=3, source=Transaction.SourceType.API)
        review1 = self._review(tx1, tx2, confidence=100)
        review2 = self._review(tx1, tx3, confidence=100)

        response = self.client.post(
            "/finance/transactions/duplicates/bulk/",
            {
                "review_ids": [str(review1.pk), str(review2.pk)],
                "action": "keep_second",
                "current_password": self.password,
                "status": "pending",
            },
        )

        self.assertEqual(response.status_code, 302)
        review1.refresh_from_db()
        review2.refresh_from_db()
        self.assertEqual(review1.status, TransactionDuplicateReview.Status.PENDING)
        self.assertEqual(review2.status, TransactionDuplicateReview.Status.PENDING)
