import re
import unicodedata

from django.db import migrations, models


POCKET_MARKERS = (
    "COFRINHO",
    "COFRINHOS",
    "COFRE",
    "DINHEIRO GUARDADO",
    "GUARDAR DINHEIRO",
    "RESERVAR DINHEIRO",
    "DINHEIRO RESERVADO",
    "RESERVA AUTOMATICA",
    "TRANSFERENCIA PARA COFRINHO",
    "TRANSFERENCIA PRO COFRINHO",
    "TRANSFERENCIA DO COFRINHO",
    "TRANSFERENCIA DE COFRINHO",
    "DEPOSITO NO COFRINHO",
    "RETIRADA DO COFRINHO",
    "RETIRAR DO COFRINHO",
    "RESGATE DO COFRINHO",
    "RESGATE DE COFRINHO",
)
YIELD_MARKERS = (
    "RENDIMENTO",
    "RENDIMENTOS",
    "RENTABILIDADE",
    "JUROS",
    "INTEREST",
    " CDI ",
)
PIX_KEYS = {
    "pixkey",
    "pix_key",
    "receiverpixkey",
    "receiver_pix_key",
    "payerpixkey",
    "payer_pix_key",
    "dictkey",
    "dict_key",
}


def _normalize(value):
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " " + re.sub(r"[^A-Za-z0-9]+", " ", ascii_text).upper().strip() + " "


def _find_pix_key(value, depth=0):
    if depth > 4:
        return ""
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).replace("-", "_").lower()
            if normalized in PIX_KEYS and nested not in (None, "", {}, []):
                return str(nested).strip()[:255]
        for nested in value.values():
            found = _find_pix_key(nested, depth + 1)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value[:20]:
            found = _find_pix_key(nested, depth + 1)
            if found:
                return found
    return ""


def _participant(participant, bank_names):
    if not isinstance(participant, dict):
        return {}
    document = participant.get("documentNumber")
    if isinstance(document, dict):
        document_type = str(document.get("type") or "").strip()
        document_value = str(document.get("value") or "").strip()
    else:
        document_type = ""
        document_value = str(document or "").strip()

    routing_number = str(participant.get("routingNumber") or "").strip()[:16]
    routing_digits = re.sub(r"\D", "", routing_number)
    bank_name = ""
    if routing_digits:
        bank_name = bank_names.get(routing_digits[-3:].zfill(3), "")

    result = {
        "name": str(participant.get("name") or "").strip()[:255],
        "branch_number": str(participant.get("branchNumber") or "").strip()[:40],
        "account_number": str(participant.get("accountNumber") or "").strip()[:80],
        "bank_name": str(bank_name)[:120],
        "routing_number": routing_number,
        "routing_number_ispb": str(participant.get("routingNumberISPB") or "").strip()[:32],
        "document_type": document_type[:16],
        "document_number": document_value[:32],
    }
    return {key: value for key, value in result.items() if value}


def backfill_pluggy_metadata(apps, schema_editor):
    Transaction = apps.get_model("finance", "Transaction")
    Bank = apps.get_model("finance", "Bank")
    bank_names = {
        str(code).zfill(3): name
        for code, name in Bank.objects.exclude(code="").values_list("code", "name")
    }

    queryset = Transaction.objects.filter(source_type="API")
    for transaction in queryset.iterator(chunk_size=500):
        raw_data = transaction.raw_data if isinstance(transaction.raw_data, dict) else {}
        is_pluggy = str(raw_data.get("provider") or "").upper() == "PLUGGY"
        payload = raw_data.get("pluggy") if is_pluggy else {}
        if not isinstance(payload, dict):
            payload = {}

        changed = []
        payment_data = payload.get("paymentData") if is_pluggy else None
        details = {}
        if isinstance(payment_data, dict):
            details = {
                "payer": _participant(payment_data.get("payer"), bank_names),
                "receiver": _participant(payment_data.get("receiver"), bank_names),
                "payment_method": str(payment_data.get("paymentMethod") or "").strip()[:32],
                "reason": str(payment_data.get("reason") or "").strip()[:255],
                "reference_number": str(payment_data.get("referenceNumber") or "").strip()[:120],
                "receiver_reference_id": str(payment_data.get("receiverReferenceId") or "").strip()[:120],
                "authentication_code": str(payment_data.get("authenticationCode") or "").strip()[:120],
            }
            pix_key = _find_pix_key(payment_data) or _find_pix_key(payload)
            if pix_key:
                details["pix_key"] = pix_key
            details = {
                key: value
                for key, value in details.items()
                if value not in (None, "", {}, [])
            }
        if details and transaction.payment_details != details:
            transaction.payment_details = details
            changed.append("payment_details")

        text = _normalize(
            " ".join(
                str(value or "")
                for value in (
                    transaction.raw_description,
                    transaction.normalized_description,
                    payload.get("description"),
                    payload.get("descriptionRaw"),
                    payload.get("category"),
                    payload.get("operationType"),
                    payload.get("operationTypeAdditionalInfo"),
                    payment_data.get("reason") if isinstance(payment_data, dict) else "",
                )
            )
        )

        is_yield = any(marker in text for marker in YIELD_MARKERS)
        if is_yield and transaction.transaction_type != "INTEREST":
            transaction.transaction_type = "INTEREST"
            changed.append("transaction_type")

        is_internal = False
        reason = ""
        if not is_yield:
            marker = next((item for item in POCKET_MARKERS if item in text), "")
            if marker:
                is_internal = True
                reason = (
                    "Movimentação entre saldo disponível e reserva/cofrinho "
                    f"({marker.title()})."
                )[:255]

        if transaction.is_internal_balance_movement != is_internal:
            transaction.is_internal_balance_movement = is_internal
            changed.append("is_internal_balance_movement")
        if transaction.internal_balance_reason != reason:
            transaction.internal_balance_reason = reason
            changed.append("internal_balance_reason")

        if changed:
            transaction.save(update_fields=list(dict.fromkeys(changed)))


def noop_reverse(apps, schema_editor):
    # Campos são removidos automaticamente se a migration for revertida.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0007_transaction_duplicate_review_and_account_holder"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="payment_details",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Dados normalizados de pagador/recebedor, banco, agência, conta, "
                    "meio de pagamento e referências, quando fornecidos pela origem."
                ),
                verbose_name="Detalhes estruturados do pagamento",
            ),
        ),
        migrations.AddField(
            model_name="transaction",
            name="is_internal_balance_movement",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text=(
                    "Marca movimentações entre o saldo disponível e reservas/cofrinhos da mesma conta. "
                    "Esses valores permanecem no extrato, mas não compõem entrada/saída externa."
                ),
                verbose_name="Movimentação interna no saldo da própria conta",
            ),
        ),
        migrations.AddField(
            model_name="transaction",
            name="internal_balance_reason",
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name="Motivo da movimentação interna no saldo",
            ),
        ),
        migrations.AlterField(
            model_name="transaction",
            name="transaction_type",
            field=models.CharField(
                choices=[
                    ("PIX", "PIX"),
                    ("TED", "TED"),
                    ("DOC", "DOC"),
                    ("TRANSFER", "Transferência"),
                    ("CARD_PURCHASE", "Compra no cartão"),
                    ("PAYMENT", "Pagamento"),
                    ("FEE", "Tarifa"),
                    ("INTEREST", "Rendimento / juros"),
                    ("CASH_WITHDRAWAL", "Saque"),
                    ("CASH_DEPOSIT", "Depósito"),
                    ("REFUND", "Estorno"),
                    ("OTHER", "Outro"),
                ],
                default="OTHER",
                max_length=24,
                verbose_name="Tipo",
            ),
        ),
        migrations.AlterField(
            model_name="transactionduplicatereview",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pendente de revisão"),
                    ("KEEP_BOTH", "Manter as duas"),
                    ("KEEP_FIRST", "Manter primeira"),
                    ("KEEP_SECOND", "Manter segunda"),
                    ("MERGED_FIRST", "Mesclada na primeira"),
                    ("MERGED_SECOND", "Mesclada na segunda"),
                    ("GROUP_RESOLVED", "Resolvida em grupo"),
                ],
                db_index=True,
                default="PENDING",
                max_length=16,
                verbose_name="Situação",
            ),
        ),
        migrations.RunPython(backfill_pluggy_metadata, noop_reverse),
    ]
