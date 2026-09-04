from datetime import datetime
from decimal import Decimal

from django.test import SimpleTestCase

from services.statements.mercado_pago_csv import MercadoPagoCsvParser
from services.statements.mercado_pago_pdf import MercadoPagoPdfParser


class MercadoPagoPdfRowTests(SimpleTestCase):
    def test_parses_row_using_operation_id_as_fitid(self):
        parser = MercadoPagoPdfParser()

        item = parser._parse_row(
            [
                "06-01-2026",
                "Transferência Pix recebida",
                "Ana Lucia Anastácio da Silva",
                "140933256028",
                "R$ 3.000,00",
                "R$ 3.000,00",
            ],
            page_number=1,
        )

        self.assertIsNotNone(item)
        self.assertEqual(
            item.fitid,
            "140933256028",
        )
        self.assertEqual(
            item.amount,
            Decimal("3000.00"),
        )
        self.assertEqual(
            item.memo,
            (
                "Transferência Pix recebida "
                "Ana Lucia Anastácio da Silva"
            ),
        )
        self.assertFalse(
            item.posted_at_has_time
        )

    def test_parses_negative_pdf_amount(self):
        parser = MercadoPagoPdfParser()

        item = parser._parse_row(
            [
                "11-01-2026",
                "Transferência Pix enviada",
                "Thiago Rezende",
                "140931718807",
                "R$ -1.452,43",
                "R$ 0,00",
            ],
            page_number=2,
        )

        self.assertEqual(
            item.amount,
            Decimal("-1452.43"),
        )


class MercadoPagoCsvTests(SimpleTestCase):
    def test_api_csv_uses_source_id_as_fitid(self):
        csv_content = (
            "SOURCE_ID;TRANSACTION_DATE;"
            "TRANSACTION_TYPE;"
            "SETTLEMENT_NET_AMOUNT;"
            "EXTERNAL_REFERENCE;"
            "PAYMENT_METHOD\n"
            "MP-123;2026-01-06T14:30:00Z;"
            "PAYMENT;3000.00;"
            "PIX-ANA;pix\n"
        ).encode("utf-8")

        parsed = (
            MercadoPagoCsvParser()
            .parse_bytes(csv_content)
        )

        item = (
            parsed.statements[0]
            .transactions[0]
        )

        self.assertEqual(
            item.fitid,
            "MP-123",
        )
        self.assertEqual(
            item.amount,
            Decimal("3000.00"),
        )
        self.assertEqual(
            item.posted_at,
            datetime.fromisoformat(
                "2026-01-06T14:30:00+00:00"
            ),
        )
        self.assertTrue(
            item.posted_at_has_time
        )
