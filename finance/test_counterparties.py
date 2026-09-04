from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from finance.models import Account
from finance.models import Bank
from finance.models import Counterparty
from finance.models import CounterpartyAlias
from finance.models import Transaction
from services.counterparties import analyze_manual_counterparty_merge
from services.counterparties import merge_counterparties_manually
from services.counterparties import rebuild_counterparty_links
from services.counterparties import extract_counterparty_candidate
from services.counterparties import infer_counterparty_kind
from services.counterparties import normalize_identity_text
from services.counterparties import resolve_transaction_counterparty


class CounterpartyParserTests(TestCase):
    def test_extracts_pix_counterparty_name(self):
        candidate = extract_counterparty_candidate(
            (
                "Transferência recebida pelo Pix - "
                "CARLOS EDUARDO VAZQUEZ ABUJDER - "
                "•••.874.032-•• - BCO C6 S.A."
            )
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(
            candidate.name,
            "CARLOS EDUARDO VAZQUEZ ABUJDER",
        )

    def test_normalization_is_case_and_accent_insensitive(self):
        self.assertEqual(
            normalize_identity_text(
                "João da Silva"
            ),
            "JOAO DA SILVA",
        )


    def test_identifies_legal_company_suffix(self):
        self.assertEqual(
            infer_counterparty_kind(
                "AMAZON SERVICOS DE VAREJO DO BRASIL LTDA"
            ),
            Counterparty.Kind.COMPANY,
        )


class CounterpartyResolutionTests(TestCase):
    def setUp(self):
        self.bank = Bank.objects.create(
            name="Banco CP",
            code="611",
        )
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Principal",
            branch="0001",
            number="1111",
        )

    def create_transaction(self, description, fitid):
        return Transaction.objects.create(
            account=self.account,
            posted_at=timezone.now(),
            amount=Decimal("10.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.OFX,
            fitid=fitid,
            raw_description=description,
        )

    def test_same_normalized_person_across_transactions_is_reused(self):
        first = self.create_transaction(
            (
                "Transferência recebida pelo Pix - "
                "João da Silva - •••.123.456-••"
            ),
            "CP-1",
        )
        second = self.create_transaction(
            (
                "Transferência Recebida - "
                "JOAO DA SILVA - •••.123.456-••"
            ),
            "CP-2",
        )

        first_counterparty = resolve_transaction_counterparty(
            first
        )
        second_counterparty = resolve_transaction_counterparty(
            second
        )

        self.assertEqual(
            first_counterparty.pk,
            second_counterparty.pk,
        )
        self.assertEqual(
            Counterparty.objects.count(),
            1,
        )

    def test_manual_alias_can_resolve_future_variant(self):
        counterparty = Counterparty.objects.create(
            display_name="João da Silva",
            normalized_name="JOAO DA SILVA",
            kind=Counterparty.Kind.PERSON,
        )

        CounterpartyAlias.objects.create(
            counterparty=counterparty,
            alias="JOAO SILVA",
            normalized_alias="JOAO SILVA",
            alias_type=CounterpartyAlias.AliasType.NAME,
        )

        transaction = self.create_transaction(
            (
                "Transferência recebida pelo Pix - "
                "João Silva - BANCO TESTE"
            ),
            "CP-ALIAS",
        )

        resolved = resolve_transaction_counterparty(
            transaction
        )

        self.assertEqual(
            resolved.pk,
            counterparty.pk,
        )

    def test_same_name_with_conflicting_masked_identifier_is_not_auto_merged(self):
        first = self.create_transaction(
            (
                "Transferência recebida pelo Pix - "
                "JOAO DA SILVA - •••.123.456-••"
            ),
            "HOMONYM-1",
        )
        second = self.create_transaction(
            (
                "Transferência recebida pelo Pix - "
                "JOAO DA SILVA - •••.999.888-••"
            ),
            "HOMONYM-2",
        )

        first_counterparty = resolve_transaction_counterparty(
            first
        )
        second_counterparty = resolve_transaction_counterparty(
            second
        )

        self.assertNotEqual(
            first_counterparty.pk,
            second_counterparty.pk,
        )
        self.assertEqual(
            Counterparty.objects.count(),
            2,
        )



class FingerprintPolicyDatabaseTests(TestCase):
    def setUp(self):
        self.bank = Bank.objects.create(
            name="Banco Fingerprint",
            code="612",
        )
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Principal",
            branch="0001",
            number="2222",
        )

    def test_same_fingerprint_with_different_fitids_is_allowed(self):
        fingerprint = "f" * 64

        Transaction.objects.create(
            account=self.account,
            posted_at=timezone.now(),
            amount=Decimal("8.98"),
            direction=Transaction.Direction.DEBIT,
            transaction_type=Transaction.TransactionType.OTHER,
            source_type=Transaction.SourceType.OFX,
            fitid="FIT-ONE",
            raw_description="Compra no débito - MESMO LOCAL",
            fingerprint=fingerprint,
        )

        Transaction.objects.create(
            account=self.account,
            posted_at=timezone.now(),
            amount=Decimal("8.98"),
            direction=Transaction.Direction.DEBIT,
            transaction_type=Transaction.TransactionType.OTHER,
            source_type=Transaction.SourceType.OFX,
            fitid="FIT-TWO",
            raw_description="Compra no débito - MESMO LOCAL",
            fingerprint=fingerprint,
        )

        self.assertEqual(
            Transaction.objects.filter(
                fingerprint=fingerprint
            ).count(),
            2,
        )


class CounterpartyViewsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="counterparty-user",
            password="safe-password-123",
        )
        self.client.force_login(self.user)

        self.counterparty = Counterparty.objects.create(
            display_name="João da Silva",
            normalized_name="JOAO DA SILVA",
            kind=Counterparty.Kind.PERSON,
        )

    def test_list_search_is_accent_insensitive(self):
        response = self.client.get(
            reverse("finance:counterparty-list"),
            data={"q": "joao"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "João da Silva",
        )

    def test_detail_ignores_invalid_date_filter(self):
        response = self.client.get(
            reverse(
                "finance:counterparty-detail",
                args=[self.counterparty.pk],
            ),
            data={
                "date_from": "data-invalida",
                "date_to": "outra-data",
            },
        )

        self.assertEqual(response.status_code, 200)


class CounterpartyBankDescriptionRegressionTests(TestCase):
    def test_extracts_banco_do_brasil_pix_with_embedded_date_and_time(self):
        candidate = extract_counterparty_candidate(
            "Pix - Enviado - 29/08 08:37 Livia Alves Mendes",
            transaction_type=Transaction.TransactionType.PIX,
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(
            candidate.name,
            "Livia Alves Mendes",
        )
        self.assertEqual(
            candidate.normalized_name,
            "LIVIA ALVES MENDES",
        )

    def test_extracts_name_from_date_and_installment_legacy_text(self):
        candidate = extract_counterparty_candidate(
            "15/01 FRANCISCA DEIJANE CARVAL 001/011",
            transaction_type=Transaction.TransactionType.PIX,
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(
            candidate.name,
            "FRANCISCA DEIJANE CARVAL",
        )

    def test_extracts_bank_identifier_without_polluting_name(self):
        candidate = extract_counterparty_candidate(
            "46.685.824 ROSENILSON EDUARDO DE SOUSA",
            transaction_type=Transaction.TransactionType.PIX,
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(
            candidate.name,
            "ROSENILSON EDUARDO DE SOUSA",
        )
        self.assertEqual(
            candidate.bank_identifier,
            "46685824",
        )

    def test_plain_and_punctuated_bank_identifier_normalize_equally(self):
        first = extract_counterparty_candidate(
            "46.685.824 ROSENILSON EDUARDO DE SOUSA",
            transaction_type=Transaction.TransactionType.PIX,
        )
        second = extract_counterparty_candidate(
            "46685824 ROSENILSON EDUAR",
            transaction_type=Transaction.TransactionType.PIX,
        )

        self.assertEqual(
            first.bank_identifier,
            second.bank_identifier,
        )

    def test_truncated_bank_name_rule_is_token_prefix_based(self):
        from services.counterparties import truncated_name_equivalent

        self.assertTrue(
            truncated_name_equivalent(
                "FRANCISCA DEIJANE CARVAL",
                "FRANCISCA DEIJANE CARVALHO",
            )
        )
        self.assertTrue(
            truncated_name_equivalent(
                "ROSENILSON EDUAR",
                "ROSENILSON EDUARDO DE SOUSA",
            )
        )
        self.assertTrue(
            truncated_name_equivalent(
                "ANA LUCIA ANASTACIO DA S",
                "ANA LUCIA ANASTACIO DA SILVA",
            )
        )
        self.assertFalse(
            truncated_name_equivalent(
                "JOAO SILVA",
                "JOAO SILVA JUNIOR",
            )
        )


class CounterpartyFullRebuildRegressionTests(TestCase):
    def setUp(self):
        self.bank = Bank.objects.create(
            name="Banco Rebuild CP",
            code="619",
        )
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Principal",
            branch="0001",
            number="9911",
        )

    def create_transaction(
        self,
        description,
        fitid,
        *,
        counterparty=None,
    ):
        return Transaction.objects.create(
            account=self.account,
            posted_at=timezone.now(),
            amount=Decimal("10.00"),
            direction=Transaction.Direction.DEBIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.OFX,
            fitid=fitid,
            raw_description=description,
            counterparty=counterparty,
        )

    def test_rebuild_links_repeated_banco_do_brasil_names(self):
        from django.core.management import call_command

        first = self.create_transaction(
            "Pix - Enviado - 29/08 08:37 Livia Alves Mendes",
            "BB-LIVIA-1",
        )
        second = self.create_transaction(
            "Pix - Enviado - 29/08 08:38 Livia Alves Mendes",
            "BB-LIVIA-2",
        )

        call_command(
            "rebuild_counterparties"
        )

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertIsNotNone(
            first.counterparty_id
        )
        self.assertEqual(
            first.counterparty_id,
            second.counterparty_id,
        )
        self.assertEqual(
            first.counterparty.display_name,
            "Livia Alves Mendes",
        )

    def test_rebuild_merges_date_and_installment_polluted_people(self):
        from django.core.management import call_command

        cp_one = Counterparty.objects.create(
            display_name=(
                "15/01 FRANCISCA DEIJANE CARVAL 001/011"
            ),
            normalized_name=(
                "15 01 FRANCISCA DEIJANE CARVAL 001 011"
            ),
            kind=Counterparty.Kind.PERSON,
        )
        cp_two = Counterparty.objects.create(
            display_name=(
                "15/02 FRANCISCA DEIJANE CARVAL 002/011"
            ),
            normalized_name=(
                "15 02 FRANCISCA DEIJANE CARVAL 002 011"
            ),
            kind=Counterparty.Kind.PERSON,
        )

        first = self.create_transaction(
            "15/01 FRANCISCA DEIJANE CARVAL 001/011",
            "FRAN-1",
            counterparty=cp_one,
        )
        second = self.create_transaction(
            "15/02 FRANCISCA DEIJANE CARVAL 002/011",
            "FRAN-2",
            counterparty=cp_two,
        )

        call_command(
            "rebuild_counterparties"
        )

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertEqual(
            first.counterparty_id,
            second.counterparty_id,
        )
        self.assertEqual(
            first.counterparty.display_name,
            "FRANCISCA DEIJANE CARVAL",
        )
        self.assertEqual(
            Counterparty.objects.filter(
                is_active=True,
                normalized_name=(
                    "FRANCISCA DEIJANE CARVAL"
                ),
            ).count(),
            1,
        )

    def test_rebuild_merges_same_bank_identifier_with_truncated_name(self):
        from django.core.management import call_command

        cp_full = Counterparty.objects.create(
            display_name=(
                "46.685.824 ROSENILSON EDUARDO DE SOUSA"
            ),
            normalized_name=(
                "46 685 824 ROSENILSON EDUARDO DE SOUSA"
            ),
            kind=Counterparty.Kind.PERSON,
        )
        cp_short = Counterparty.objects.create(
            display_name=(
                "46685824 ROSENILSON EDUAR"
            ),
            normalized_name=(
                "46685824 ROSENILSON EDUAR"
            ),
            kind=Counterparty.Kind.PERSON,
        )

        first = self.create_transaction(
            "46.685.824 ROSENILSON EDUARDO DE SOUSA",
            "ROS-1",
            counterparty=cp_full,
        )
        second = self.create_transaction(
            "46685824 ROSENILSON EDUAR",
            "ROS-2",
            counterparty=cp_short,
        )

        call_command(
            "rebuild_counterparties"
        )

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertEqual(
            first.counterparty_id,
            second.counterparty_id,
        )
        self.assertEqual(
            first.counterparty.display_name,
            "ROSENILSON EDUARDO DE SOUSA",
        )
        self.assertTrue(
            first.counterparty.aliases.filter(
                alias_type=(
                    CounterpartyAlias.AliasType.BANK_ID
                ),
                normalized_alias="46685824",
            ).exists()
        )


class CounterpartyRebuildHomonymSafetyTests(TestCase):
    def setUp(self):
        self.bank = Bank.objects.create(
            name="Banco Homonimo Rebuild",
            code="620",
        )
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Principal",
            branch="1",
            number="6200",
        )

    def test_rebuild_keeps_same_name_with_conflicting_pix_identifier_separate(self):
        from django.core.management import call_command

        first_cp = Counterparty.objects.create(
            display_name="JOAO DA SILVA",
            normalized_name="JOAO DA SILVA",
            kind=Counterparty.Kind.PERSON,
        )
        second_cp = Counterparty.objects.create(
            display_name="JOAO DA SILVA",
            normalized_name="JOAO DA SILVA",
            kind=Counterparty.Kind.PERSON,
        )

        CounterpartyAlias.objects.create(
            counterparty=first_cp,
            alias="•••.123.456-••",
            normalized_alias="123 456",
            alias_type=CounterpartyAlias.AliasType.PIX,
        )
        CounterpartyAlias.objects.create(
            counterparty=second_cp,
            alias="•••.999.888-••",
            normalized_alias="999 888",
            alias_type=CounterpartyAlias.AliasType.PIX,
        )

        first = Transaction.objects.create(
            account=self.account,
            posted_at=timezone.now(),
            amount=Decimal("10.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.OFX,
            fitid="HOM-REB-1",
            raw_description=(
                "Transferência recebida pelo Pix - "
                "JOAO DA SILVA - •••.123.456-••"
            ),
            counterparty=first_cp,
        )
        second = Transaction.objects.create(
            account=self.account,
            posted_at=timezone.now(),
            amount=Decimal("11.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.OFX,
            fitid="HOM-REB-2",
            raw_description=(
                "Transferência recebida pelo Pix - "
                "JOAO DA SILVA - •••.999.888-••"
            ),
            counterparty=second_cp,
        )

        call_command(
            "rebuild_counterparties"
        )

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertNotEqual(
            first.counterparty_id,
            second.counterparty_id,
        )
        self.assertEqual(
            Counterparty.objects.filter(
                is_active=True,
                normalized_name="JOAO DA SILVA",
            ).count(),
            2,
        )


class CounterpartyRebuildViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="counterparty-rebuild-user",
            password="safe-password-123",
        )
        self.client.force_login(self.user)

    def test_list_exposes_rebuild_action(self):
        response = self.client.get(
            reverse(
                "finance:counterparty-list"
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertContains(
            response,
            "Reanalisar associações",
        )

    def test_rebuild_endpoint_accepts_post(self):
        response = self.client.post(
            reverse(
                "finance:counterparty-rebuild"
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )



class CounterpartyManualMergeServiceTests(TestCase):
    def setUp(self):
        self.bank = Bank.objects.create(
            name="Banco Merge Manual",
            code="621",
        )
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Principal",
            branch="1",
            number="6210",
        )

        self.short = Counterparty.objects.create(
            display_name="THOMPSON RESENDE DA SILVA",
            normalized_name="THOMPSON RESENDE DA SILVA",
            kind=Counterparty.Kind.PERSON,
        )
        self.long = Counterparty.objects.create(
            display_name="THOMPSON RESENDE DA SILVA OLIVEIRA",
            normalized_name=(
                "THOMPSON RESENDE DA SILVA OLIVEIRA"
            ),
            kind=Counterparty.Kind.PERSON,
        )

        self.first = Transaction.objects.create(
            account=self.account,
            posted_at=timezone.now(),
            amount=Decimal("20.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.OFX,
            fitid="MERGE-MANUAL-1",
            raw_description=(
                "Transferência recebida pelo Pix - "
                "THOMPSON RESENDE DA SILVA - BANCO TESTE"
            ),
            counterparty=self.short,
            counterparty_raw_name=(
                "THOMPSON RESENDE DA SILVA"
            ),
        )
        self.second = Transaction.objects.create(
            account=self.account,
            posted_at=timezone.now(),
            amount=Decimal("30.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.OFX,
            fitid="MERGE-MANUAL-2",
            raw_description=(
                "Transferência recebida pelo Pix - "
                "THOMPSON RESENDE DA SILVA OLIVEIRA - BANCO TESTE"
            ),
            counterparty=self.long,
            counterparty_raw_name=(
                "THOMPSON RESENDE DA SILVA OLIVEIRA"
            ),
        )

    def test_manual_merge_moves_transactions_and_keeps_richer_name(self):
        result = merge_counterparties_manually(
            counterparty_ids=[
                self.short.pk,
                self.long.pk,
            ],
            target_id=self.long.pk,
            final_display_name=(
                "THOMPSON RESENDE DA SILVA OLIVEIRA"
            ),
        )

        self.short.refresh_from_db()
        self.long.refresh_from_db()
        self.first.refresh_from_db()
        self.second.refresh_from_db()

        self.assertFalse(
            self.short.is_active
        )
        self.assertTrue(
            self.long.is_active
        )
        self.assertEqual(
            self.first.counterparty_id,
            self.long.pk,
        )
        self.assertEqual(
            self.second.counterparty_id,
            self.long.pk,
        )
        self.assertEqual(
            result.moved_transactions,
            1,
        )
        self.assertTrue(
            self.long.aliases.filter(
                alias_type=(
                    CounterpartyAlias.AliasType.NAME
                ),
                normalized_alias=(
                    "THOMPSON RESENDE DA SILVA"
                ),
            ).exists()
        )

    def test_rebuild_does_not_split_manually_merged_name_variants(self):
        merge_counterparties_manually(
            counterparty_ids=[
                self.short.pk,
                self.long.pk,
            ],
            target_id=self.long.pk,
            final_display_name=(
                "THOMPSON RESENDE DA SILVA OLIVEIRA"
            ),
        )

        rebuild_counterparty_links()

        self.first.refresh_from_db()
        self.second.refresh_from_db()

        self.assertEqual(
            self.first.counterparty_id,
            self.long.pk,
        )
        self.assertEqual(
            self.second.counterparty_id,
            self.long.pk,
        )

    def test_full_tax_id_conflict_requires_explicit_override(self):
        self.short.tax_id = (
            "11111111111"
        )
        self.short.save(
            update_fields=[
                "tax_id",
                "updated_at",
            ]
        )

        self.long.tax_id = (
            "22222222222"
        )
        self.long.save(
            update_fields=[
                "tax_id",
                "updated_at",
            ]
        )

        selected = (
            Counterparty.objects.filter(
                pk__in=[
                    self.short.pk,
                    self.long.pk,
                ]
            )
            .prefetch_related(
                "aliases"
            )
        )

        analysis = (
            analyze_manual_counterparty_merge(
                selected
            )
        )

        self.assertTrue(
            analysis[
                "has_strong_conflicts"
            ]
        )

        with self.assertRaises(
            ValueError
        ):
            merge_counterparties_manually(
                counterparty_ids=[
                    self.short.pk,
                    self.long.pk,
                ],
                target_id=self.long.pk,
                final_display_name=(
                    self.long.display_name
                ),
            )

        result = (
            merge_counterparties_manually(
                counterparty_ids=[
                    self.short.pk,
                    self.long.pk,
                ],
                target_id=self.long.pk,
                final_display_name=(
                    self.long.display_name
                ),
                allow_strong_conflicts=True,
            )
        )

        self.assertEqual(
            result.target_id,
            self.long.pk,
        )


class CounterpartyManualMergeViewTests(TestCase):
    def setUp(self):
        self.user = (
            get_user_model()
            .objects.create_user(
                username="counterparty-merge-user",
                password="safe-password-123",
            )
        )
        self.client.force_login(
            self.user
        )

        self.first = Counterparty.objects.create(
            display_name="THOMPSON RESENDE DA SILVA",
            normalized_name="THOMPSON RESENDE DA SILVA",
            kind=Counterparty.Kind.PERSON,
        )
        self.second = Counterparty.objects.create(
            display_name=(
                "THOMPSON RESENDE DA SILVA OLIVEIRA"
            ),
            normalized_name=(
                "THOMPSON RESENDE DA SILVA OLIVEIRA"
            ),
            kind=Counterparty.Kind.PERSON,
        )

    def test_list_exposes_manual_merge_selection(self):
        response = self.client.get(
            reverse(
                "finance:counterparty-list"
            ),
            {
                "q": "THOMPSON",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertContains(
            response,
            "Unificar selecionados",
        )
        self.assertContains(
            response,
            'name="counterparties"',
        )

    def test_preview_requires_at_least_two_records(self):
        response = self.client.post(
            reverse(
                "finance:counterparty-merge-preview"
            ),
            {
                "counterparties": [
                    str(
                        self.first.pk
                    )
                ],
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

    def test_preview_shows_selected_similar_names(self):
        response = self.client.post(
            reverse(
                "finance:counterparty-merge-preview"
            ),
            {
                "counterparties": [
                    str(
                        self.first.pk
                    ),
                    str(
                        self.second.pk
                    ),
                ],
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertContains(
            response,
            self.first.display_name,
        )
        self.assertContains(
            response,
            self.second.display_name,
        )
        self.assertContains(
            response,
            "Confirmar unificação manual",
        )

    def test_apply_merges_selected_records(self):
        response = self.client.post(
            reverse(
                "finance:counterparty-merge-apply"
            ),
            {
                "counterparties": [
                    str(
                        self.first.pk
                    ),
                    str(
                        self.second.pk
                    ),
                ],
                "target": str(
                    self.second.pk
                ),
                "final_display_name": (
                    "THOMPSON RESENDE DA SILVA OLIVEIRA"
                ),
                "confirm_merge": "on",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.first.refresh_from_db()
        self.second.refresh_from_db()

        self.assertFalse(
            self.first.is_active
        )
        self.assertTrue(
            self.second.is_active
        )
