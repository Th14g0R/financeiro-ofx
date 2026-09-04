from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from services.ofx.parser import OfxBrParser


class OfxBrParserTests(SimpleTestCase):
    def test_parser_converts_ofxbr_document_to_internal_models(self):
        transaction = SimpleNamespace(
            fitid="ABC123",
            posted_at=datetime(
                2026,
                9,
                3,
                12,
                0,
                tzinfo=timezone.utc,
            ),
            amount=Decimal("-150.25"),
            type="DEBIT",
            memo="PAGAMENTO FORNECEDOR",
            payee="FORNECEDOR TESTE",
            checknum="",
            refnum="REF-1",
        )

        account = SimpleNamespace(
            bank_id="341",
            bank_name="Itaú Unibanco",
            branch_id="1234",
            account_id="56789-0",
            account_type="CHECKING",
        )

        class FakeStatement:
            currency = "BRL"
            start = datetime(2026, 9, 1, tzinfo=timezone.utc)
            end = datetime(2026, 9, 30, tzinfo=timezone.utc)
            ledger_balance = Decimal("1000.00")

            def __init__(self):
                self.account = account

            def __iter__(self):
                return iter([transaction])

        fake_document = SimpleNamespace(
            version=1,
            encoding="cp1252",
            statements=[FakeStatement()],
        )

        fake_module = SimpleNamespace(
            parse=lambda content: fake_document
        )

        with patch.dict(
            "sys.modules",
            {"ofxbr": fake_module},
        ):
            result = OfxBrParser().parse_bytes(b"OFX")

        self.assertEqual(result.version, 1)
        self.assertEqual(result.encoding, "cp1252")
        self.assertEqual(result.transaction_count, 1)

        statement = result.statements[0]
        self.assertEqual(statement.bank_id, "341")
        self.assertEqual(statement.account_id, "56789-0")
        self.assertEqual(statement.currency, "BRL")

        item = statement.transactions[0]
        self.assertEqual(item.fitid, "ABC123")
        self.assertEqual(item.amount, Decimal("-150.25"))
        self.assertTrue(item.is_debit)
        self.assertEqual(
            item.absolute_amount,
            Decimal("150.25"),
        )



class OfxBrParserEncodingTests(SimpleTestCase):
    def test_parser_repairs_mojibake_and_preserves_source_text(self):
        transaction = SimpleNamespace(
            fitid="NU-001",
            posted_at=datetime(
                2026,
                9,
                3,
                12,
                0,
                tzinfo=timezone.utc,
            ),
            amount=Decimal("-10.00"),
            type="DEBIT",
            memo="Compra no dÃ©bito - FARMACIA",
            payee="",
            checknum="",
            refnum="",
        )

        account = SimpleNamespace(
            bank_id="260",
            bank_name="NU PAGAMENTOS",
            branch_id="0001",
            account_id="123456",
            account_type="CHECKING",
        )

        class FakeStatement:
            currency = "BRL"
            start = None
            end = None
            ledger_balance = Decimal("100.00")

            def __init__(self):
                self.account = account
                self.transactions = [transaction]

        fake_document = SimpleNamespace(
            version=1,
            encoding="cp1252",
            statements=[FakeStatement()],
        )

        fake_module = SimpleNamespace(
            parse=lambda content: fake_document
        )

        with patch.dict(
            "sys.modules",
            {"ofxbr": fake_module},
        ):
            result = OfxBrParser().parse_bytes(b"OFX")

        item = result.statements[0].transactions[0]

        self.assertEqual(
            item.memo,
            "Compra no débito - FARMACIA",
        )
        self.assertEqual(
            item.raw["_source_text"]["memo"],
            "Compra no dÃ©bito - FARMACIA",
        )
        self.assertEqual(
            item.raw["memo"],
            "Compra no débito - FARMACIA",
        )



class OfxRawDateTimeTests(SimpleTestCase):
    def _fake_document(self, transaction):
        account = SimpleNamespace(
            bank_id="260",
            bank_name="NU PAGAMENTOS",
            branch_id="0001",
            account_id="123456",
            account_type="CHECKING",
        )

        class FakeStatement:
            currency = "BRL"
            start = None
            end = None
            ledger_balance = Decimal("100.00")

            def __init__(self):
                self.account = account
                self.transactions = [transaction]

        return SimpleNamespace(
            version=1,
            encoding="cp1252",
            statements=[FakeStatement()],
        )

    def test_raw_dtposted_without_time_is_identified(self):
        transaction = SimpleNamespace(
            fitid="DATE-ONLY",
            posted_at=datetime(
                2026,
                5,
                2,
                0,
                0,
                tzinfo=timezone.utc,
            ),
            amount=Decimal("-8.98"),
            type="DEBIT",
            memo="Compra no débito - TESTE",
            payee="",
            checknum="",
            refnum="",
        )

        fake_module = SimpleNamespace(
            parse=lambda content: self._fake_document(transaction)
        )

        content = (
            b"<OFX><STMTTRN>"
            b"<TRNTYPE>DEBIT"
            b"<DTPOSTED>20260502"
            b"<TRNAMT>-8.98"
            b"<FITID>DATE-ONLY"
            b"</STMTTRN></OFX>"
        )

        with patch.dict("sys.modules", {"ofxbr": fake_module}):
            result = OfxBrParser().parse_bytes(content)

        item = result.statements[0].transactions[0]

        self.assertEqual(item.posted_at_raw, "20260502")
        self.assertFalse(item.posted_at_has_time)
        self.assertEqual(
            item.raw["_ofx_datetime"]["dtposted"],
            "20260502",
        )

    def test_raw_dtposted_with_time_is_preserved(self):
        transaction = SimpleNamespace(
            fitid="WITH-TIME",
            posted_at=datetime(
                2026,
                5,
                2,
                14,
                37,
                25,
                tzinfo=timezone.utc,
            ),
            amount=Decimal("5.00"),
            type="CREDIT",
            memo="Transferência recebida",
            payee="",
            checknum="",
            refnum="",
        )

        fake_module = SimpleNamespace(
            parse=lambda content: self._fake_document(transaction)
        )

        content = (
            b"<OFX><STMTTRN>"
            b"<TRNTYPE>CREDIT"
            b"<DTPOSTED>20260502143725[-3:BRT]"
            b"<TRNAMT>5.00"
            b"<FITID>WITH-TIME"
            b"</STMTTRN></OFX>"
        )

        with patch.dict("sys.modules", {"ofxbr": fake_module}):
            result = OfxBrParser().parse_bytes(content)

        item = result.statements[0].transactions[0]

        self.assertEqual(
            item.posted_at_raw,
            "20260502143725[-3:BRT]",
        )
        self.assertTrue(item.posted_at_has_time)
