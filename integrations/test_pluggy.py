from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from finance.models import Account, Bank, Transaction

from .forms import PluggyConfigurationForm
from .models import PluggyAccount, PluggyConfiguration, PluggyItem, PluggyTransactionLink
from .pluggy import authenticate
from .pluggy_sync import sync_account_transactions, upsert_accounts, upsert_item


class PluggyConfigurationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="pluggy-admin",
            password="Senha-Muito-Forte-123!",
        )

    @override_settings(DEBUG=False)
    def test_form_encrypts_client_secret_and_never_stores_plaintext(self):
        form = PluggyConfigurationForm(
            data={
                "name": "Pluggy / Open Finance",
                "client_id": "client-id-test",
                "client_secret": "client-secret-ultra-reservado",
                "current_password": "Senha-Muito-Forte-123!",
                "is_active": "on",
            },
            user=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        config = form.save()
        self.assertNotIn("client-secret-ultra-reservado", config.client_secret_encrypted)
        self.assertEqual(config.get_client_secret(), "client-secret-ultra-reservado")

    def test_auth_caches_short_lived_api_key_encrypted(self):
        config = PluggyConfiguration(name="Pluggy", client_id="client")
        config.set_client_secret("secret")
        config.save()
        with patch("integrations.pluggy._request_json", return_value={"accessToken": "temporary-api-key"}) as mocked:
            first = authenticate(config, force=True)
            second = authenticate(config)
        self.assertEqual(first, "temporary-api-key")
        self.assertEqual(second, "temporary-api-key")
        self.assertEqual(mocked.call_count, 1)
        config.refresh_from_db()
        self.assertNotIn("temporary-api-key", config.api_key_encrypted)
        self.assertGreater(config.api_key_expires_at, timezone.now() + timedelta(hours=1))


class PluggySyncTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="operator", password="Senha-Muito-Forte-123!")
        self.config = PluggyConfiguration(name="Pluggy", client_id="client")
        self.config.set_client_secret("secret")
        self.config.save()
        self.item = PluggyItem.objects.create(
            configuration=self.config,
            item_id="11111111-1111-1111-1111-111111111111",
            connector_name="Nubank",
            status="UPDATED",
        )
        self.bank = Bank.objects.create(name="Nubank")
        self.local = Account.objects.create(
            bank=self.bank,
            nickname="Nubank Principal",
            branch="0001",
            number="12345",
            digit="6",
            account_type=Account.AccountType.CHECKING,
            currency="BRL",
            is_own_account=True,
        )
        self.remote = PluggyAccount.objects.create(
            item=self.item,
            pluggy_account_id="22222222-2222-2222-2222-222222222222",
            local_account=self.local,
            remote_type="BANK",
            subtype="CHECKING_ACCOUNT",
            name="Conta Corrente",
            currency="BRL",
        )

    @patch("integrations.pluggy_sync.list_all_transactions")
    def test_posted_transaction_is_created_once_using_provider_id(self, mocked):
        mocked.return_value = [{
            "id": "33333333-3333-3333-3333-333333333333",
            "providerId": "provider-xyz-1",
            "date": "2026-09-08T12:00:00.000Z",
            "description": "Pix recebido de Maria Silva",
            "amount": 150.25,
            "type": "CREDIT",
            "status": "POSTED",
            "currencyCode": "BRL",
        }]
        first = sync_account_transactions(self.remote, user=self.user)
        second = sync_account_transactions(self.remote, user=self.user)
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(Transaction.objects.count(), 1)
        tx = Transaction.objects.get()
        self.assertEqual(tx.fitid, "PLUGGY-PROVIDER:provider-xyz-1")
        self.assertEqual(tx.source_type, Transaction.SourceType.API)
        self.assertEqual(tx.created_by, self.user)
        self.assertEqual(PluggyTransactionLink.objects.count(), 1)

    @patch("integrations.pluggy_sync.list_all_transactions")
    def test_pending_transaction_is_not_written(self, mocked):
        mocked.return_value = [{
            "id": "44444444-4444-4444-4444-444444444444",
            "date": "2026-09-08T12:00:00.000Z",
            "description": "Compra pendente",
            "amount": -20,
            "type": "DEBIT",
            "status": "PENDING",
            "currencyCode": "BRL",
        }]
        result = sync_account_transactions(self.remote, user=self.user)
        self.assertEqual(result["pending"], 1)
        self.assertEqual(Transaction.objects.count(), 0)

    @patch("integrations.pluggy_sync.list_all_transactions")
    def test_remote_change_does_not_overwrite_financial_value(self, mocked):
        payload = {
            "id": "55555555-5555-5555-5555-555555555555",
            "providerId": "provider-conflict-1",
            "date": "2026-09-08T12:00:00.000Z",
            "description": "TED ORIGINAL",
            "amount": -100,
            "type": "DEBIT",
            "status": "POSTED",
            "currencyCode": "BRL",
        }
        mocked.return_value = [payload]
        sync_account_transactions(self.remote, user=self.user)
        tx = Transaction.objects.get()
        payload["amount"] = -120
        mocked.return_value = [payload]
        result = sync_account_transactions(self.remote, user=self.user)
        tx.refresh_from_db()
        self.assertEqual(tx.amount, 100)
        self.assertEqual(result["conflicts"], 1)
        link = PluggyTransactionLink.objects.get()
        self.assertTrue(link.has_conflict)
        self.assertIn("valor", link.conflict_fields)

    def test_item_status_detail_is_preserved_for_partial_success(self):
        payload = {
            "id": self.item.item_id,
            "connector": {"id": 200, "name": "Meu Pluggy"},
            "status": "UPDATED",
            "executionStatus": "PARTIAL_SUCCESS",
            "lastUpdatedAt": "2026-09-08T17:50:54.000Z",
            "statusDetail": {
                "accounts": {
                    "isUpdated": True,
                    "warnings": [],
                },
                "investments": {
                    "isUpdated": False,
                    "warnings": ["Produto indisponível"],
                },
            },
        }

        item = upsert_item(self.config, payload, user=self.user)

        self.assertEqual(item.execution_status, "PARTIAL_SUCCESS")
        self.assertTrue(item.status_detail["accounts"]["isUpdated"])
        self.assertFalse(item.status_detail["investments"]["isUpdated"])

    @patch("integrations.pluggy_sync.list_accounts")
    def test_bank_account_can_be_created_and_linked_automatically(self, mocked):
        self.remote.delete()
        mocked.return_value = [{
            "id": "66666666-6666-6666-6666-666666666666",
            "type": "BANK",
            "subtype": "CHECKING_ACCOUNT",
            "number": "0001/98765-4",
            "name": "Conta Corrente",
            "marketingName": "Conta Principal",
            "balance": 2500.10,
            "currencyCode": "BRL",
            "bankData": {"transferNumber": "260/0001/98765-4"},
        }]
        accounts, created = upsert_accounts(self.item)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(created, 1)
        self.assertIsNotNone(accounts[0].local_account_id)
        self.assertTrue(accounts[0].local_account.ofx_account_id.startswith("PLUGGY:"))



class PluggyMeuPluggyConnectorTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="pluggy-root",
            email="root@example.test",
            password="Senha-Muito-Forte-123!",
        )
        self.config = PluggyConfiguration(
            name="Pluggy Meu Pluggy",
            client_id="client-200",
            created_by=self.admin,
        )
        self.config.set_client_secret(
            "segredo-super-reservado"
        )
        self.config.save()

    @override_settings(PLUGGY_EMBEDDED_CONNECT_ENABLED=True)
    def test_connect_token_uses_backend_only_and_connector_200(self):
        from django.urls import reverse

        self.client.force_login(
            self.admin
        )

        with (
            patch(
                "integrations.pluggy_views.retrieve_connector",
                return_value={
                    "id": 200,
                    "name": "MeuPluggy",
                },
            ),
            patch(
                "integrations.pluggy_views.create_connect_token",
                return_value="connect-token-publico-curto",
            ) as mocked_token,
        ):
            response = self.client.post(
                reverse(
                    "integrations:pluggy-connect-token"
                ),
                REMOTE_ADDR="127.0.0.1",
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        payload = response.json()

        self.assertEqual(
            payload["connectorId"],
            200,
        )
        self.assertEqual(
            payload["accessToken"],
            "connect-token-publico-curto",
        )
        self.assertNotIn(
            "clientSecret",
            payload,
        )
        self.assertNotIn(
            "apiKey",
            payload,
        )

        mocked_token.assert_called_once_with(
            self.config,
            client_user_id=(
                f"financeiro-user-{self.admin.pk}"
            ),
            item_id=None,
        )

        self.assertIn(
            "no-store",
            response.headers[
                "Cache-Control"
            ],
        )

    @override_settings(PLUGGY_EMBEDDED_CONNECT_ENABLED=True)
    def test_widget_success_item_is_retrieved_server_side_before_storage(self):
        from django.urls import reverse

        self.client.force_login(
            self.admin
        )

        item_id = (
            "20000000-0000-0000-0000-"
            "000000000001"
        )

        with patch(
            "integrations.pluggy_views.retrieve_item",
            return_value={
                "id": item_id,
                "connector": {
                    "id": 200,
                    "name": "MeuPluggy",
                },
                "status": "UPDATED",
                "executionStatus": "SUCCESS",
            },
        ):
            response = self.client.post(
                reverse(
                    "integrations:pluggy-capture-item"
                ),
                {
                    "item_id": item_id,
                },
                REMOTE_ADDR="127.0.0.1",
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        item = PluggyItem.objects.get(
            item_id=item_id
        )

        self.assertEqual(
            item.connector_id,
            200,
        )
        self.assertEqual(
            item.created_by,
            self.admin,
        )

    def test_overview_defaults_to_manual_item_id_flow(self):
        from django.urls import reverse

        self.client.force_login(
            self.admin
        )

        response = self.client.get(
            reverse(
                "integrations:pluggy-overview"
            ),
            REMOTE_ADDR="127.0.0.1",
        )

        self.assertContains(
            response,
            "Registrar Item ID do Meu Pluggy",
        )
        self.assertContains(
            response,
            "Conectar Conta",
        )
        self.assertNotContains(
            response,
            "pluggy-connect/v2.8.2/pluggy-connect.js",
        )

        csp = response.headers.get(
            "Content-Security-Policy",
            "",
        )
        self.assertNotIn(
            "https://cdn.pluggy.ai",
            csp,
        )
        self.assertNotIn(
            "frame-src https://*.pluggy.ai",
            csp,
        )
        self.assertNotEqual(
            response.headers.get(
                "Cross-Origin-Opener-Policy"
            ),
            "same-origin-allow-popups",
        )

    @override_settings(PLUGGY_EMBEDDED_CONNECT_ENABLED=True)
    def test_overview_can_enable_connector_200_widget_explicitly(self):
        from django.urls import reverse

        self.client.force_login(
            self.admin
        )

        response = self.client.get(
            reverse(
                "integrations:pluggy-overview"
            ),
            REMOTE_ADDR="127.0.0.1",
        )

        self.assertContains(
            response,
            "Abrir Pluggy Connect embutido",
        )
        self.assertContains(
            response,
            "pluggy-connect/v2.8.2/pluggy-connect.js",
        )

        csp = response.headers.get(
            "Content-Security-Policy",
            "",
        )
        self.assertIn(
            "https://cdn.pluggy.ai",
            csp,
        )
        self.assertIn(
            "frame-src https://*.pluggy.ai",
            csp,
        )
        self.assertEqual(
            response.headers.get(
                "Cross-Origin-Opener-Policy"
            ),
            "same-origin-allow-popups",
        )

    def test_connect_token_endpoint_is_disabled_by_default(self):
        from django.urls import reverse

        self.client.force_login(
            self.admin
        )

        response = self.client.post(
            reverse(
                "integrations:pluggy-connect-token"
            ),
            REMOTE_ADDR="127.0.0.1",
        )

        self.assertEqual(
            response.status_code,
            409,
        )
        self.assertIn(
            "Development > Demo",
            response.json()["error"],
        )

    def test_meu_pluggy_item_does_not_use_direct_patch_update(self):
        from django.urls import reverse

        item = PluggyItem.objects.create(
            configuration=self.config,
            item_id=(
                "20000000-0000-0000-0000-"
                "000000000002"
            ),
            connector_id=200,
            connector_name="MeuPluggy",
            status="UPDATED",
            created_by=self.admin,
        )

        self.client.force_login(
            self.admin
        )

        with patch(
            "integrations.pluggy_views.trigger_item_update"
        ) as mocked:
            response = self.client.post(
                reverse(
                    "integrations:pluggy-trigger-update",
                    args=[
                        item.pk,
                    ],
                ),
                REMOTE_ADDR="127.0.0.1",
            )

        self.assertEqual(
            response.status_code,
            302,
        )
        mocked.assert_not_called()


class PluggyConnectTokenApiTests(TestCase):
    def test_create_connect_token_never_sends_client_secret_to_connect_endpoint(self):
        from integrations.pluggy import create_connect_token

        config = PluggyConfiguration(
            name="Pluggy API Token",
            client_id="client-id",
        )
        config.set_client_secret(
            "client-secret-nao-pode-ir-ao-widget"
        )
        config.set_api_key(
            "api-key-servidor"
        )
        config.api_key_expires_at = (
            timezone.now()
            + timedelta(
                hours=1,
            )
        )
        config.save()

        with patch(
            "integrations.pluggy._request_json",
            return_value={
                "accessToken": "connect-token",
            },
        ) as mocked:
            token = create_connect_token(
                config,
                client_user_id="financeiro-user-1",
            )

        self.assertEqual(
            token,
            "connect-token",
        )

        args, kwargs = mocked.call_args

        self.assertEqual(
            args[:2],
            (
                "POST",
                "/connect_token",
            ),
        )
        self.assertEqual(
            kwargs["api_key"],
            "api-key-servidor",
        )
        self.assertEqual(
            kwargs["json"],
            {
                "options": {
                    "clientUserId": (
                        "financeiro-user-1"
                    ),
                    "avoidDuplicates": True,
                }
            },
        )
        self.assertNotIn(
            "clientSecret",
            str(
                kwargs["json"]
            ),
        )


class PluggyCleanupTests(TestCase):
    def setUp(self):
        from finance.models import InternalTransfer

        self.InternalTransfer = InternalTransfer
        self.user = get_user_model().objects.create_superuser(
            username="cleanup-admin",
            email="cleanup@example.test",
            password="Senha-Muito-Forte-123!",
        )
        self.config = PluggyConfiguration(name="Pluggy Cleanup", client_id="cleanup-client")
        self.config.set_client_secret("cleanup-secret")
        self.config.save()
        self.item = PluggyItem.objects.create(
            configuration=self.config,
            item_id="77777777-7777-7777-7777-777777777777",
            connector_name="Sandbox Open Finance",
            status="UPDATED",
            last_sync_at=timezone.now(),
            created_by=self.user,
        )
        self.bank = Bank.objects.create(name="Sib Bank")
        self.local = Account.objects.create(
            bank=self.bank,
            nickname="Sandbox Conta",
            branch="0001",
            number="123456",
            digit="7",
            account_type=Account.AccountType.CHECKING,
            currency="BRL",
            ofx_account_id="PLUGGY:88888888-8888-8888-8888-888888888888",
            is_own_account=True,
        )
        self.remote = PluggyAccount.objects.create(
            item=self.item,
            pluggy_account_id="88888888-8888-8888-8888-888888888888",
            local_account=self.local,
            remote_type="BANK",
            subtype="CHECKING_ACCOUNT",
            name="Sandbox Conta",
            currency="BRL",
        )

    def _pluggy_transaction(self, *, fitid="PLUGGY:tx-cleanup", amount="50.00"):
        return Transaction.objects.create(
            account=self.local,
            posted_at=timezone.now(),
            competence_date=timezone.localdate(),
            amount=amount,
            direction=Transaction.Direction.DEBIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.API,
            fitid=fitid,
            raw_description="PIX TESTE SANDBOX",
            normalized_description="PIX TESTE SANDBOX",
            fingerprint="a" * 64,
            raw_data={"provider": "PLUGGY", "pluggy": {"id": fitid}},
            notes="Importado automaticamente via Pluggy / Open Finance.",
            created_by=self.user,
        )

    def test_cleanup_deletes_pluggy_owned_transaction_but_preserves_ofx_transaction(self):
        from integrations.pluggy_cleanup import build_cleanup_preview, cleanup_pluggy_data

        pluggy_tx = self._pluggy_transaction()
        ofx_tx = Transaction.objects.create(
            account=self.local,
            posted_at=timezone.now() - timedelta(days=1),
            competence_date=timezone.localdate() - timedelta(days=1),
            amount="25.00",
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.OFX,
            fitid="OFX-EXISTENTE-1",
            raw_description="PIX OFX EXISTENTE",
            normalized_description="PIX OFX EXISTENTE",
            fingerprint="b" * 64,
            raw_data={"provider": "OFX"},
            created_by=self.user,
        )
        PluggyTransactionLink.objects.create(
            pluggy_account=self.remote,
            remote_transaction_id="remote-pluggy-1",
            transaction=pluggy_tx,
        )
        PluggyTransactionLink.objects.create(
            pluggy_account=self.remote,
            remote_transaction_id="remote-existing-1",
            transaction=ofx_tx,
        )

        other_bank = Bank.objects.create(name="Outro Banco")
        other_account = Account.objects.create(
            bank=other_bank,
            nickname="Conta Destino",
            branch="0001",
            number="987654",
            digit="3",
            account_type=Account.AccountType.CHECKING,
            currency="BRL",
            is_own_account=True,
        )
        credit_leg = Transaction.objects.create(
            account=other_account,
            posted_at=pluggy_tx.posted_at,
            competence_date=pluggy_tx.competence_date,
            amount=pluggy_tx.amount,
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.MANUAL,
            fitid="",
            raw_description="TRANSFERÊNCIA INTERNA TESTE",
            normalized_description="TRANSFERÊNCIA INTERNA TESTE",
            fingerprint="d" * 64,
            raw_data={},
            created_by=self.user,
        )
        internal_transfer = self.InternalTransfer.objects.create(
            debit_transaction=pluggy_tx,
            credit_transaction=credit_leg,
            status=self.InternalTransfer.Status.CONFIRMED,
            match_method=self.InternalTransfer.MatchMethod.MANUAL,
            confidence=100,
        )

        preview = build_cleanup_preview(item=self.item)
        self.assertEqual(preview.transactions_to_delete, 1)
        self.assertEqual(preview.transactions_preserved, 1)
        self.assertEqual(preview.links, 2)
        self.assertEqual(preview.internal_transfers_to_delete, 1)

        result = cleanup_pluggy_data(item_pk=self.item.pk)

        self.assertEqual(result.transactions_deleted, 1)
        self.assertEqual(result.transactions_preserved, 1)
        self.assertEqual(result.internal_transfers_deleted, 1)
        self.assertFalse(self.InternalTransfer.objects.filter(pk=internal_transfer.pk).exists())
        self.assertTrue(Transaction.objects.filter(pk=credit_leg.pk).exists())
        self.assertFalse(Transaction.objects.filter(pk=pluggy_tx.pk).exists())
        self.assertTrue(Transaction.objects.filter(pk=ofx_tx.pk).exists())
        self.assertEqual(PluggyTransactionLink.objects.count(), 0)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.last_sync_at)

    def test_cleanup_can_remove_empty_local_account_and_local_item(self):
        from integrations.pluggy_cleanup import cleanup_pluggy_data

        pluggy_tx = self._pluggy_transaction(fitid="PLUGGY:tx-remove-all")
        PluggyTransactionLink.objects.create(
            pluggy_account=self.remote,
            remote_transaction_id="remote-remove-all",
            transaction=pluggy_tx,
        )

        item_pk = self.item.pk
        account_pk = self.local.pk
        bank_pk = self.bank.pk
        result = cleanup_pluggy_data(
            item_pk=item_pk,
            delete_empty_local_accounts=True,
            remove_item=True,
        )

        self.assertEqual(result.transactions_deleted, 1)
        self.assertEqual(result.local_accounts_deleted, 1)
        self.assertEqual(result.local_banks_deleted, 1)
        self.assertTrue(result.item_removed)
        self.assertFalse(Account.objects.filter(pk=account_pk).exists())
        self.assertFalse(Bank.objects.filter(pk=bank_pk).exists())
        self.assertFalse(PluggyItem.objects.filter(pk=item_pk).exists())

    def test_cleanup_preserves_local_account_when_non_pluggy_data_exists(self):
        from integrations.pluggy_cleanup import cleanup_pluggy_data

        pluggy_tx = self._pluggy_transaction(fitid="PLUGGY:tx-preserve-account")
        PluggyTransactionLink.objects.create(
            pluggy_account=self.remote,
            remote_transaction_id="remote-preserve-account",
            transaction=pluggy_tx,
        )
        Transaction.objects.create(
            account=self.local,
            posted_at=timezone.now() - timedelta(days=2),
            competence_date=timezone.localdate() - timedelta(days=2),
            amount="10.00",
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.OTHER,
            source_type=Transaction.SourceType.MANUAL,
            fitid="",
            raw_description="LANÇAMENTO MANUAL",
            normalized_description="LANÇAMENTO MANUAL",
            fingerprint="c" * 64,
            raw_data={},
            created_by=self.user,
        )

        result = cleanup_pluggy_data(
            item_pk=self.item.pk,
            delete_empty_local_accounts=True,
        )

        self.assertEqual(result.local_accounts_deleted, 0)
        self.assertEqual(result.local_accounts_preserved, 1)
        self.assertTrue(Account.objects.filter(pk=self.local.pk).exists())

    def test_cleanup_view_requires_password_and_confirmation_text(self):
        from django.urls import reverse

        self.client.force_login(self.user)
        pluggy_tx = self._pluggy_transaction(fitid="PLUGGY:tx-view")
        PluggyTransactionLink.objects.create(
            pluggy_account=self.remote,
            remote_transaction_id="remote-view",
            transaction=pluggy_tx,
        )

        url = reverse("integrations:pluggy-cleanup-item", args=[self.item.pk])
        response = self.client.post(
            url,
            {
                "confirmation": "EXCLUIR",
                "current_password": "senha-incorreta",
            },
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A senha atual não confere")
        self.assertTrue(Transaction.objects.filter(pk=pluggy_tx.pk).exists())

        response = self.client.post(
            url,
            {
                "confirmation": "EXCLUIR",
                "current_password": "Senha-Muito-Forte-123!",
            },
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Transaction.objects.filter(pk=pluggy_tx.pk).exists())


class PluggyUnderlyingBankClassificationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="pluggy-bank-classifier",
            password="Senha-Muito-Forte-123!",
        )
        self.config = PluggyConfiguration(name="Pluggy Bancos", client_id="client-banks")
        self.config.set_client_secret("secret-banks")
        self.config.save()
        self.item = PluggyItem.objects.create(
            configuration=self.config,
            item_id="91919191-9191-9191-9191-919191919191",
            connector_id=200,
            connector_name="MeuPluggy",
            status="UPDATED",
            created_by=self.user,
        )

    @patch("integrations.pluggy_sync.list_accounts")
    def test_meu_pluggy_creates_bank_from_underlying_institution(self, mocked):
        mocked.return_value = [
            {
                "id": "92929292-9292-9292-9292-929292929292",
                "type": "BANK",
                "subtype": "CHECKING_ACCOUNT",
                "number": "08614777-3",
                "name": "PICPAY INSTITUIÇÃO DE PAGAMENTO S.A (Conta Pré-paga)",
                "marketingName": "PICPAY INSTITUIÇÃO DE PAGAMENTO S.A (Conta Pré-paga)",
                "balance": 0.42,
                "currencyCode": "BRL",
                "bankData": {},
            },
            {
                "id": "93939393-9393-9393-9393-939393939393",
                "type": "BANK",
                "subtype": "CHECKING_ACCOUNT",
                "number": "634385454-2",
                "name": "RecargaPay (Conta Pré-paga)",
                "marketingName": "RecargaPay (Conta Pré-paga)",
                "balance": 0,
                "currencyCode": "BRL",
                "bankData": {},
            },
        ]

        accounts, created = upsert_accounts(self.item)

        self.assertEqual(created, 2)
        self.assertEqual({account.detected_bank_name for account in accounts}, {"PicPay", "RecargaPay"})
        self.assertEqual(
            {account.local_account.bank.name for account in accounts},
            {"PicPay", "RecargaPay"},
        )
        self.assertFalse(Bank.objects.filter(name__iexact="MeuPluggy").exists())
        self.assertTrue(all(account.local_account_created_by_pluggy for account in accounts))
        self.assertTrue(all(account.local_bank_created_by_pluggy for account in accounts))

    @patch("integrations.pluggy_sync.list_accounts")
    def test_legacy_meupluggy_bank_is_reclassified_without_recreating_transaction(self, mocked):
        legacy_bank = Bank.objects.create(name="MeuPluggy", code="000")
        remote_id = "94949494-9494-9494-9494-949494949494"
        legacy_account = Account.objects.create(
            bank=legacy_bank,
            nickname="PICPAY INSTITUIÇÃO DE PAGAMENTO S.A (Conta Pré-paga)",
            number=f"PLUGGY-{remote_id[:12]}",
            account_type=Account.AccountType.CHECKING,
            currency="BRL",
            ofx_account_id=f"PLUGGY:{remote_id}",
            is_own_account=True,
        )
        remote = PluggyAccount.objects.create(
            item=self.item,
            pluggy_account_id=remote_id,
            local_account=legacy_account,
            remote_type="BANK",
            subtype="CHECKING_ACCOUNT",
            name="PICPAY INSTITUIÇÃO DE PAGAMENTO S.A (Conta Pré-paga)",
            currency="BRL",
            local_account_created_by_pluggy=True,
            local_bank_created_by_pluggy=True,
        )
        tx = Transaction.objects.create(
            account=legacy_account,
            posted_at=timezone.now(),
            competence_date=timezone.localdate(),
            amount="10.00",
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.API,
            fitid="PLUGGY:legacy-reclassify",
            raw_description="PIX TESTE",
            normalized_description="PIX TESTE",
            fingerprint="e" * 64,
            raw_data={"provider": "PLUGGY"},
            created_by=self.user,
        )
        mocked.return_value = [
            {
                "id": remote_id,
                "type": "BANK",
                "subtype": "CHECKING_ACCOUNT",
                "number": "08614777-3",
                "name": "PICPAY INSTITUIÇÃO DE PAGAMENTO S.A (Conta Pré-paga)",
                "marketingName": "PICPAY INSTITUIÇÃO DE PAGAMENTO S.A (Conta Pré-paga)",
                "balance": 0.42,
                "currencyCode": "BRL",
                "bankData": {},
            }
        ]

        accounts, created = upsert_accounts(self.item)

        self.assertEqual(created, 0)
        remote.refresh_from_db()
        legacy_account.refresh_from_db()
        tx.refresh_from_db()
        self.assertEqual(remote.local_account_id, legacy_account.pk)
        self.assertEqual(legacy_account.bank.name, "PicPay")
        self.assertEqual(tx.account_id, legacy_account.pk)
        self.assertFalse(Bank.objects.filter(pk=legacy_bank.pk).exists())


class PluggyAccountSimilarityAndIdentityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="pluggy-match-user",
            password="Senha-Muito-Forte-123!",
        )
        self.config = PluggyConfiguration(name="Pluggy", client_id="client-match")
        self.config.set_client_secret("secret")
        self.config.save()
        self.item = PluggyItem.objects.create(
            configuration=self.config,
            item_id="99999999-1111-2222-3333-444444444444",
            connector_id=200,
            connector_name="MeuPluggy",
            status="UPDATED",
            execution_status="SUCCESS",
        )
        self.bank = Bank.objects.create(name="Nubank", code="260")
        self.existing = Account.objects.create(
            bank=self.bank,
            nickname="Nubank",
            branch="0001",
            number="530540",
            digit="6",
            ofx_account_id="530540-6",
        )

    @patch("integrations.pluggy_sync.list_accounts")
    def test_leading_zero_account_is_suggested_instead_of_duplicated(self, mocked):
        from integrations.pluggy_sync import resolve_account_similarity

        mocked.return_value = [{
            "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "type": "BANK",
            "subtype": "CHECKING_ACCOUNT",
            "number": "00530540-6",
            "name": "Nu Pagamentos S.A. - Instituição de Pagamento (Conta Pré-paga)",
            "marketingName": "Nubank",
            "balance": 10.25,
            "currencyCode": "BRL",
            "owner": "Titular Teste",
            "taxNumber": "123.456.789-09",
            "bankData": {"transferNumber": "260/0001/00530540-6"},
        }]

        accounts, created = upsert_accounts(self.item)

        self.assertEqual(created, 0)
        remote = accounts[0]
        self.assertIsNone(remote.local_account_id)
        self.assertEqual(remote.suggested_account_id, self.existing.pk)
        self.assertEqual(remote.match_status, PluggyAccount.MatchStatus.REVIEW)
        self.assertGreaterEqual(remote.match_score, 90)
        self.assertEqual(Account.objects.filter(bank=self.bank).count(), 1)

        linked = resolve_account_similarity(remote, action="use_existing")
        linked.refresh_from_db()
        remote.refresh_from_db()
        self.assertEqual(linked.pk, self.existing.pk)
        self.assertEqual(remote.local_account_id, self.existing.pk)
        self.assertEqual(remote.match_status, PluggyAccount.MatchStatus.MANUAL)
        self.assertEqual(linked.holder_name, "Titular Teste")
        self.assertEqual(linked.holder_tax_id, "123.456.789-09")


    @patch("integrations.pluggy_sync.list_accounts")
    def test_account_number_fallback_matches_existing_when_transfer_number_is_missing(self, mocked):
        mocked.return_value = [{
            "id": "dddddddd-eeee-ffff-0000-111111111111",
            "type": "BANK",
            "subtype": "CHECKING_ACCOUNT",
            "number": "00530540-6",
            "name": "Nubank",
            "marketingName": "Nubank",
            "balance": 10.25,
            "currencyCode": "BRL",
            "owner": "Titular Teste",
            "taxNumber": "123.456.789-09",
            "bankData": {},
        }]

        accounts, created = upsert_accounts(self.item)

        self.assertEqual(created, 0)
        remote = accounts[0]
        self.assertIsNone(remote.local_account_id)
        self.assertEqual(remote.suggested_account_id, self.existing.pk)
        self.assertEqual(remote.match_status, PluggyAccount.MatchStatus.REVIEW)
        self.assertGreaterEqual(remote.match_score, 90)
        self.assertIn("agência ausente", remote.match_reason)

    @patch("integrations.pluggy_sync.list_all_transactions")
    def test_payment_data_links_structured_counterparty(self, mocked):
        remote = PluggyAccount.objects.create(
            item=self.item,
            pluggy_account_id="bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
            local_account=self.existing,
            remote_type="BANK",
            subtype="CHECKING_ACCOUNT",
            name="Nubank",
            currency="BRL",
        )
        mocked.return_value = [{
            "id": "cccccccc-dddd-eeee-ffff-000000000001",
            "providerId": "provider-payment-data-1",
            "date": "2026-09-08T12:00:00.000Z",
            "description": "Transferência enviada",
            "amount": -8,
            "type": "DEBIT",
            "status": "POSTED",
            "currencyCode": "BRL",
            "paymentData": {
                "receiver": {
                    "name": "JOAO BARBOSA DE SOUSA",
                    "routingNumber": "104",
                    "routingNumberISPB": "00360305",
                    "documentNumber": {"type": "CPF", "value": "123.456.789-09"},
                }
            },
        }]

        result = sync_account_transactions(remote, user=self.user)

        self.assertEqual(result["created"], 1)
        tx = Transaction.objects.get(fitid="PLUGGY-PROVIDER:provider-payment-data-1")
        self.assertIsNotNone(tx.counterparty_id)
        self.assertEqual(tx.counterparty_raw_name, "JOAO BARBOSA DE SOUSA")
        self.assertEqual(tx.counterparty.tax_id, "12345678909")


class PluggySimilarityDecisionRegressionTests(TestCase):
    """Regressões do fluxo de decisão manual de contas semelhantes."""

    def setUp(self):
        self.password = "Senha-Muito-Forte-123!"
        self.user = get_user_model().objects.create_superuser(
            username="pluggy-regression-admin",
            email="admin@example.test",
            password=self.password,
        )
        self.config = PluggyConfiguration(name="Pluggy", client_id="client")
        self.config.set_client_secret("secret")
        self.config.save()
        self.item = PluggyItem.objects.create(
            configuration=self.config,
            item_id="12121212-3434-5656-7878-909090909090",
            connector_id=200,
            connector_name="MeuPluggy",
            status="UPDATED",
            execution_status="SUCCESS",
        )
        self.bank = Bank.objects.create(name="Nubank", code="260")
        self.target = Account.objects.create(
            bank=self.bank,
            nickname="Nubank existente",
            branch="0001",
            number="530540",
            digit="6",
            ofx_account_id="530540-6",
        )
        self.source = Account.objects.create(
            bank=self.bank,
            nickname="Nubank via Pluggy",
            branch="",
            number="00530540",
            digit="6",
            ofx_account_id="PLUGGY:abababab-abab-abab-abab-abababababab",
        )
        self.remote = PluggyAccount.objects.create(
            item=self.item,
            pluggy_account_id="abababab-abab-abab-abab-abababababab",
            local_account=self.source,
            suggested_account=self.target,
            remote_type="BANK",
            subtype="CHECKING_ACCOUNT",
            name="Nu Pagamentos S.A.",
            masked_number="00530540-6",
            currency="BRL",
            match_status=PluggyAccount.MatchStatus.REVIEW,
            match_score=100,
            match_reason="mesmo número de conta após normalizar zeros",
            local_account_created_by_pluggy=True,
        )
        self.transaction = Transaction.objects.create(
            account=self.source,
            posted_at=timezone.now(),
            competence_date=timezone.localdate(),
            amount="10.00",
            direction=Transaction.Direction.DEBIT,
            transaction_type=Transaction.TransactionType.OTHER,
            source_type=Transaction.SourceType.API,
            fitid="PLUGGY:transaction-regression",
            raw_description="Teste de migração de conta",
            normalized_description="Teste de migração de conta",
            raw_data={"provider": "PLUGGY"},
        )
        PluggyTransactionLink.objects.create(
            pluggy_account=self.remote,
            remote_transaction_id="transaction-regression",
            transaction=self.transaction,
            remote_hash="hash-regression",
        )

    def test_use_existing_view_moves_pluggy_transactions_to_existing_account(self):
        from django.urls import reverse

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("integrations:pluggy-resolve-account-similarity", args=[self.remote.pk]),
            {"current_password": self.password, "action": "use_existing"},
        )

        self.assertEqual(response.status_code, 302)
        self.remote.refresh_from_db()
        self.transaction.refresh_from_db()
        self.assertEqual(self.remote.local_account_id, self.target.pk)
        self.assertEqual(self.transaction.account_id, self.target.pk)
        self.assertEqual(self.remote.match_status, PluggyAccount.MatchStatus.MANUAL)

    @patch("integrations.pluggy_sync.retrieve_item")
    def test_missing_remote_item_error_preserves_context(self, mocked_retrieve):
        from integrations.pluggy import PluggyApiError
        from integrations.pluggy_sync import refresh_item

        mocked_retrieve.side_effect = PluggyApiError("item not found", status_code=404)
        with self.assertRaises(PluggyApiError) as raised:
            refresh_item(self.item)

        self.assertEqual(raised.exception.status_code, 404)
        message = str(raised.exception)
        self.assertIn(self.item.item_id, message)
        self.assertIn("dados já copiados", message)
        self.assertIn("mesma aplicação/credenciais", message)
