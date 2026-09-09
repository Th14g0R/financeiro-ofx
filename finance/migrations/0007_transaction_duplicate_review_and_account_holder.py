from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("finance", "0006_counterparty_bank_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="holder_name",
            field=models.CharField(
                blank=True,
                help_text="Nome do titular informado pela instituição/Open Finance, quando disponível.",
                max_length=200,
                verbose_name="Titular",
            ),
        ),
        migrations.AddField(
            model_name="account",
            name="holder_tax_id",
            field=models.CharField(
                blank=True,
                help_text="Documento do titular informado pela instituição/Open Finance, quando disponível.",
                max_length=32,
                verbose_name="CPF/CNPJ do titular",
            ),
        ),
        migrations.AddField(
            model_name="transaction",
            name="is_financially_ignored",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text=(
                    "Mantém o lançamento para auditoria/proveniência, mas o exclui "
                    "dos totais e gráficos financeiros após revisão de duplicidade."
                ),
                verbose_name="Ignorar nos totais financeiros",
            ),
        ),
        migrations.AddField(
            model_name="transaction",
            name="ignored_reason",
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name="Motivo da exclusão financeira",
            ),
        ),
        migrations.AddField(
            model_name="transaction",
            name="canonical_transaction",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Quando este lançamento foi descartado/mesclado como duplicado, "
                    "aponta para a movimentação mantida como canônica."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="merged_duplicates",
                to="finance.transaction",
                verbose_name="Movimentação canônica",
            ),
        ),
        migrations.CreateModel(
            name="TransactionDuplicateReview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("classification", models.CharField(
                    choices=[("EXACT", "Duplicidade muito provável"), ("POSSIBLE", "Possível duplicidade")],
                    db_index=True,
                    max_length=12,
                    verbose_name="Classificação",
                )),
                ("confidence", models.PositiveSmallIntegerField(
                    default=0,
                    validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)],
                    verbose_name="Confiança",
                )),
                ("match_reasons", models.JSONField(blank=True, default=list, verbose_name="Evidências")),
                ("status", models.CharField(
                    choices=[
                        ("PENDING", "Pendente de revisão"),
                        ("KEEP_BOTH", "Manter as duas"),
                        ("KEEP_FIRST", "Manter primeira"),
                        ("KEEP_SECOND", "Manter segunda"),
                        ("MERGED_FIRST", "Mesclada na primeira"),
                        ("MERGED_SECOND", "Mesclada na segunda"),
                    ],
                    db_index=True,
                    default="PENDING",
                    max_length=16,
                    verbose_name="Situação",
                )),
                ("reviewed_at", models.DateTimeField(blank=True, null=True, verbose_name="Revisado em")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Atualizado em")),
                ("first_transaction", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="duplicate_reviews_as_first",
                    to="finance.transaction",
                    verbose_name="Primeira movimentação",
                )),
                ("second_transaction", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="duplicate_reviews_as_second",
                    to="finance.transaction",
                    verbose_name="Segunda movimentação",
                )),
                ("reviewed_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="reviewed_transaction_duplicates",
                    to=settings.AUTH_USER_MODEL,
                    verbose_name="Revisado por",
                )),
            ],
            options={
                "verbose_name": "Revisão de duplicidade",
                "verbose_name_plural": "Revisões de duplicidade",
                "ordering": ["status", "-confidence", "-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="transactionduplicatereview",
            constraint=models.CheckConstraint(
                condition=models.Q(("first_transaction_id__lt", models.F("second_transaction_id"))),
                name="fin_dup_review_ordered_pair",
            ),
        ),
        migrations.AddConstraint(
            model_name="transactionduplicatereview",
            constraint=models.UniqueConstraint(
                fields=("first_transaction", "second_transaction"),
                name="fin_dup_review_unique_pair",
            ),
        ),
        migrations.AddIndex(
            model_name="transactionduplicatereview",
            index=models.Index(fields=["status", "-confidence"], name="fin_dup_status_conf_idx"),
        ),
    ]
