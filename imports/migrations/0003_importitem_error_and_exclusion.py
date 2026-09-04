from django.conf import settings
from django.db import migrations
from django.db import models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("imports", "0002_importeffect_batch_reprocessed"),
    ]

    operations = [
        migrations.AddField(
            model_name="importitem",
            name="commit_error_code",
            field=models.CharField(
                blank=True,
                max_length=40,
                verbose_name="Código do erro",
            ),
        ),
        migrations.AddField(
            model_name="importitem",
            name="commit_error_message",
            field=models.TextField(
                blank=True,
                verbose_name="Erro de gravação",
            ),
        ),
        migrations.AddField(
            model_name="importitem",
            name="commit_error_details",
            field=models.JSONField(
                blank=True,
                default=dict,
                verbose_name="Detalhes do erro",
            ),
        ),
        migrations.AddField(
            model_name="importitem",
            name="is_excluded",
            field=models.BooleanField(
                db_index=True,
                default=False,
                verbose_name="Removido da importação",
            ),
        ),
        migrations.AddField(
            model_name="importitem",
            name="excluded_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Removido em",
            ),
        ),
        migrations.AddField(
            model_name="importitem",
            name="excluded_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="excluded_import_items",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Removido por",
            ),
        ),
        migrations.AlterField(
            model_name="importitem",
            name="classification",
            field=models.CharField(
                choices=[
                    ("NEW", "Novo"),
                    ("DUPLICATE", "Duplicado"),
                    ("DIVERGENT", "Divergente"),
                    (
                        "UNRESOLVED_ACCOUNT",
                        "Conta não relacionada",
                    ),
                    ("INVALID", "Inválido"),
                    ("COMMIT_ERROR", "Erro de gravação"),
                ],
                db_index=True,
                max_length=24,
                verbose_name="Classificação",
            ),
        ),
    ]
