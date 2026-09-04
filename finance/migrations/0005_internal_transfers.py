from django.conf import settings
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import migrations
from django.db import models
import django.db.models.deletion
from django.db.models import F
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(
            settings.AUTH_USER_MODEL
        ),
        (
            "finance",
            "0004_transaction_source_types",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="is_own_account",
            field=models.BooleanField(
                db_index=True,
                default=True,
                help_text=(
                    "Marque para contas do próprio titular. "
                    "O sistema usa esta informação para separar transferências "
                    "entre contas próprias de entradas/saídas externas."
                ),
                verbose_name="Esta conta é minha",
            ),
        ),
        migrations.CreateModel(
            name="InternalTransfer",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            (
                                "POSSIBLE",
                                "Possível transferência interna",
                            ),
                            (
                                "CONFIRMED",
                                "Transferência interna",
                            ),
                            (
                                "REJECTED",
                                "Não é transferência interna",
                            ),
                        ],
                        db_index=True,
                        default="POSSIBLE",
                        max_length=12,
                        verbose_name="Situação",
                    ),
                ),
                (
                    "match_method",
                    models.CharField(
                        choices=[
                            ("AUTOMATIC", "Automático"),
                            ("MANUAL", "Manual"),
                        ],
                        db_index=True,
                        default="AUTOMATIC",
                        max_length=12,
                        verbose_name="Método",
                    ),
                ),
                (
                    "confidence",
                    models.PositiveSmallIntegerField(
                        default=0,
                        help_text="Pontuação heurística de 0 a 100.",
                        validators=[
                            MinValueValidator(0),
                            MaxValueValidator(100),
                        ],
                        verbose_name="Confiança",
                    ),
                ),
                (
                    "match_reasons",
                    models.JSONField(
                        blank=True,
                        default=list,
                        verbose_name="Evidências",
                    ),
                ),
                (
                    "reviewed_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Revisado em",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Criado em",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="Atualizado em",
                    ),
                ),
                (
                    "credit_transaction",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="internal_transfer_credit_matches",
                        to="finance.transaction",
                        verbose_name="Entrada",
                    ),
                ),
                (
                    "debit_transaction",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="internal_transfer_debit_matches",
                        to="finance.transaction",
                        verbose_name="Saída",
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviewed_internal_transfers",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Revisado por",
                    ),
                ),
            ],
            options={
                "verbose_name": "Transferência interna",
                "verbose_name_plural": "Transferências internas",
                "ordering": [
                    "-status",
                    "-confidence",
                    "-created_at",
                ],
                "indexes": [
                    models.Index(
                        fields=[
                            "status",
                            "-created_at",
                        ],
                        name="fin_int_status_created_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=~Q(
                            debit_transaction=F(
                                "credit_transaction"
                            )
                        ),
                        name="fin_internal_transfer_distinct_legs",
                    ),
                    models.UniqueConstraint(
                        condition=Q(
                            status__in=[
                                "POSSIBLE",
                                "CONFIRMED",
                            ]
                        ),
                        fields=(
                            "debit_transaction",
                        ),
                        name="fin_internal_transfer_active_debit_unique",
                    ),
                    models.UniqueConstraint(
                        condition=Q(
                            status__in=[
                                "POSSIBLE",
                                "CONFIRMED",
                            ]
                        ),
                        fields=(
                            "credit_transaction",
                        ),
                        name="fin_internal_transfer_active_credit_unique",
                    ),
                ],
            },
        ),
    ]
