from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0007_transaction_duplicate_review_and_account_holder"),
        ("integrations", "0003_pluggy_account_provenance"),
    ]

    operations = [
        migrations.AddField(
            model_name="pluggyitem",
            name="identity_data",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Snapshot retornado pelo produto Identity da Pluggy, quando disponível.",
                verbose_name="Identidade do titular",
            ),
        ),
        migrations.AddField(
            model_name="pluggyitem",
            name="last_sync_summary",
            field=models.JSONField(blank=True, default=dict, verbose_name="Resumo da última cópia"),
        ),
        migrations.AddField(
            model_name="pluggyaccount",
            name="owner_name",
            field=models.CharField(blank=True, max_length=200, verbose_name="Titular informado pela Pluggy"),
        ),
        migrations.AddField(
            model_name="pluggyaccount",
            name="owner_tax_number",
            field=models.CharField(blank=True, max_length=32, verbose_name="Documento do titular informado pela Pluggy"),
        ),
        migrations.AddField(
            model_name="pluggyaccount",
            name="match_status",
            field=models.CharField(
                choices=[
                    ("UNCHECKED", "Não analisada"),
                    ("AUTO_CREATED", "Conta criada automaticamente"),
                    ("AUTO_LINKED", "Vinculada automaticamente"),
                    ("REVIEW", "Similaridade para revisar"),
                    ("MANUAL", "Vínculo definido pelo usuário"),
                    ("KEPT_NEW", "Conta separada confirmada"),
                ],
                db_index=True,
                default="UNCHECKED",
                max_length=16,
                verbose_name="Situação do vínculo local",
            ),
        ),
        migrations.AddField(
            model_name="pluggyaccount",
            name="suggested_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="pluggy_account_suggestions",
                to="finance.account",
                verbose_name="Conta local sugerida",
            ),
        ),
        migrations.AddField(
            model_name="pluggyaccount",
            name="match_score",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Confiança da similaridade"),
        ),
        migrations.AddField(
            model_name="pluggyaccount",
            name="match_reason",
            field=models.CharField(blank=True, max_length=255, verbose_name="Motivo da similaridade"),
        ),
    ]
