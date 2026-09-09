from datetime import datetime
from decimal import Decimal
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from finance.models import Account, Bank, Transaction, TransactionDuplicateReview
from imports.models import ImportBatch, ImportEffect, ImportFile, ImportItem, ImportStatement
from services.importing.commit import transaction_snapshot
from services.importing.ofx_cleanup import (
    CATEGORY_DIRECT_UNIQUE,
    CATEGORY_MODIFIED_UNIQUE,
    CATEGORY_PLUGGY_DUPLICATE,
    CATEGORY_UPDATED_REVERT,
    build_ofx_cleanup_plan,
    execute_ofx_cleanup,
)


class OfxCleanupTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._media_dir = tempfile.TemporaryDirectory()
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir.name)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        cls._media_dir.cleanup()

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="ofx-cleanup",
            password="safe-password-123",
        )
        self.bank = Bank.objects.create(name="Nubank", code="260")
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Nubank",
            branch="0001",
            number="530540",
            digit="6",
            ofx_account_id="530540-6",
        )
        self.posted_at = timezone.make_aware(datetime(2026, 2, 20, 0, 0))

    def _batch_item(self, *, sequence=1):
        batch = ImportBatch.objects.create(created_by=self.user, status=ImportBatch.Status.COMMITTED)
        import_file = ImportFile.objects.create(
            batch=batch,
            file=SimpleUploadedFile("nubank.ofx", b"OFXHEADER:100\n<OFX></OFX>"),
            original_name="nubank.ofx",
            file_hash=("a" * 63) + str(sequence % 10),
            file_size=25,
            source_format=ImportFile.SourceFormat.OFX,
            status=ImportFile.Status.IMPORTED,
        )
        statement = ImportStatement.objects.create(
            import_file=import_file,
            sequence=1,
            bank_id="260",
            bank_name="Nubank",
            branch_id="0001",
            account_id="530540-6",
            account_type="CHECKING",
            currency="BRL",
            matched_bank=self.bank,
            matched_account=self.account,
            match_method=ImportStatement.MatchMethod.AUTOMATIC,
        )
        item = ImportItem.objects.create(
            statement=statement,
            sequence=sequence,
            fitid=f"OFX-{sequence}",
            posted_at=self.posted_at,
            posted_at_raw="20260220000000",
            posted_at_has_time=False,
            signed_amount=Decimal("10.00"),
            amount=Decimal("10.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            ofx_transaction_type="CREDIT",
            raw_description="Transferência Recebida - JOAO",
            fingerprint=("b" * 63) + str(sequence % 10),
            classification=ImportItem.Classification.NEW,
            resolution=ImportItem.Resolution.IMPORT,
            commit_status=ImportItem.CommitStatus.CREATED,
        )
        return batch, item

    def _transaction(self, *, source_type, fitid, posted_at=None, description="Transferência Recebida - JOAO"):
        return Transaction.objects.create(
            account=self.account,
            posted_at=posted_at or self.posted_at,
            competence_date=(posted_at or self.posted_at).date(),
            amount=Decimal("10.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=source_type,
            fitid=fitid,
            raw_description=description,
            normalized_description=description,
            fingerprint="c" * 64 if source_type == Transaction.SourceType.OFX else "d" * 64,
            fingerprint_version=2,
            raw_data={"provider": "PLUGGY"} if source_type == Transaction.SourceType.API else {"ofx": True},
            created_by=self.user,
        )

    def _created_effect(self, item, tx):
        item.imported_transaction = tx
        item.save(update_fields=["imported_transaction"])
        return ImportEffect.objects.create(
            import_item=item,
            transaction=tx,
            action=ImportEffect.Action.CREATED,
            before_data={},
            after_data=transaction_snapshot(tx),
        )

    def test_cleanup_prefers_pluggy_and_archives_original_ofx(self):
        batch, item = self._batch_item()
        ofx_tx = self._transaction(
            source_type=Transaction.SourceType.OFX,
            fitid="OFX-1",
        )
        self._created_effect(item, ofx_tx)
        pluggy_tx = self._transaction(
            source_type=Transaction.SourceType.API,
            fitid="PLUGGY:remote-1",
            posted_at=timezone.make_aware(datetime(2026, 2, 20, 8, 55)),
            description="Transferência Recebida|JOAO",
        )
        pluggy_tx.is_financially_ignored = True
        pluggy_tx.canonical_transaction = ofx_tx
        pluggy_tx.ignored_reason = f"Duplicidade revisada; mantida movimentação #{ofx_tx.pk}."
        pluggy_tx.save(update_fields=["is_financially_ignored", "canonical_transaction", "ignored_reason"])

        first, second = sorted((ofx_tx, pluggy_tx), key=lambda tx: tx.pk)
        TransactionDuplicateReview.objects.create(
            first_transaction=first,
            second_transaction=second,
            classification=TransactionDuplicateReview.Classification.EXACT,
            confidence=93,
            match_reasons=["Mesmo banco, natureza e valor", "Mesma data"],
        )

        plan = build_ofx_cleanup_plan(batch_ids=[batch.pk], confidence_min=90)
        self.assertEqual(plan.entries[0].category, CATEGORY_PLUGGY_DUPLICATE)

        result = execute_ofx_cleanup(
            user=self.user,
            batch_ids=[batch.pk],
            confidence_min=90,
        )

        self.assertEqual(result.ofx_transactions_deleted, 1)
        self.assertEqual(result.pluggy_transactions_reactivated, 1)
        self.assertFalse(Transaction.objects.filter(pk=ofx_tx.pk).exists())
        pluggy_tx.refresh_from_db()
        self.assertFalse(pluggy_tx.is_financially_ignored)
        self.assertEqual(timezone.localtime(pluggy_tx.posted_at).hour, 8)
        batch.refresh_from_db()
        self.assertIsNotNone(batch.cleanup_archived_at)
        self.assertEqual(batch.cleanup_archived_by, self.user)
        self.assertTrue(batch.files.filter(file__isnull=False).exists())

    def test_historical_snapshot_with_local_offset_is_not_false_modification(self):
        batch, item = self._batch_item(sequence=6)
        tx = self._transaction(source_type=Transaction.SourceType.OFX, fitid="OFX-6")
        effect = self._created_effect(item, tx)
        historical = dict(effect.after_data)
        historical["posted_at"] = self.posted_at.isoformat()
        effect.after_data = historical
        effect.save(update_fields=["after_data"])

        plan = build_ofx_cleanup_plan(batch_ids=[batch.pk])

        self.assertEqual(plan.entries[0].category, CATEGORY_DIRECT_UNIQUE)
        self.assertFalse(plan.entries[0].differences)

    def test_modified_unique_ofx_is_preserved(self):
        batch, item = self._batch_item(sequence=2)
        tx = self._transaction(source_type=Transaction.SourceType.OFX, fitid="OFX-2")
        effect = self._created_effect(item, tx)
        tx.notes = "Classificação manual posterior"
        tx.save(update_fields=["notes", "updated_at"])

        plan = build_ofx_cleanup_plan(batch_ids=[batch.pk])
        self.assertEqual(plan.entries[0].category, CATEGORY_MODIFIED_UNIQUE)
        self.assertTrue(plan.entries[0].differences)

        result = execute_ofx_cleanup(user=self.user, batch_ids=[batch.pk])
        self.assertEqual(result.skipped_modified_unique, 1)
        self.assertTrue(Transaction.objects.filter(pk=tx.pk).exists())
        effect.refresh_from_db()
        self.assertIsNone(effect.reverted_at)
        batch.refresh_from_db()
        self.assertIsNone(batch.cleanup_archived_at)

    def test_modified_unique_can_be_deleted_explicitly_with_snapshot_preserved(self):
        batch, item = self._batch_item(sequence=5)
        tx = self._transaction(source_type=Transaction.SourceType.OFX, fitid="OFX-5")
        effect = self._created_effect(item, tx)
        tx.notes = "Ajuste manual importante"
        tx.save(update_fields=["notes", "updated_at"])

        result = execute_ofx_cleanup(
            user=self.user,
            batch_ids=[batch.pk],
            delete_modified_unique_ofx=True,
        )
        self.assertEqual(result.modified_unique_deleted, 1)
        self.assertFalse(Transaction.objects.filter(pk=tx.pk).exists())
        effect.refresh_from_db()
        self.assertIsNotNone(effect.reverted_at)
        self.assertEqual(
            effect.cleanup_data["current_before_cleanup"]["notes"],
            "Ajuste manual importante",
        )

    def test_unique_unmodified_ofx_requires_explicit_opt_in(self):
        batch, item = self._batch_item(sequence=3)
        tx = self._transaction(source_type=Transaction.SourceType.OFX, fitid="OFX-3")
        effect = self._created_effect(item, tx)

        plan = build_ofx_cleanup_plan(batch_ids=[batch.pk])
        self.assertEqual(plan.entries[0].category, CATEGORY_DIRECT_UNIQUE)

        execute_ofx_cleanup(user=self.user, batch_ids=[batch.pk], delete_unique_ofx=False)
        self.assertTrue(Transaction.objects.filter(pk=tx.pk).exists())
        effect.refresh_from_db()
        self.assertIsNone(effect.reverted_at)

        result = execute_ofx_cleanup(user=self.user, batch_ids=[batch.pk], delete_unique_ofx=True)
        self.assertEqual(result.unique_ofx_deleted, 1)
        self.assertFalse(Transaction.objects.filter(pk=tx.pk).exists())

    def test_updated_effect_three_way_revert_preserves_later_manual_edit(self):
        batch, item = self._batch_item(sequence=4)
        tx = self._transaction(
            source_type=Transaction.SourceType.API,
            fitid="PLUGGY:existing-1",
            posted_at=timezone.make_aware(datetime(2026, 2, 20, 8, 55)),
            description="Descrição Pluggy original",
        )
        before = transaction_snapshot(tx)
        tx.source_type = Transaction.SourceType.OFX
        tx.fitid = "OFX-4"
        tx.posted_at = self.posted_at
        tx.raw_description = "Descrição OFX"
        tx.save(update_fields=["source_type", "fitid", "posted_at", "raw_description", "updated_at"])
        after = transaction_snapshot(tx)
        item.commit_status = ImportItem.CommitStatus.UPDATED
        item.imported_transaction = tx
        item.save(update_fields=["commit_status", "imported_transaction"])
        ImportEffect.objects.create(
            import_item=item,
            transaction=tx,
            action=ImportEffect.Action.UPDATED,
            before_data=before,
            after_data=after,
        )
        tx.raw_description = "Descrição editada manualmente depois"
        tx.save(update_fields=["raw_description", "updated_at"])

        plan = build_ofx_cleanup_plan(batch_ids=[batch.pk])
        self.assertEqual(plan.entries[0].category, CATEGORY_UPDATED_REVERT)

        result = execute_ofx_cleanup(user=self.user, batch_ids=[batch.pk])
        self.assertEqual(result.transactions_restored, 1)
        tx.refresh_from_db()
        self.assertEqual(tx.source_type, Transaction.SourceType.API)
        self.assertTrue(tx.fitid.startswith("PLUGGY:"))
        self.assertEqual(timezone.localtime(tx.posted_at).hour, 8)
        self.assertEqual(tx.raw_description, "Descrição editada manualmente depois")

    def test_cleanup_page_requires_login(self):
        response = self.client.get("/imports/ofx-cleanup/")
        self.assertEqual(response.status_code, 302)
