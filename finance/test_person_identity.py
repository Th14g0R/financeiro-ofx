from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from finance.models import Account, Bank, Counterparty, CounterpartyAlias, Transaction
from services.counterparties.resolver import (
    rebuild_counterparty_links,
    resolve_transaction_counterparty,
)


class PersonIdentityTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            bank=Bank.objects.create(name="Banco", code="999"),
            nickname="Conta", branch="1", number="123",
        )

    def movement(self, name, document="", bank="00000000"):
        return Transaction.objects.create(
            account=self.account, posted_at=timezone.now(), amount=Decimal("10"),
            direction=Transaction.Direction.DEBIT,
            transaction_type=Transaction.TransactionType.TRANSFER,
            source_type=Transaction.SourceType.OFX,
            fitid=f"PERSON-{Transaction.objects.count()}",
            raw_description=f"Transferencia enviada|{name}",
            payment_details={"receiver": {
                "name": name, "document_number": document,
                "routing_number_ispb": bank,
            }},
        )

    def test_shared_ispb_never_merges_different_people(self):
        for bank in ("00000000", "90400888"):
            first = resolve_transaction_counterparty(self.movement("MUNDAU MOVEIS LTDA", bank=bank))
            second = resolve_transaction_counterparty(self.movement("MINISTERIO DA FAZENDA", bank=bank))
            self.assertNotEqual(first.pk, second.pk)

    def test_same_name_different_documents_stays_separate_after_rebuild(self):
        first = self.movement("JOAO DA SILVA", "12345678901")
        second = self.movement("JOAO DA SILVA", "12345678902")
        resolve_transaction_counterparty(first)
        resolve_transaction_counterparty(second)
        rebuild_counterparty_links()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertNotEqual(first.counterparty_id, second.counterparty_id)
        self.assertEqual(Counterparty.objects.filter(is_active=True).count(), 2)

    def test_same_document_different_name_and_bank_reuses_person(self):
        first = resolve_transaction_counterparty(self.movement("JOAO DA SILVA", "12345678901"))
        second = resolve_transaction_counterparty(self.movement("JOAO SILVA", "12345678901", "90400888"))
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(rebuild_counterparty_links(repair_bank_groups=True)["quarantined"], 0)

    def test_shared_masked_document_does_not_merge_different_names(self):
        first = self.movement("JOAO DA SILVA")
        second = self.movement("MARIA DA SILVA")
        for tx, name in ((first, "JOAO DA SILVA"), (second, "MARIA DA SILVA")):
            tx.payment_details = {}
            tx.raw_description = f"Transferência recebida pelo Pix - {name} - ***.123.456-**"
            resolve_transaction_counterparty(tx)
        self.assertNotEqual(first.counterparty_id, second.counterparty_id)

    def test_repair_separates_contaminated_group_and_is_idempotent(self):
        first = self.movement("MUNDAU MOVEIS LTDA", "12345678000101")
        second = self.movement("MINISTERIO DA FAZENDA", "12345678000102")
        group = resolve_transaction_counterparty(first)
        CounterpartyAlias.objects.create(
            counterparty=group, alias="MINISTERIO DA FAZENDA",
            normalized_alias="MINISTERIO DA FAZENDA", alias_type="NAME",
        )
        CounterpartyAlias.objects.create(
            counterparty=group, alias="12345678000102",
            normalized_alias="12345678000102", alias_type="TAX_ID",
        )
        second.counterparty = group
        second.save()
        result = rebuild_counterparty_links(repair_bank_groups=True)
        first.refresh_from_db()
        second.refresh_from_db()
        group.refresh_from_db()
        self.assertEqual(result["quarantined"], 1)
        self.assertFalse(group.is_active)
        self.assertNotEqual(first.counterparty_id, second.counterparty_id)
        self.assertEqual(first.counterparty.tax_id, "12345678000101")
        self.assertEqual(second.counterparty.tax_id, "12345678000102")
        before = (first.counterparty_id, second.counterparty_id)
        self.assertEqual(rebuild_counterparty_links(repair_bank_groups=True)["reassigned"], 0)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(before, (first.counterparty_id, second.counterparty_id))

    def test_detail_paginates_preserving_full_totals(self):
        self.client.force_login(get_user_model().objects.create_user(username="person-test"))
        person = resolve_transaction_counterparty(self.movement("JOAO DA SILVA"))
        for _ in range(50):
            tx = self.movement("JOAO DA SILVA")
            tx.counterparty = person
            tx.save()
        response = self.client.get(reverse("finance:counterparty-detail", args=[person.pk]), {"page": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["transactions"]), 1)
        self.assertEqual(response.context["transaction_count"], 51)
        self.assertEqual(response.context["total_debit"], Decimal("510"))

    def test_old_group_url_redirects_to_current_people(self):
        self.client.force_login(get_user_model().objects.create_user(username="archive-test"))
        person = Counterparty.objects.create(
            display_name="Grupo antigo", normalized_name="GRUPO ANTIGO", is_active=False,
        )
        response = self.client.get(reverse("finance:counterparty-detail", args=[person.pk]))
        self.assertRedirects(response, reverse("finance:counterparty-list"))
