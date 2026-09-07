from django.test import SimpleTestCase

from finance.models import Transaction
from services.counterparties import extract_counterparty_candidate


class AstroPayCounterpartyTests(SimpleTestCase):
    def test_extracts_name_before_trailing_transfer_pix_label(self):
        candidate = extract_counterparty_candidate(
            (
                "Ana Lucia Anastácio Da Silva "
                "Transferência Pix"
            ),
            transaction_type=(
                Transaction.TransactionType.PIX
            ),
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(
            candidate.name,
            "Ana Lucia Anastácio Da Silva",
        )

    def test_trailing_transfer_keeps_bank_identifier_for_existing_resolver(self):
        candidate = extract_counterparty_candidate(
            (
                "58.876.922 Talyze Reboucas Marques De Souza "
                "Transferência Pix"
            ),
            transaction_type=(
                Transaction.TransactionType.PIX
            ),
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(
            candidate.name,
            "Talyze Reboucas Marques De Souza",
        )
        self.assertEqual(
            candidate.bank_identifier,
            "58876922",
        )
