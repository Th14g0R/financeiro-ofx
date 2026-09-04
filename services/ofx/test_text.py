from django.test import SimpleTestCase

from services.ofx.text import normalize_display_text
from services.ofx.text import repair_mojibake


class OfxTextRepairTests(SimpleTestCase):
    def test_repairs_debito(self):
        self.assertEqual(
            repair_mojibake("Compra no dÃ©bito"),
            "Compra no débito",
        )

    def test_repairs_transferencia(self):
        self.assertEqual(
            repair_mojibake("TransferÃªncia recebida pelo Pix"),
            "Transferência recebida pelo Pix",
        )

    def test_repairs_agencia(self):
        self.assertEqual(
            repair_mojibake("AgÃªncia: 3140"),
            "Agência: 3140",
        )

    def test_repairs_masked_bullets(self):
        self.assertEqual(
            repair_mojibake(
                "â€¢â€¢â€¢713.503-â€¢â€¢â€¢"
            ),
            "•••713.503-•••",
        )

    def test_keeps_correct_portuguese_untouched(self):
        values = [
            "São João",
            "AÇÃO COMERCIAL",
            "Pagamento de fatura",
            "Transferência recebida pelo Pix",
        ]

        for value in values:
            with self.subTest(value=value):
                self.assertEqual(
                    repair_mojibake(value),
                    value,
                )

    def test_normalizes_redundant_whitespace_after_repair(self):
        self.assertEqual(
            normalize_display_text(
                "TransferÃªncia   recebida\n pelo Pix"
            ),
            "Transferência recebida pelo Pix",
        )
