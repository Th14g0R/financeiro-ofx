from datetime import timedelta

from django.db import migrations, models


def _backfill_pluggy_provenance(apps, schema_editor):
    PluggyAccount = apps.get_model("integrations", "PluggyAccount")

    rows = list(
        PluggyAccount.objects.select_related("local_account", "local_account__bank")
        .exclude(local_account=None)
        .order_by("id")
    )

    by_bank = {}
    for row in rows:
        account = row.local_account
        expected_ofx_id = f"PLUGGY:{row.pluggy_account_id}"
        near_creation = abs(account.created_at - row.created_at) <= timedelta(minutes=10)
        account_owned = account.ofx_account_id == expected_ofx_id and near_creation

        row.local_account_created_by_pluggy = account_owned
        by_bank.setdefault(account.bank_id, []).append((row, account_owned))

    for bank_id, related in by_bank.items():
        # A legacy bank is considered integration-created only when every
        # account currently attached to it is a Pluggy-created account and
        # the bank itself was created in the same short synchronization window.
        bank = related[0][0].local_account.bank
        attached_account_ids = set(bank.accounts.values_list("id", flat=True))
        pluggy_account_ids = {row.local_account_id for row, owned in related if owned}
        bank_near_accounts = all(
            abs(bank.created_at - row.local_account.created_at) <= timedelta(minutes=10)
            for row, owned in related
            if owned
        )
        bank_owned = (
            bool(pluggy_account_ids)
            and attached_account_ids == pluggy_account_ids
            and bank_near_accounts
            and not bank.import_statements.exists()
        )

        for row, account_owned in related:
            row.local_bank_created_by_pluggy = bool(account_owned and bank_owned)
            row.save(
                update_fields=[
                    "local_account_created_by_pluggy",
                    "local_bank_created_by_pluggy",
                ]
            )


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0002_pluggy"),
        ("imports", "0006_importfile_provider_astropay"),
    ]

    operations = [
        migrations.AddField(
            model_name="pluggyaccount",
            name="detected_bank_name",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Instituição financeira identificada a partir dos dados da conta. "
                    "No conector Meu Pluggy, é o banco real por trás do proxy."
                ),
                max_length=120,
                verbose_name="Banco detectado",
            ),
        ),
        migrations.AddField(
            model_name="pluggyaccount",
            name="detected_bank_code",
            field=models.CharField(
                blank=True,
                max_length=3,
                verbose_name="Código bancário detectado",
            ),
        ),
        migrations.AddField(
            model_name="pluggyaccount",
            name="local_account_created_by_pluggy",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Marca de proveniência usada para permitir limpeza segura de "
                    "contas criadas automaticamente pela integração."
                ),
                verbose_name="Conta local criada pela Pluggy",
            ),
        ),
        migrations.AddField(
            model_name="pluggyaccount",
            name="local_bank_created_by_pluggy",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Marca de proveniência usada para permitir limpeza segura de "
                    "bancos criados automaticamente pela integração."
                ),
                verbose_name="Banco local criado pela Pluggy",
            ),
        ),
        migrations.RunPython(_backfill_pluggy_provenance, _noop_reverse),
    ]
