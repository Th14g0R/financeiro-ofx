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
