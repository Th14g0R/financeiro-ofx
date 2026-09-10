from datetime import timedelta
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

class TransactionDuplicateGroupingRegressionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="duplicate-group-reviewer",
            password="Senha-Muito-Forte-123!",
        )
        self.bank = Bank.objects.create(name="Nubank Group", code="269")
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Nubank",
            branch="0001",
            number="530540",
            digit="6",
        )
        self.posted_at = timezone.now().replace(hour=14, minute=0, second=0, microsecond=0)

    def _tx(self, *, fitid, description, source=Transaction.SourceType.API):
        return Transaction.objects.create(
            account=self.account,
            posted_at=self.posted_at,
            competence_date=self.posted_at.date(),
            amount=Decimal("15.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.TRANSFER,
            source_type=source,
            fitid=fitid,
            raw_description=description,
        )

    def test_same_source_distinct_people_do_not_become_duplicate_candidates(self):
        first = self._tx(
            fitid="PLUGGY:first",
            description="Transferência Recebida|Murilo Feitosa Dantas",
        )
        second = self._tx(
            fitid="PLUGGY:second",
            description="Transferência Recebida|José Davi Silva de Oliveira",
        )

        analyze_duplicates(transaction_ids=[first.pk, second.pk])

        self.assertFalse(TransactionDuplicateReview.objects.exists())

    def test_pending_graph_is_grouped_and_transaction_appears_once(self):
        from services.duplicates import build_duplicate_review_groups

        first = self._tx(fitid="A", description="Transferência Recebida|Pessoa A", source=Transaction.SourceType.OFX)
        second = self._tx(fitid="B", description="Transferência Recebida|Pessoa A")
        third = self._tx(fitid="C", description="Transferência Recebida|Pessoa A")
        review1 = TransactionDuplicateReview.objects.create(
            first_transaction=first,
            second_transaction=second,
            classification=TransactionDuplicateReview.Classification.EXACT,
            confidence=100,
            match_reasons=["Teste"],
        )
        review2 = TransactionDuplicateReview.objects.create(
            first_transaction=first,
            second_transaction=third,
            classification=TransactionDuplicateReview.Classification.EXACT,
            confidence=100,
            match_reasons=["Teste"],
        )

        groups = build_duplicate_review_groups([review1, review2])

        self.assertEqual(len(groups), 1)
        self.assertEqual({tx.pk for tx in groups[0].transactions}, {first.pk, second.pk, third.pk})
        self.assertEqual(len(groups[0].transactions), 3)

    def test_group_resolution_ignores_each_noncanonical_transaction_once(self):
        from services.duplicates import review_duplicate_group

        canonical = self._tx(
            fitid="OFX-CANONICAL",
            description="Transferência Recebida|Pessoa A",
            source=Transaction.SourceType.OFX,
        )
        second = self._tx(fitid="PLUGGY:2", description="Transferência Recebida|Pessoa A")
        third = self._tx(fitid="PLUGGY:3", description="Transferência Recebida|Pessoa A")
        review1 = TransactionDuplicateReview.objects.create(
            first_transaction=canonical,
            second_transaction=second,
            classification=TransactionDuplicateReview.Classification.EXACT,
            confidence=100,
            match_reasons=["Teste"],
        )
        TransactionDuplicateReview.objects.create(
            first_transaction=canonical,
            second_transaction=third,
            classification=TransactionDuplicateReview.Classification.EXACT,
            confidence=100,
            match_reasons=["Teste"],
        )

        result = review_duplicate_group(
            review1.pk,
            action="keep_one",
            canonical_transaction_id=canonical.pk,
            user=self.user,
        )

        canonical.refresh_from_db()
        second.refresh_from_db()
        third.refresh_from_db()
        self.assertEqual(result["transactions"], 3)
        self.assertFalse(canonical.is_financially_ignored)
        self.assertTrue(second.is_financially_ignored)
        self.assertTrue(third.is_financially_ignored)
        self.assertEqual(second.canonical_transaction_id, canonical.pk)
        self.assertEqual(third.canonical_transaction_id, canonical.pk)
        self.assertFalse(
            TransactionDuplicateReview.objects.filter(
                status=TransactionDuplicateReview.Status.PENDING
            ).exists()
        )

class TransactionDuplicateStaleSuggestionTests(TestCase):
    def setUp(self):
        self.password = "Senha-Muito-Forte-123!"
        self.user = get_user_model().objects.create_user(
            username="duplicate-stale-reviewer",
            password=self.password,
        )
        self.client.force_login(self.user)
        self.bank = Bank.objects.create(name="Banco Stale", code="268")
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Principal",
            branch="1",
            number="900",
        )
        self.when = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)

    def _tx(self, fitid, description):
        return Transaction.objects.create(
            account=self.account,
            posted_at=self.when,
            competence_date=self.when.date(),
            amount=Decimal("15.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.TRANSFER,
            source_type=Transaction.SourceType.API,
            fitid=fitid,
            raw_description=description,
        )

    def test_full_analysis_removes_old_false_pair_and_releases_quarantine(self):
        first = self._tx("PLUGGY:OLD-1", "Transferência Recebida|Murilo Feitosa Dantas")
        second = self._tx("PLUGGY:OLD-2", "Transferência Recebida|José Davi Silva de Oliveira")
        TransactionDuplicateReview.objects.create(
            first_transaction=first,
            second_transaction=second,
            classification=TransactionDuplicateReview.Classification.POSSIBLE,
            confidence=78,
            match_reasons=["Regra antiga"],
        )
        second.is_financially_ignored = True
        second.ignored_reason = f"Aguardando revisão de duplicidade provável com movimentação #{first.pk}."
        second.canonical_transaction = first
        second.save(
            update_fields=[
                "is_financially_ignored",
                "ignored_reason",
                "canonical_transaction",
                "updated_at",
            ]
        )

        analyze_duplicates()

        self.assertFalse(TransactionDuplicateReview.objects.exists())
        second.refresh_from_db()
        self.assertFalse(second.is_financially_ignored)
        self.assertEqual(second.ignored_reason, "")
        self.assertIsNone(second.canonical_transaction_id)

    def test_bulk_filter_does_not_resolve_lower_confidence_edges_in_same_group(self):
        first = self._tx("A", "Transferência Recebida|Pessoa Um")
        second = Transaction.objects.create(
            account=self.account,
            posted_at=self.when,
            competence_date=self.when.date(),
            amount=Decimal("15.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.TRANSFER,
            source_type=Transaction.SourceType.OFX,
            fitid="B",
            raw_description="Transferência Recebida|Pessoa Um",
        )
        third = Transaction.objects.create(
            account=self.account,
            posted_at=self.when,
            competence_date=self.when.date(),
            amount=Decimal("15.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.PDF,
            fitid="C",
            raw_description="Transferência Recebida|Pessoa Um",
        )
        high = TransactionDuplicateReview.objects.create(
            first_transaction=min(first, second, key=lambda tx: tx.pk),
            second_transaction=max(first, second, key=lambda tx: tx.pk),
            classification=TransactionDuplicateReview.Classification.EXACT,
            confidence=100,
            match_reasons=["Alta"],
        )
        low_first, low_second = sorted((second, third), key=lambda tx: tx.pk)
        low = TransactionDuplicateReview.objects.create(
            first_transaction=low_first,
            second_transaction=low_second,
            classification=TransactionDuplicateReview.Classification.POSSIBLE,
            confidence=78,
            match_reasons=["Baixa"],
        )

        response = self.client.post(
            "/finance/transactions/duplicates/bulk/",
            {
                "action": "keep_all",
                "current_password": self.password,
                "apply_all_filtered": "1",
                "status": "pending",
                "confidence_min": "100",
                "confidence_max": "100",
            },
        )

        self.assertEqual(response.status_code, 302)
        high.refresh_from_db()
        low.refresh_from_db()
        self.assertEqual(high.status, TransactionDuplicateReview.Status.PENDING)
        self.assertEqual(low.status, TransactionDuplicateReview.Status.PENDING)

class TransactionDuplicatePairGuardTests(TestCase):
    def test_pairwise_decision_is_blocked_when_transaction_belongs_to_group(self):
        user = get_user_model().objects.create_user(username="pair-guard", password="safe-pass-123")
        bank = Bank.objects.create(name="Banco Pair Guard", code="267")
        account = Account.objects.create(bank=bank, nickname="Conta", branch="1", number="777")
        when = timezone.now()
        transactions = [
            Transaction.objects.create(
                account=account,
                posted_at=when,
                competence_date=when.date(),
                amount=Decimal("10.00"),
                direction=Transaction.Direction.CREDIT,
                transaction_type=Transaction.TransactionType.TRANSFER,
                source_type=source,
                fitid=f"GUARD-{index}",
                raw_description="Transferência Recebida|Pessoa Guard",
            )
            for index, source in enumerate(
                [Transaction.SourceType.OFX, Transaction.SourceType.API, Transaction.SourceType.PDF],
                start=1,
            )
        ]
        first = TransactionDuplicateReview.objects.create(
            first_transaction=transactions[0],
            second_transaction=transactions[1],
            classification=TransactionDuplicateReview.Classification.EXACT,
            confidence=100,
            match_reasons=["Teste"],
        )
        TransactionDuplicateReview.objects.create(
            first_transaction=transactions[0],
            second_transaction=transactions[2],
            classification=TransactionDuplicateReview.Classification.EXACT,
            confidence=100,
            match_reasons=["Teste"],
        )

        with self.assertRaisesRegex(ValueError, "grupo completo"):
            review_duplicate_pair(first, action="keep_second", user=user)

class TransactionDuplicateGroupingViewTests(TestCase):
    def setUp(self):
        self.password = "Senha-Muito-Forte-123!"
        self.user = get_user_model().objects.create_user(
            username="duplicate-group-viewer",
            password=self.password,
        )
        self.client.force_login(self.user)
        self.bank = Bank.objects.create(name="Banco Group View", code="266")
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Principal",
            branch="0001",
            number="123456",
            digit="7",
        )
        self.when = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)

    def _tx(self, *, source, fitid, description="Transferência Recebida|Pessoa Teste"):
        return Transaction.objects.create(
            account=self.account,
            posted_at=self.when,
            competence_date=self.when.date(),
            amount=Decimal("25.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.TRANSFER,
            source_type=source,
            fitid=fitid,
            raw_description=description,
        )

    def test_pending_list_renders_connected_component_as_one_group(self):
        first = self._tx(source=Transaction.SourceType.OFX, fitid="OFX-GROUP-1")
        second = self._tx(source=Transaction.SourceType.API, fitid="PLUGGY:GROUP-2")
        third = self._tx(source=Transaction.SourceType.PDF, fitid="PDF-GROUP-3")
        TransactionDuplicateReview.objects.create(
            first_transaction=first,
            second_transaction=second,
            classification=TransactionDuplicateReview.Classification.EXACT,
            confidence=100,
            match_reasons=["Teste"],
        )
        TransactionDuplicateReview.objects.create(
            first_transaction=first,
            second_transaction=third,
            classification=TransactionDuplicateReview.Classification.POSSIBLE,
            confidence=88,
            match_reasons=["Teste"],
        )

        response = self.client.get("/finance/transactions/duplicates/")

        self.assertEqual(response.status_code, 200)
        groups = list(response.context["groups"])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].transaction_count, 3)
        self.assertEqual(groups[0].pair_count, 2)
        self.assertTrue(groups[0].fully_matches_filter)

    def test_confidence_filter_marks_partial_component_as_not_bulk_eligible(self):
        first = self._tx(source=Transaction.SourceType.OFX, fitid="OFX-FILTER-1")
        second = self._tx(source=Transaction.SourceType.API, fitid="PLUGGY:FILTER-2")
        third = self._tx(source=Transaction.SourceType.PDF, fitid="PDF-FILTER-3")
        TransactionDuplicateReview.objects.create(
            first_transaction=first,
            second_transaction=second,
            classification=TransactionDuplicateReview.Classification.EXACT,
            confidence=100,
            match_reasons=["Alta"],
        )
        TransactionDuplicateReview.objects.create(
            first_transaction=first,
            second_transaction=third,
            classification=TransactionDuplicateReview.Classification.POSSIBLE,
            confidence=78,
            match_reasons=["Baixa"],
        )

        response = self.client.get(
            "/finance/transactions/duplicates/",
            {"confidence_min": "100", "confidence_max": "100"},
        )

        self.assertEqual(response.status_code, 200)
        groups = list(response.context["groups"])
        self.assertEqual(len(groups), 1)
        self.assertFalse(groups[0].fully_matches_filter)


class TransactionDuplicateCanonicalReactivationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="duplicate-reactivation-user",
            password="Senha-Muito-Forte-123!",
        )
        self.bank = Bank.objects.create(name="Banco Reactivation", code="265")
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Conta",
            branch="0001",
            number="98765",
            digit="4",
        )
        self.when = timezone.now().replace(hour=9, minute=15, second=0, microsecond=0)

    def _tx(self, *, source, fitid):
        return Transaction.objects.create(
            account=self.account,
            posted_at=self.when,
            competence_date=self.when.date(),
            amount=Decimal("19.90"),
            direction=Transaction.Direction.DEBIT,
            transaction_type=Transaction.TransactionType.OTHER,
            source_type=source,
            fitid=fitid,
            raw_description="Compra teste estabelecimento",
        )

    def test_keep_quarantined_second_reactivates_selected_canonical_transaction(self):
        original = self._tx(source=Transaction.SourceType.OFX, fitid="OFX-REACTIVATE")
        pluggy = self._tx(source=Transaction.SourceType.API, fitid="PLUGGY:REACTIVATE")
        analyze_duplicates(transaction_ids=[pluggy.pk], quarantine_new=True)
        review = TransactionDuplicateReview.objects.get()
        pluggy.refresh_from_db()
        self.assertTrue(pluggy.is_financially_ignored)

        review_duplicate_pair(review, action="keep_second", user=self.user)

        original.refresh_from_db()
        pluggy.refresh_from_db()
        self.assertTrue(original.is_financially_ignored)
        self.assertFalse(pluggy.is_financially_ignored)
        self.assertIsNone(pluggy.canonical_transaction_id)

    def test_pluggy_and_other_api_are_treated_as_different_source_families(self):
        legacy_api = self._tx(source=Transaction.SourceType.API, fitid="MERCADOPAGO:LEGACY-1")
        pluggy = self._tx(source=Transaction.SourceType.API, fitid="PLUGGY:CROSS-API-2")

        analyze_duplicates(transaction_ids=[pluggy.pk])

        review = TransactionDuplicateReview.objects.get()
        self.assertGreaterEqual(review.confidence, 72)
        self.assertIn("Mesma operação em origens diferentes", review.match_reasons)


class TransactionDuplicateStrictDateTests(TestCase):
    def setUp(self):
        self.bank = Bank.objects.create(name="Banco Data Estrita", code="264")
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Principal",
            branch="0001",
            number="123456",
            digit="7",
        )
        self.when = timezone.now().replace(hour=9, minute=44, second=0, microsecond=0)

    def _tx(self, *, when, source, fitid, description):
        return Transaction.objects.create(
            account=self.account,
            posted_at=when,
            competence_date=timezone.localtime(when).date(),
            amount=Decimal("0.50"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.INTEREST,
            source_type=source,
            fitid=fitid,
            raw_description=description,
        )

    def test_equal_value_and_description_on_different_dates_are_not_duplicates(self):
        first = self._tx(
            when=self.when,
            source=Transaction.SourceType.OFX,
            fitid="OFX-CDI-1",
            description="Rendimento CDI",
        )
        second = self._tx(
            when=self.when + timedelta(days=1),
            source=Transaction.SourceType.API,
            fitid="PLUGGY:CDI-2",
            description="Rendimento CDI",
        )

        analyze_duplicates(transaction_ids=[second.pk])

        self.assertFalse(
            TransactionDuplicateReview.objects.filter(
                first_transaction_id=min(first.pk, second.pk),
                second_transaction_id=max(first.pk, second.pk),
            ).exists()
        )

    def test_same_date_and_same_time_are_positive_duplicate_evidence(self):
        from services.duplicates.matcher import score_pair

        first = self._tx(
            when=self.when,
            source=Transaction.SourceType.OFX,
            fitid="OFX-SAME-TIME",
            description="Transferência Recebida José da Silva",
        )
        second = self._tx(
            when=self.when,
            source=Transaction.SourceType.API,
            fitid="PLUGGY:SAME-TIME",
            description="Transferência Recebida|José da Silva",
        )

        score, reasons = score_pair(first, second)

        self.assertGreaterEqual(score, 90)
        self.assertIn("Mesma data", reasons)
        # O OFX deste teste não marca explicitamente ausência de horário,
        # portanto 09:44 é tratado como horário real.
        self.assertIn("Mesmo horário", reasons)

    def test_precise_times_more_than_one_hour_apart_are_not_duplicates(self):
        from services.duplicates.matcher import score_pair

        first = self._tx(
            when=self.when,
            source=Transaction.SourceType.PDF,
            fitid="PDF-TIME-1",
            description="Transferência Recebida|José da Silva",
        )
        second = self._tx(
            when=self.when + timedelta(hours=2, minutes=1),
            source=Transaction.SourceType.API,
            fitid="PLUGGY:TIME-2",
            description="Transferência Recebida|José da Silva",
        )

        score, reasons = score_pair(first, second)

        self.assertEqual(score, 0)
        self.assertEqual(reasons, [])
