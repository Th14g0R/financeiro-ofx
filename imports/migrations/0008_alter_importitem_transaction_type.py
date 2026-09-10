from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0007_importbatch_cleanup_archive"),
    ]

    operations = [
        migrations.AlterField(
            model_name="importitem",
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
                max_length=24,
                verbose_name="Tipo",
            ),
        ),
    ]
