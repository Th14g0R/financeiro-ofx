from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from finance.models import Account
from finance.models import Bank
from finance.models import Transaction
from imports.models import ImportBatch
from imports.models import ImportFile
from imports.models import ImportItem
from services.importing import commit_batch
from services.importing import create_and_assign_account_from_ofx
from services.importing import delete_batch
from services.importing import reprocess_batch
from services.importing import rollback_batch
from services.importing import suggested_account_values
from services.importing import stage_uploaded_file
from services.ofx.models import ParsedOfxFile
from services.ofx.models import ParsedStatement
from services.ofx.models import ParsedTransaction


class ImportFlowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._media_dir = tempfile.TemporaryDirectory()
        cls._media_override = override_settings(
            MEDIA_ROOT=cls._media_dir.name
        )
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        cls._media_dir.cleanup()

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="importer",
            password="safe-password-123",
        )

        self.bank = Bank.objects.create(
            name="Banco Importação",
            code="777",
            ofx_bank_id="777",
        )

        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Principal",
            branch="0001",
            number="123456",
            ofx_account_id="123456",
        )

        self.posted_at = timezone.make_aware(
            datetime(2026, 9, 3, 12, 0)
        )

    def parsed_file(
        self,
        *,
        fitid="FIT-001",
        amount=Decimal("500.00"),
        memo="PIX RECEBIDO JOAO",
    ):
        return ParsedOfxFile(
            version=1,
            encoding="cp1252",
            statements=(
                ParsedStatement(
                    bank_id="777",
                    bank_name="Banco Importação",
                    branch_id="0001",
                    account_id="123456",
                    account_type="CHECKING",
                    currency="BRL",
                    start=self.posted_at,
                    end=self.posted_at,
                    ledger_balance=Decimal("500.00"),
                    transactions=(
                        ParsedTransaction(
                            fitid=fitid,
                            posted_at=self.posted_at,
                            amount=amount,
                            transaction_type="CREDIT",
                            memo=memo,
                            payee="",
                            checknum="",
                            reference="",
                            raw={
                                "fitid": fitid,
                                "amount": str(amount),
                                "memo": memo,
                            },
                        ),
                    ),
                ),
            ),
        )

    def upload(self, name="extrato.ofx"):
        return SimpleUploadedFile(
            name,
            b"OFXHEADER:100\n<OFX>TESTE</OFX>",
            content_type="application/octet-stream",
        )

    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_new_item_is_staged_and_committed(self, parse_bytes):
        parse_bytes.return_value = self.parsed_file()

        batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=batch,
            uploaded_file=self.upload(),
        )

        item = ImportItem.objects.get()

        self.assertEqual(
            item.classification,
            ImportItem.Classification.NEW,
        )

        result = commit_batch(
            batch=batch,
            user=self.user,
        )

        self.assertEqual(result["created"], 1)

        transaction = Transaction.objects.get()

        self.assertEqual(
            transaction.source_type,
            Transaction.SourceType.OFX,
        )
        self.assertEqual(
            transaction.amount,
            Decimal("500.00"),
        )
        self.assertEqual(
            transaction.direction,
            Transaction.Direction.CREDIT,
        )

    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_same_fitid_same_values_is_duplicate(self, parse_bytes):
        Transaction.objects.create(
            account=self.account,
            posted_at=self.posted_at,
            competence_date=self.posted_at.date(),
            amount=Decimal("500.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.OFX,
            fitid="FIT-001",
            raw_description="PIX RECEBIDO JOAO",
        )

        parse_bytes.return_value = self.parsed_file()

        batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=batch,
            uploaded_file=self.upload(),
        )

        item = ImportItem.objects.get()

        self.assertEqual(
            item.classification,
            ImportItem.Classification.DUPLICATE,
        )

    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_same_fitid_different_description_is_divergent(
        self,
        parse_bytes,
    ):
        Transaction.objects.create(
            account=self.account,
            posted_at=self.posted_at,
            competence_date=self.posted_at.date(),
            amount=Decimal("500.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.OFX,
            fitid="FIT-001",
            raw_description="PIX JOAO",
        )

        parse_bytes.return_value = self.parsed_file(
            memo="PIX RECEBIDO JOAO DA SILVA",
        )

        batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=batch,
            uploaded_file=self.upload(),
        )

        item = ImportItem.objects.get()

        self.assertEqual(
            item.classification,
            ImportItem.Classification.DIVERGENT,
        )
        self.assertIn(
            "raw_description",
            item.divergence_fields,
        )

    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_divergent_item_can_update_existing_transaction(
        self,
        parse_bytes,
    ):
        existing = Transaction.objects.create(
            account=self.account,
            posted_at=self.posted_at,
            competence_date=self.posted_at.date(),
            amount=Decimal("500.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.OFX,
            fitid="FIT-001",
            raw_description="PIX JOAO",
        )

        parse_bytes.return_value = self.parsed_file(
            memo="PIX RECEBIDO JOAO DA SILVA",
        )

        batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=batch,
            uploaded_file=self.upload(),
        )

        item = ImportItem.objects.get()

        commit_batch(
            batch=batch,
            user=self.user,
            divergent_resolutions={
                item.pk: ImportItem.Resolution.UPDATE,
            },
        )

        existing.refresh_from_db()

        self.assertEqual(
            existing.raw_description,
            "PIX RECEBIDO JOAO DA SILVA",
        )

    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_exact_file_already_imported_is_marked_duplicate_file(
        self,
        parse_bytes,
    ):
        parse_bytes.return_value = self.parsed_file()

        first_batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        first_file = stage_uploaded_file(
            batch=first_batch,
            uploaded_file=self.upload(),
        )

        first_file.status = ImportFile.Status.IMPORTED
        first_file.save(update_fields=["status"])

        second_batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        second_file = stage_uploaded_file(
            batch=second_batch,
            uploaded_file=self.upload(),
        )

        self.assertEqual(
            second_file.status,
            ImportFile.Status.DUPLICATE_FILE,
        )
        self.assertEqual(
            second_file.duplicate_of,
            first_file,
        )

    def test_upload_page_requires_authentication(self):
        response = self.client.get(
            reverse("imports:upload")
        )

        self.assertEqual(response.status_code, 302)

    def test_upload_page_opens_when_authenticated(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("imports:upload")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Importar extrato",
        )



class ImportRollbackAndEditingTests(ImportFlowTests):
    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_rollback_removes_transaction_created_by_batch(
        self,
        parse_bytes,
    ):
        parse_bytes.return_value = self.parsed_file()

        batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=batch,
            uploaded_file=self.upload(),
        )

        commit_batch(
            batch=batch,
            user=self.user,
        )

        self.assertEqual(
            Transaction.objects.count(),
            1,
        )

        rollback_batch(batch)

        self.assertEqual(
            Transaction.objects.count(),
            0,
        )

    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_rollback_restores_transaction_updated_by_batch(
        self,
        parse_bytes,
    ):
        existing = Transaction.objects.create(
            account=self.account,
            posted_at=self.posted_at,
            competence_date=self.posted_at.date(),
            amount=Decimal("500.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.OFX,
            fitid="FIT-001",
            raw_description="PIX JOAO",
        )

        parse_bytes.return_value = self.parsed_file(
            memo="PIX RECEBIDO JOAO DA SILVA",
        )

        batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=batch,
            uploaded_file=self.upload(),
        )

        item = ImportItem.objects.get(
            statement__import_file__batch=batch
        )

        commit_batch(
            batch=batch,
            user=self.user,
            divergent_resolutions={
                item.pk: ImportItem.Resolution.UPDATE,
            },
        )

        existing.refresh_from_db()

        self.assertEqual(
            existing.raw_description,
            "PIX RECEBIDO JOAO DA SILVA",
        )

        rollback_batch(batch)

        existing.refresh_from_db()

        self.assertEqual(
            existing.raw_description,
            "PIX JOAO",
        )

    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_delete_batch_removes_created_transactions(
        self,
        parse_bytes,
    ):
        parse_bytes.return_value = self.parsed_file()

        batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=batch,
            uploaded_file=self.upload(),
        )

        commit_batch(
            batch=batch,
            user=self.user,
        )

        batch_id = batch.pk

        delete_batch(batch)

        self.assertFalse(
            ImportBatch.objects.filter(
                pk=batch_id
            ).exists()
        )
        self.assertEqual(
            Transaction.objects.count(),
            0,
        )

    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_reprocess_batch_recreates_staging_without_committing(
        self,
        parse_bytes,
    ):
        parse_bytes.return_value = self.parsed_file()

        batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=batch,
            uploaded_file=self.upload(),
        )

        commit_batch(
            batch=batch,
            user=self.user,
        )

        parse_bytes.return_value = self.parsed_file(
            memo="PIX REPROCESSADO",
        )

        reprocess_batch(batch=batch)

        self.assertEqual(
            Transaction.objects.count(),
            0,
        )

        item = ImportItem.objects.get(
            statement__import_file__batch=batch
        )

        self.assertEqual(
            item.raw_description,
            "PIX REPROCESSADO",
        )
        self.assertEqual(
            item.commit_status,
            ImportItem.CommitStatus.PENDING,
        )

    def test_history_page_opens(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("imports:history")
        )

        self.assertEqual(response.status_code, 200)


class CreateAccountFromOfxTests(ImportFlowTests):
    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_can_create_bank_and_account_from_unmatched_statement(
        self,
        parse_bytes,
    ):
        parsed = self.parsed_file()

        parsed = ParsedOfxFile(
            version=parsed.version,
            encoding=parsed.encoding,
            statements=(
                ParsedStatement(
                    bank_id="555",
                    bank_name="Banco Novo OFX",
                    branch_id="4321",
                    account_id="987654",
                    account_type="CHECKING",
                    currency="BRL",
                    start=self.posted_at,
                    end=self.posted_at,
                    ledger_balance=Decimal("500.00"),
                    transactions=parsed.statements[0].transactions,
                ),
            ),
        )

        parse_bytes.return_value = parsed

        batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=batch,
            uploaded_file=self.upload("novo.ofx"),
        )

        statement = batch.files.get().statements.get()

        self.assertIsNone(
            statement.matched_account
        )

        values = suggested_account_values(statement)

        account = create_and_assign_account_from_ofx(
            statement=statement,
            cleaned_data=values,
        )

        self.assertEqual(
            account.bank.ofx_bank_id,
            "555",
        )
        self.assertEqual(
            account.ofx_account_id,
            "987654",
        )

        item = statement.items.get()
        item.refresh_from_db()

        self.assertEqual(
            item.classification,
            ImportItem.Classification.NEW,
        )



class PartialCommitErrorTests(ImportFlowTests):
    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_one_invalid_item_does_not_cancel_other_items(
        self,
        parse_bytes,
    ):
        valid_item = ParsedTransaction(
            fitid="VALID-001",
            posted_at=self.posted_at,
            amount=Decimal("100.00"),
            transaction_type="CREDIT",
            memo="PIX RECEBIDO TESTE",
            payee="",
            checknum="",
            reference="",
            raw={},
        )

        invalid_item = ParsedTransaction(
            fitid="INVALID-001",
            posted_at=self.posted_at,
            amount=Decimal("50.00"),
            transaction_type="CREDIT",
            memo="",
            payee="",
            checknum="",
            reference="",
            raw={},
        )

        parse_bytes.return_value = ParsedOfxFile(
            version=1,
            encoding="utf-8",
            statements=(
                ParsedStatement(
                    bank_id="777",
                    bank_name="Banco Importação",
                    branch_id="0001",
                    account_id="123456",
                    account_type="CHECKING",
                    currency="BRL",
                    start=self.posted_at,
                    end=self.posted_at,
                    ledger_balance=Decimal("150.00"),
                    transactions=(
                        valid_item,
                        invalid_item,
                    ),
                ),
            ),
        )

        batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=batch,
            uploaded_file=self.upload(),
        )

        result = commit_batch(
            batch=batch,
            user=self.user,
        )

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(
            Transaction.objects.count(),
            1,
        )

        failed_item = ImportItem.objects.get(
            fitid="INVALID-001"
        )

        self.assertEqual(
            failed_item.commit_error_code,
            "INVALID_DESCRIPTION",
        )
        self.assertTrue(
            failed_item.commit_error_message
        )
        self.assertEqual(
            failed_item.commit_status,
            ImportItem.CommitStatus.PENDING,
        )

    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_duplicate_inside_same_batch_is_skipped_not_failed(
        self,
        parse_bytes,
    ):
        duplicate_1 = ParsedTransaction(
            fitid="SAME-FITID",
            posted_at=self.posted_at,
            amount=Decimal("75.00"),
            transaction_type="CREDIT",
            memo="PIX DUPLICADO",
            payee="",
            checknum="",
            reference="",
            raw={},
        )

        duplicate_2 = ParsedTransaction(
            fitid="SAME-FITID",
            posted_at=self.posted_at,
            amount=Decimal("75.00"),
            transaction_type="CREDIT",
            memo="PIX DUPLICADO",
            payee="",
            checknum="",
            reference="",
            raw={},
        )

        parse_bytes.return_value = ParsedOfxFile(
            version=1,
            encoding="utf-8",
            statements=(
                ParsedStatement(
                    bank_id="777",
                    bank_name="Banco Importação",
                    branch_id="0001",
                    account_id="123456",
                    account_type="CHECKING",
                    currency="BRL",
                    start=self.posted_at,
                    end=self.posted_at,
                    ledger_balance=Decimal("75.00"),
                    transactions=(
                        duplicate_1,
                        duplicate_2,
                    ),
                ),
            ),
        )

        batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=batch,
            uploaded_file=self.upload(),
        )

        result = commit_batch(
            batch=batch,
            user=self.user,
        )

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(
            Transaction.objects.count(),
            1,
        )

        items = list(
            ImportItem.objects.order_by("sequence")
        )

        self.assertEqual(
            items[1].classification,
            ImportItem.Classification.DUPLICATE,
        )

    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_failed_item_can_be_removed_and_batch_continues(
        self,
        parse_bytes,
    ):
        invalid_item = ParsedTransaction(
            fitid="INVALID-REMOVE",
            posted_at=self.posted_at,
            amount=Decimal("50.00"),
            transaction_type="CREDIT",
            memo="",
            payee="",
            checknum="",
            reference="",
            raw={},
        )

        parse_bytes.return_value = ParsedOfxFile(
            version=1,
            encoding="utf-8",
            statements=(
                ParsedStatement(
                    bank_id="777",
                    bank_name="Banco Importação",
                    branch_id="0001",
                    account_id="123456",
                    account_type="CHECKING",
                    currency="BRL",
                    start=self.posted_at,
                    end=self.posted_at,
                    ledger_balance=Decimal("50.00"),
                    transactions=(invalid_item,),
                ),
            ),
        )

        batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=batch,
            uploaded_file=self.upload(),
        )

        commit_batch(
            batch=batch,
            user=self.user,
        )

        item = ImportItem.objects.get(
            fitid="INVALID-REMOVE"
        )

        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "imports:item-toggle-exclusion",
                args=[batch.pk, item.pk],
            ),
            data={"action": "exclude"},
        )

        self.assertEqual(response.status_code, 302)

        item.refresh_from_db()
        batch.refresh_from_db()

        self.assertTrue(item.is_excluded)
        self.assertEqual(
            item.commit_status,
            ImportItem.CommitStatus.SKIPPED,
        )
        self.assertEqual(
            batch.status,
            ImportBatch.Status.COMMITTED,
        )
        self.assertTrue(
            batch.files.exists()
        )

    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_excluded_item_can_be_restored_to_staging(
        self,
        parse_bytes,
    ):
        invalid_item = ParsedTransaction(
            fitid="RESTORE-001",
            posted_at=self.posted_at,
            amount=Decimal("50.00"),
            transaction_type="CREDIT",
            memo="",
            payee="",
            checknum="",
            reference="",
            raw={},
        )

        parse_bytes.return_value = ParsedOfxFile(
            version=1,
            encoding="utf-8",
            statements=(
                ParsedStatement(
                    bank_id="777",
                    bank_name="Banco Importação",
                    branch_id="0001",
                    account_id="123456",
                    account_type="CHECKING",
                    currency="BRL",
                    start=self.posted_at,
                    end=self.posted_at,
                    ledger_balance=Decimal("50.00"),
                    transactions=(invalid_item,),
                ),
            ),
        )

        batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=batch,
            uploaded_file=self.upload(),
        )

        item = ImportItem.objects.get()

        item.is_excluded = True
        item.commit_status = ImportItem.CommitStatus.SKIPPED
        item.save(
            update_fields=[
                "is_excluded",
                "commit_status",
            ]
        )

        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "imports:item-toggle-exclusion",
                args=[batch.pk, item.pk],
            ),
            data={"action": "restore"},
        )

        self.assertEqual(response.status_code, 302)

        item.refresh_from_db()

        self.assertFalse(item.is_excluded)
        self.assertEqual(
            item.commit_status,
            ImportItem.CommitStatus.PENDING,
        )



class FitidPolicyTests(ImportFlowTests):
    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_same_value_description_date_but_different_fitid_are_distinct(
        self,
        parse_bytes,
    ):
        first = ParsedTransaction(
            fitid="FITID-A",
            posted_at=self.posted_at,
            amount=Decimal("-8.98"),
            transaction_type="DEBIT",
            memo="Compra no débito - VMIT*AT HOME S",
            payee="",
            checknum="",
            reference="",
            raw={},
        )

        second = ParsedTransaction(
            fitid="FITID-B",
            posted_at=self.posted_at,
            amount=Decimal("-8.98"),
            transaction_type="DEBIT",
            memo="Compra no débito - VMIT*AT HOME S",
            payee="",
            checknum="",
            reference="",
            raw={},
        )

        parse_bytes.return_value = ParsedOfxFile(
            version=1,
            encoding="utf-8",
            statements=(
                ParsedStatement(
                    bank_id="777",
                    bank_name="Banco Importação",
                    branch_id="0001",
                    account_id="123456",
                    account_type="CHECKING",
                    currency="BRL",
                    start=self.posted_at,
                    end=self.posted_at,
                    ledger_balance=Decimal("0.00"),
                    transactions=(first, second),
                ),
            ),
        )

        batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=batch,
            uploaded_file=self.upload(),
        )

        staged = list(
            ImportItem.objects.order_by("sequence")
        )

        self.assertEqual(
            staged[0].classification,
            ImportItem.Classification.NEW,
        )
        self.assertEqual(
            staged[1].classification,
            ImportItem.Classification.NEW,
        )

        result = commit_batch(
            batch=batch,
            user=self.user,
        )

        self.assertEqual(result["created"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(
            Transaction.objects.filter(
                fitid__in=["FITID-A", "FITID-B"]
            ).count(),
            2,
        )

    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_missing_fitid_uses_fingerprint_only_as_possible_duplicate(
        self,
        parse_bytes,
    ):
        existing = Transaction.objects.create(
            account=self.account,
            posted_at=self.posted_at,
            competence_date=self.posted_at.date(),
            amount=Decimal("8.98"),
            direction=Transaction.Direction.DEBIT,
            transaction_type=Transaction.TransactionType.OTHER,
            source_type=Transaction.SourceType.OFX,
            fitid="",
            raw_description="Compra no débito - TESTE",
            fingerprint="a" * 64,
        )

        parsed_item = ParsedTransaction(
            fitid="",
            posted_at=self.posted_at,
            amount=Decimal("-8.98"),
            transaction_type="DEBIT",
            memo="Compra no débito - TESTE",
            payee="",
            checknum="",
            reference="",
            raw={},
        )

        parse_bytes.return_value = ParsedOfxFile(
            version=1,
            encoding="utf-8",
            statements=(
                ParsedStatement(
                    bank_id="777",
                    bank_name="Banco Importação",
                    branch_id="0001",
                    account_id="123456",
                    account_type="CHECKING",
                    currency="BRL",
                    start=self.posted_at,
                    end=self.posted_at,
                    ledger_balance=Decimal("0.00"),
                    transactions=(parsed_item,),
                ),
            ),
        )

        batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=batch,
            uploaded_file=self.upload(),
        )

        item = ImportItem.objects.get()

        # O fingerprint do staging é calculado pelo sistema. Para reproduzir
        # a colisão heurística, colocamos o mesmo valor no registro existente.
        existing.fingerprint = item.fingerprint
        existing.save(update_fields=["fingerprint"])

        from services.importing import reclassify_import_item
        reclassify_import_item(item)

        item.refresh_from_db()

        self.assertEqual(
            item.classification,
            ImportItem.Classification.POSSIBLE_DUPLICATE,
        )

        result = commit_batch(
            batch=batch,
            user=self.user,
        )

        self.assertEqual(result["pending_review"], 1)
        self.assertEqual(
            Transaction.objects.count(),
            1,
        )

    @patch("services.statements.parser.OfxBrParser.parse_bytes")
    def test_possible_duplicate_can_be_forced_and_fingerprint_is_not_unique(
        self,
        parse_bytes,
    ):
        parsed_item = ParsedTransaction(
            fitid="",
            posted_at=self.posted_at,
            amount=Decimal("-11.00"),
            transaction_type="DEBIT",
            memo="Compra sem FITID",
            payee="",
            checknum="",
            reference="",
            raw={},
        )

        parse_bytes.return_value = ParsedOfxFile(
            version=1,
            encoding="utf-8",
            statements=(
                ParsedStatement(
                    bank_id="777",
                    bank_name="Banco Importação",
                    branch_id="0001",
                    account_id="123456",
                    account_type="CHECKING",
                    currency="BRL",
                    start=self.posted_at,
                    end=self.posted_at,
                    ledger_balance=Decimal("0.00"),
                    transactions=(parsed_item,),
                ),
            ),
        )

        first_batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=first_batch,
            uploaded_file=self.upload("one.ofx"),
        )

        first_item = ImportItem.objects.get(
            statement__import_file__batch=first_batch
        )

        from services.importing import commit_item

        result = commit_item(
            item=first_item,
            user=self.user,
        )
        self.assertEqual(result["status"], "created")

        second_batch = ImportBatch.objects.create(
            created_by=self.user,
        )

        stage_uploaded_file(
            batch=second_batch,
            uploaded_file=self.upload("two.ofx"),
        )

        second_item = ImportItem.objects.get(
            statement__import_file__batch=second_batch
        )

        self.assertEqual(
            second_item.classification,
            ImportItem.Classification.POSSIBLE_DUPLICATE,
        )

        result = commit_item(
            item=second_item,
            user=self.user,
            force_possible_duplicate=True,
        )

        self.assertEqual(result["status"], "created")
        self.assertEqual(
            Transaction.objects.filter(fitid="").count(),
            2,
        )
