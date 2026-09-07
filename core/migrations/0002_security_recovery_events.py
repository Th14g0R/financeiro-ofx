from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        (
            "core",
            "0001_security_models",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="securityevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    (
                        "LOGIN_BLOCKED",
                        "Login bloqueado",
                    ),
                    (
                        "LOGIN_SUCCESS",
                        "Login realizado",
                    ),
                    (
                        "LOCAL_ACCOUNT_RECOVERY",
                        "Recuperação local de acesso",
                    ),
                    (
                        "PROFILE_UPDATED",
                        "Perfil atualizado",
                    ),
                    (
                        "INTEGRATION_CREATED",
                        "Integração criada",
                    ),
                    (
                        "INTEGRATION_UPDATED",
                        "Integração atualizada",
                    ),
                    (
                        "INTEGRATION_TESTED",
                        "Integração testada",
                    ),
                    (
                        "REPORT_REQUESTED",
                        "Relatório solicitado",
                    ),
                    (
                        "REPORT_IMPORTED",
                        "Relatório importado",
                    ),
                ],
                db_index=True,
                max_length=32,
                verbose_name="Evento",
            ),
        ),
    ]
