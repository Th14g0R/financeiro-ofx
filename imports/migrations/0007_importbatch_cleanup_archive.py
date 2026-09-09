from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0006_importfile_provider_astropay"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="importeffect",
            name="cleanup_data",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Snapshot e metadados preservados quando um efeito é removido pela limpeza assistida OFX."
                ),
                verbose_name="Dados da limpeza assistida",
            ),
        ),
        migrations.AddField(
            model_name="importbatch",
            name="cleanup_archived_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text=(
                    "Quando preenchido, o lote foi mantido apenas como evidência da "
                    "importação original após a limpeza assistida dos efeitos financeiros."
                ),
                null=True,
                verbose_name="Arquivado após limpeza em",
            ),
        ),
        migrations.AddField(
            model_name="importbatch",
            name="cleanup_archived_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="cleanup_archived_import_batches",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Arquivado após limpeza por",
            ),
        ),
        migrations.AddField(
            model_name="importbatch",
            name="cleanup_note",
            field=models.TextField(blank=True, verbose_name="Observação da limpeza"),
        ),
    ]
