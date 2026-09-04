from datetime import datetime
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from services.ofx.models import ParsedOfxFile
from services.ofx.models import ParsedStatement
from services.ofx.models import ParsedTransaction


class OfxPreviewViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="ofxuser",
            password="safe-password-123",
        )
        self.client.force_login(self.user)

    def test_preview_requires_valid_extension(self):
        file = SimpleUploadedFile(
            "extrato.txt",
            b"OFXHEADER:100\n<OFX>",
            content_type="text/plain",
        )

        response = self.client.post(
            reverse("finance:ofx-preview"),
            data={"file": file},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "extensão .ofx ou .qfx",
        )

    @patch("finance.ofx_views.OfxBrParser.parse_bytes")
    def test_preview_does_not_persist_transactions(
        self,
        parse_bytes,
    ):
        parse_bytes.return_value = ParsedOfxFile(
            version=1,
            encoding="cp1252",
            statements=(
                ParsedStatement(
                    bank_id="999",
                    bank_name="Banco Teste",
                    branch_id="0001",
                    account_id="123456",
                    account_type="CHECKING",
                    currency="BRL",
                    start=None,
                    end=None,
                    ledger_balance=Decimal("500.00"),
                    transactions=(
                        ParsedTransaction(
                            fitid="TESTE-1",
                            posted_at=datetime(2026, 9, 3, 12, 0),
                            amount=Decimal("500.00"),
                            transaction_type="CREDIT",
                            memo="PIX TESTE",
                            payee="",
                            checknum="",
                            reference="",
                            raw={},
                        ),
                    ),
                ),
            ),
        )

        file = SimpleUploadedFile(
            "extrato.ofx",
            b"OFXHEADER:100\n<OFX>",
            content_type="application/octet-stream",
        )

        response = self.client.post(
            reverse("finance:ofx-preview"),
            data={"file": file},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Nenhuma movimentação foi gravada",
        )
        self.assertContains(
            response,
            "TESTE-1",
        )
