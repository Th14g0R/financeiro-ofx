from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

import pymupdf

from finance.models import Account
from finance.models import Bank
from finance.models import Transaction
from imports.models import ImportBatch
from imports.models import ImportFile
from imports.models import ImportItem
from services.importing import commit_batch
from services.importing import stage_uploaded_file
from services.statements.astropay_pdf import AstroPayPdfParser


def build_astropay_pdf(
    *,
    generation_label: str = "07 set 2026 09:22",
    only_balances: bool = False,
) -> bytes:
    document = pymupdf.open()
    page = document.new_page(
        width=595,
        height=842,
    )

    header_lines = [
        "Este extrato e um documento informativo gerado automaticamente.",
        "Suporte: support@astropay.com | www.astropay.com",
        "Astro Instituicao de Pagamento Ltda",
        f"Gerado em: {generation_label} (UTC -03:00)",
        "BRL Declaracao",
        "1 agosto 2026 - 31 agosto 2026",
        "Titular da conta",
        "Thiago Rezende Da Silva Oliveira",
        "Resumo",
        "Saldo Inicial",
        "4.309,91",
        "Creditos totais",
        "507,50",
        "Debitos Totais",
        "0,00",
        "Saldo Final",
        "4.817,41",
        "Historico de transacoes",
        "Data Descricao Quantia Equilibrio",
    ]

    y = 35

    for line in header_lines:
        page.insert_text(
            (35, y),
            line,
            fontsize=9,
        )
        y += 14

    rows = [
        (
            "08/01\nSaldo Inicial\n4.309,91\n4.309,91"
        ),
    ]

    if not only_balances:
        rows.extend(
            [
                (
                    "08/03\nThiago Rezende Da Silva Oliveira "
                    "Transferencia Pix\n500,00\n4.809,91"
                ),
                "08/13\nCashback\n3,75\n4.813,66",
                "08/13\nCashback\n3,75\n4.817,41",
            ]
        )

    rows.append(
        "08/31\nSaldo Final\n4.817,41\n4.817,41"
    )

    row_y = y + 12

    for row in rows:
        height = 74
        result = page.insert_textbox(
            pymupdf.Rect(
                35,
                row_y,
                560,
                row_y + height,
            ),
            row,
            fontsize=9,
        )

        if result < 0:
            raise AssertionError(
                "Falha ao montar PDF AstroPay sintético para o teste."
            )

        row_y += height + 4

    content = document.tobytes()
    document.close()
    return content


class AstroPayPdfImportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="astropay-import-user",
            password="safe-password-123",
        )

    def _batch(self):
        return ImportBatch.objects.create(
            created_by=self.user,
            status=ImportBatch.Status.ANALYZING,
        )

    def _upload(
        self,
        *,
        name: str,
        content: bytes,
    ):
        return SimpleUploadedFile(
            name,
            content,
            content_type="application/pdf",
        )

    def test_astropay_pdf_ignores_opening_and_closing_balance_rows(self):
        content = build_astropay_pdf()
        batch = self._batch()

        import_file = stage_uploaded_file(
            batch=batch,
            uploaded_file=self._upload(
                name="statement_BRL_2026_8.pdf",
                content=content,
            ),
        )

        self.assertEqual(
            import_file.status,
            ImportFile.Status.ANALYZED,
        )
        self.assertEqual(
            import_file.provider,
            ImportFile.Provider.ASTROPAY,
        )
        self.assertEqual(
            import_file.source_format,
            ImportFile.SourceFormat.PDF,
        )

        statement = import_file.statements.get()
        items = list(
            statement.items.order_by(
                "sequence"
            )
        )

        self.assertEqual(
            len(items),
            3,
        )
        self.assertFalse(
            any(
                "SALDO" in item.raw_description.upper()
                for item in items
            )
        )
        self.assertEqual(
            statement.ledger_balance,
            Decimal("4817.41"),
        )

    def test_same_day_equal_cashbacks_keep_distinct_fitids(self):
        content = build_astropay_pdf()
        parsed = AstroPayPdfParser().parse_bytes(
            content
        )
        items = [
            item
            for item in parsed.statements[0].transactions
            if item.memo == "Cashback"
        ]

        self.assertEqual(
            len(items),
            2,
        )
        self.assertEqual(
            items[0].amount,
            Decimal("3.75"),
        )
        self.assertEqual(
            items[1].amount,
            Decimal("3.75"),
        )
        self.assertNotEqual(
            items[0].fitid,
            items[1].fitid,
        )

    def test_balance_only_month_is_valid_and_has_zero_items(self):
        content = build_astropay_pdf(
            only_balances=True
        )
        batch = self._batch()

        import_file = stage_uploaded_file(
            batch=batch,
            uploaded_file=self._upload(
                name="statement_BRL_2026_2.pdf",
                content=content,
            ),
        )

        self.assertEqual(
            import_file.status,
            ImportFile.Status.ANALYZED,
        )
        statement = import_file.statements.get()
        self.assertEqual(
            statement.items.count(),
            0,
        )

    def test_redownloaded_pdf_uses_same_synthetic_fitids(self):
        first_content = build_astropay_pdf(
            generation_label="07 set 2026 09:22"
        )
        second_content = build_astropay_pdf(
            generation_label="08 set 2026 10:40"
        )

        first_parsed = AstroPayPdfParser().parse_bytes(
            first_content
        )
        second_parsed = AstroPayPdfParser().parse_bytes(
            second_content
        )

        first_fitids = [
            item.fitid
            for item in first_parsed.statements[0].transactions
        ]
        second_fitids = [
            item.fitid
            for item in second_parsed.statements[0].transactions
        ]

        self.assertEqual(
            first_fitids,
            second_fitids,
        )

    def test_redownload_is_classified_as_duplicate_after_first_commit(self):
        first_content = build_astropay_pdf(
            generation_label="07 set 2026 09:22"
        )
        second_content = build_astropay_pdf(
            generation_label="08 set 2026 10:40"
        )

        parsed = AstroPayPdfParser().parse_bytes(
            first_content
        )
        parsed_statement = parsed.statements[0]

        bank = Bank.objects.create(
            name="AstroPay",
            ofx_bank_id="ASTROPAY",
        )
        Account.objects.create(
            bank=bank,
            nickname="AstroPay BRL",
            branch="",
            number=parsed_statement.account_id,
            account_type=Account.AccountType.PAYMENT,
            currency="BRL",
            ofx_account_id=parsed_statement.account_id,
            is_own_account=True,
        )

        first_batch = self._batch()
        first_file = stage_uploaded_file(
            batch=first_batch,
            uploaded_file=self._upload(
                name="statement_BRL_2026_8-a.pdf",
                content=first_content,
            ),
        )

        self.assertEqual(
            first_file.statements.get().items.filter(
                classification=ImportItem.Classification.NEW
            ).count(),
            3,
        )

        commit_batch(
            batch=first_batch,
            user=self.user,
        )

        self.assertEqual(
            Transaction.objects.filter(
                account__bank=bank
            ).count(),
            3,
        )

        second_batch = self._batch()
        second_file = stage_uploaded_file(
            batch=second_batch,
            uploaded_file=self._upload(
                name="statement_BRL_2026_8-b.pdf",
                content=second_content,
            ),
        )

        self.assertNotEqual(
            first_file.file_hash,
            second_file.file_hash,
        )
        self.assertEqual(
            second_file.statements.get().items.filter(
                classification=ImportItem.Classification.DUPLICATE
            ).count(),
            3,
        )
