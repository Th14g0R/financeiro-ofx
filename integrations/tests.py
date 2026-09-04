from unittest.mock import Mock
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from finance.models import Account
from finance.models import Bank
from integrations.forms import BankIntegrationForm
from integrations.mercado_pago import get_access_token
from integrations.models import BankIntegration


class BankIntegrationCredentialTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="integration-user",
            password="safe-password-123",
        )
        self.bank = Bank.objects.create(
            name="Mercado Pago",
            code="323",
        )
        self.account = Account.objects.create(
            bank=self.bank,
            nickname="Mercado Pago",
            branch="1",
            number="123456",
        )

    def test_secret_is_stored_encrypted(self):
        integration = BankIntegration(
            name="MP",
            account=self.account,
            created_by=self.user,
        )

        integration.set_client_secret(
            "secret-value"
        )

        self.assertNotEqual(
            integration.client_secret_encrypted,
            "secret-value",
        )
        self.assertEqual(
            integration.get_client_secret(),
            "secret-value",
        )

    def test_integration_form_requires_current_password(self):
        form = BankIntegrationForm(
            data={
                "name": "MP Seguro",
                "provider": (
                    BankIntegration.Provider.MERCADO_PAGO
                ),
                "account": self.account.pk,
                "auth_mode": (
                    BankIntegration.AuthMode.CLIENT_CREDENTIALS
                ),
                "client_id": "client-id",
                "client_secret": "client-secret",
                "access_token": "",
                "current_password": "senha-incorreta",
                "is_active": True,
            },
            user=self.user,
        )

        self.assertFalse(
            form.is_valid()
        )
        self.assertIn(
            "current_password",
            form.errors,
        )

    def test_integration_form_accepts_valid_current_password(self):
        form = BankIntegrationForm(
            data={
                "name": "MP Seguro",
                "provider": (
                    BankIntegration.Provider.MERCADO_PAGO
                ),
                "account": self.account.pk,
                "auth_mode": (
                    BankIntegration.AuthMode.CLIENT_CREDENTIALS
                ),
                "client_id": "client-id",
                "client_secret": "client-secret",
                "access_token": "",
                "current_password": "safe-password-123",
                "is_active": True,
            },
            user=self.user,
        )

        self.assertTrue(
            form.is_valid(),
            form.errors,
        )

    @patch(
        "integrations.mercado_pago.requests.post"
    )
    def test_client_credentials_token_is_cached(
        self,
        post,
    ):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "access_token": "token-from-api",
            "expires_in": 21600,
        }
        post.return_value = response

        integration = BankIntegration.objects.create(
            name="MP API",
            account=self.account,
            auth_mode=(
                BankIntegration.AuthMode.CLIENT_CREDENTIALS
            ),
            client_id="client-id",
            created_by=self.user,
        )
        integration.set_client_secret(
            "client-secret"
        )
        integration.save(
            update_fields=[
                "client_secret_encrypted",
                "updated_at",
            ]
        )

        token = get_access_token(
            integration
        )

        self.assertEqual(
            token,
            "token-from-api",
        )

        integration.refresh_from_db()

        self.assertEqual(
            integration.get_access_token(),
            "token-from-api",
        )
        self.assertIsNotNone(
            integration.access_token_expires_at
        )
