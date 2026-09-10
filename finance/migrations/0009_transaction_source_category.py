from django.db import migrations, models


def backfill_pluggy_categories(apps, schema_editor):
    Transaction = apps.get_model("finance", "Transaction")
    Category = apps.get_model("finance", "Category")

    queryset = Transaction.objects.filter(source_type="API")
    for transaction in queryset.iterator(chunk_size=500):
        raw_data = transaction.raw_data if isinstance(transaction.raw_data, dict) else {}
        if str(raw_data.get("provider") or "").upper() != "PLUGGY":
            continue

        payload = raw_data.get("pluggy")
        if not isinstance(payload, dict):
            continue

        merchant = payload.get("merchant") if isinstance(payload.get("merchant"), dict) else {}
        source_name = " ".join(
            str(payload.get("category") or merchant.get("category") or "").split()
        )[:120]
        source_id = str(payload.get("categoryId") or "").strip()[:64]
        update_fields = []

        if transaction.source_category_name != source_name:
            transaction.source_category_name = source_name
            update_fields.append("source_category_name")
        if transaction.source_category_id != source_id:
            transaction.source_category_id = source_id
            update_fields.append("source_category_id")

        if source_name and transaction.category_id is None:
            category = Category.objects.filter(name__iexact=source_name).order_by("pk").first()
            if category is None:
                category = Category.objects.create(
                    name=source_name,
                    category_type="BOTH",
                    is_active=True,
                )
            transaction.category_id = category.pk
            transaction.category_assignment_source = "PLUGGY"
            update_fields.extend(["category", "category_assignment_source"])

        if update_fields:
            transaction.save(update_fields=list(dict.fromkeys(update_fields)))


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0008_transaction_payment_details_and_internal_balance"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="source_category_name",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Categoria recebida da fonte original, como a classificação da Pluggy. "
                    "É preservada mesmo quando a categoria local é ajustada manualmente."
                ),
                max_length=120,
                verbose_name="Categoria informada pela origem",
            ),
        ),
        migrations.AddField(
            model_name="transaction",
            name="source_category_id",
            field=models.CharField(
                blank=True,
                max_length=64,
                verbose_name="ID da categoria na origem",
            ),
        ),
        migrations.AddField(
            model_name="transaction",
            name="category_assignment_source",
            field=models.CharField(
                blank=True,
                choices=[("PLUGGY", "Pluggy"), ("MANUAL", "Manual")],
                db_index=True,
                help_text=(
                    "Indica se a categoria local foi sugerida automaticamente pela Pluggy "
                    "ou escolhida manualmente no Financeiro OFX."
                ),
                max_length=16,
                verbose_name="Origem da categoria aplicada",
            ),
        ),
        migrations.RunPython(backfill_pluggy_categories, migrations.RunPython.noop),
    ]
