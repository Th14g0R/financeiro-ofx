from django.db import migrations
from django.db import models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Bank",
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
                    "name",
                    models.CharField(
                        max_length=120,
                        unique=True,
                        verbose_name="Nome",
                    ),
                ),
                (
                    "code",
                    models.CharField(
                        blank=True,
                        help_text=(
                            "Código bancário de 3 dígitos, quando aplicável."
                        ),
                        max_length=3,
                        verbose_name="Código COMPE",
                    ),
                ),
                (
                    "ofx_bank_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        help_text=(
                            "Identificador BANKID informado pelo arquivo OFX."
                        ),
                        max_length=32,
                        verbose_name="BANKID do OFX",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        verbose_name="Ativo",
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
            ],
            options={
                "verbose_name": "Banco",
                "verbose_name_plural": "Bancos",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="Account",
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
                    "nickname",
                    models.CharField(
                        help_text="Ex.: Principal, Empresa, Reserva.",
                        max_length=120,
                        verbose_name="Apelido",
                    ),
                ),
                (
                    "branch",
                    models.CharField(
                        blank=True,
                        max_length=20,
                        verbose_name="Agência",
                    ),
                ),
                (
                    "number",
                    models.CharField(
                        max_length=40,
                        verbose_name="Conta",
                    ),
                ),
                (
                    "digit",
                    models.CharField(
                        blank=True,
                        max_length=10,
                        verbose_name="Dígito",
                    ),
                ),
                (
                    "account_type",
                    models.CharField(
                        choices=[
                            ("CHECKING", "Conta corrente"),
                            ("SAVINGS", "Poupança"),
                            ("PAYMENT", "Conta de pagamento"),
                            ("INVESTMENT", "Investimento"),
                            ("OTHER", "Outra"),
                        ],
                        default="CHECKING",
                        max_length=20,
                        verbose_name="Tipo",
                    ),
                ),
                (
                    "currency",
                    models.CharField(
                        default="BRL",
                        max_length=3,
                        verbose_name="Moeda",
                    ),
                ),
                (
                    "ofx_account_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        help_text=(
                            "Identificador ACCTID informado no OFX. "
                            "Será usado para reconhecimento automático da conta."
                        ),
                        max_length=100,
                        verbose_name="ACCTID do OFX",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        verbose_name="Ativa",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Criada em",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="Atualizada em",
                    ),
                ),
                (
                    "bank",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="accounts",
                        to="finance.bank",
                        verbose_name="Banco",
                    ),
                ),
            ],
            options={
                "verbose_name": "Conta",
                "verbose_name_plural": "Contas",
                "ordering": ["bank__name", "nickname"],
            },
        ),
        migrations.AddConstraint(
            model_name="bank",
            constraint=models.UniqueConstraint(
                condition=models.Q(("code", ""), _negated=True),
                fields=("code",),
                name="finance_bank_unique_code_nonempty",
            ),
        ),
        migrations.AddConstraint(
            model_name="bank",
            constraint=models.UniqueConstraint(
                condition=models.Q(("ofx_bank_id", ""), _negated=True),
                fields=("ofx_bank_id",),
                name="finance_bank_unique_ofx_id_nonempty",
            ),
        ),
        migrations.AddConstraint(
            model_name="account",
            constraint=models.UniqueConstraint(
                fields=("bank", "branch", "number", "digit"),
                name="finance_account_unique_bank_branch_number_digit",
            ),
        ),
        migrations.AddConstraint(
            model_name="account",
            constraint=models.UniqueConstraint(
                condition=models.Q(("ofx_account_id", ""), _negated=True),
                fields=("bank", "ofx_account_id"),
                name="finance_account_unique_bank_ofx_id_nonempty",
            ),
        ),
    ]
