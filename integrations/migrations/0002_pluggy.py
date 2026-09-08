from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("finance", "0006_counterparty_bank_id"),
        ("integrations", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PluggyConfiguration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(default="Pluggy / Open Finance", max_length=120, unique=True, verbose_name="Nome")),
                ("client_id", models.CharField(max_length=180, verbose_name="Client ID")),
                ("client_secret_encrypted", models.TextField(verbose_name="Client Secret criptografado")),
                ("api_key_encrypted", models.TextField(blank=True, verbose_name="API Key temporária criptografada")),
                ("api_key_expires_at", models.DateTimeField(blank=True, null=True, verbose_name="API Key expira em")),
                ("status", models.CharField(choices=[("NEW", "Não testada"), ("OK", "Conectada"), ("ERROR", "Erro")], db_index=True, default="NEW", max_length=12, verbose_name="Situação")),
                ("is_active", models.BooleanField(default=True, verbose_name="Ativa")),
                ("last_error", models.TextField(blank=True, verbose_name="Último erro")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Criada em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Atualizada em")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_pluggy_configurations", to=settings.AUTH_USER_MODEL, verbose_name="Criada por")),
            ],
            options={"ordering": ["name", "id"], "verbose_name": "Configuração Pluggy", "verbose_name_plural": "Configurações Pluggy"},
        ),
        migrations.CreateModel(
            name="PluggyItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("item_id", models.CharField(max_length=64, unique=True, verbose_name="Item ID")),
                ("connector_id", models.PositiveIntegerField(blank=True, db_index=True, null=True, verbose_name="Connector ID")),
                ("connector_name", models.CharField(blank=True, max_length=180, verbose_name="Instituição")),
                ("client_user_id", models.CharField(blank=True, max_length=120, verbose_name="Referência do usuário")),
                ("status", models.CharField(blank=True, db_index=True, max_length=40, verbose_name="Situação Pluggy")),
                ("execution_status", models.CharField(blank=True, max_length=60, verbose_name="Execução Pluggy")),
                ("status_detail", models.JSONField(blank=True, default=dict, verbose_name="Detalhes de situação")),
                ("last_updated_at", models.DateTimeField(blank=True, null=True, verbose_name="Última atualização na Pluggy")),
                ("last_sync_at", models.DateTimeField(blank=True, null=True, verbose_name="Última cópia para o Financeiro")),
                ("last_error", models.TextField(blank=True, verbose_name="Último erro")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Ativo")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Atualizado em")),
                ("configuration", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="items", to="integrations.pluggyconfiguration", verbose_name="Configuração")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_pluggy_items", to=settings.AUTH_USER_MODEL, verbose_name="Conectado por")),
            ],
            options={"ordering": ["connector_name", "item_id"], "verbose_name": "Conexão Pluggy", "verbose_name_plural": "Conexões Pluggy"},
        ),
        migrations.CreateModel(
            name="PluggyAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("pluggy_account_id", models.CharField(max_length=64, unique=True, verbose_name="Account ID Pluggy")),
                ("remote_type", models.CharField(blank=True, db_index=True, max_length=20, verbose_name="Tipo Pluggy")),
                ("subtype", models.CharField(blank=True, max_length=60, verbose_name="Subtipo Pluggy")),
                ("name", models.CharField(blank=True, max_length=180, verbose_name="Nome da conta")),
                ("masked_number", models.CharField(blank=True, max_length=120, verbose_name="Número apresentado")),
                ("currency", models.CharField(default="BRL", max_length=3, verbose_name="Moeda")),
                ("balance", models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True, verbose_name="Saldo informado")),
                ("bank_data", models.JSONField(blank=True, default=dict, verbose_name="Dados bancários normalizados")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Ativa")),
                ("last_seen_at", models.DateTimeField(blank=True, null=True, verbose_name="Vista pela última vez")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Criada em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Atualizada em")),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="accounts", to="integrations.pluggyitem", verbose_name="Conexão Pluggy")),
                ("local_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="pluggy_accounts", to="finance.account", verbose_name="Conta local")),
            ],
            options={"ordering": ["item__connector_name", "name", "pluggy_account_id"], "verbose_name": "Conta Pluggy", "verbose_name_plural": "Contas Pluggy"},
        ),
        migrations.CreateModel(
            name="PluggyTransactionLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("remote_transaction_id", models.CharField(max_length=64, verbose_name="Transaction ID Pluggy")),
                ("provider_id", models.CharField(blank=True, db_index=True, max_length=255, verbose_name="Provider ID")),
                ("remote_hash", models.CharField(blank=True, max_length=64, verbose_name="Hash remoto")),
                ("has_conflict", models.BooleanField(db_index=True, default=False, verbose_name="Divergência detectada")),
                ("conflict_fields", models.JSONField(blank=True, default=list, verbose_name="Campos divergentes")),
                ("last_seen_at", models.DateTimeField(blank=True, null=True, verbose_name="Vista pela última vez")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Criada em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Atualizada em")),
                ("pluggy_account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="transaction_links", to="integrations.pluggyaccount", verbose_name="Conta Pluggy")),
                ("transaction", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="pluggy_links", to="finance.transaction", verbose_name="Movimentação local")),
            ],
            options={"ordering": ["-last_seen_at", "-id"], "verbose_name": "Vínculo de transação Pluggy", "verbose_name_plural": "Vínculos de transações Pluggy"},
        ),
        migrations.AddIndex(model_name="pluggyaccount", index=models.Index(fields=["item", "remote_type", "is_active"], name="int_plug_acc_item_type_idx")),
        migrations.AddConstraint(model_name="pluggytransactionlink", constraint=models.UniqueConstraint(fields=("pluggy_account", "remote_transaction_id"), name="int_plug_tx_remote_unique")),
        migrations.AddConstraint(model_name="pluggytransactionlink", constraint=models.UniqueConstraint(condition=models.Q(("provider_id", ""), _negated=True), fields=("pluggy_account", "provider_id"), name="int_plug_tx_provider_unique")),
        migrations.AddIndex(model_name="pluggytransactionlink", index=models.Index(fields=["pluggy_account", "has_conflict"], name="int_plug_tx_conflict_idx")),
    ]
