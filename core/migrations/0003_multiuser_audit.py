from django.conf import settings
from django.db import migrations
from django.db import models
import django.db.models.deletion


def create_existing_profiles(apps, schema_editor):
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(app_label, model_name)
    UserAccessProfile = apps.get_model("core", "UserAccessProfile")

    users = list(
        User.objects.all().order_by("id")
    )

    admin_user_ids = {
        user.pk
        for user in users
        if user.is_superuser or user.is_staff
    }

    if not admin_user_ids:
        first_active = next(
            (user for user in users if user.is_active),
            None,
        )
        if first_active is not None:
            admin_user_ids.add(first_active.pk)

    for user in users:
        UserAccessProfile.objects.get_or_create(
            user_id=user.pk,
            defaults={
                "role": (
                    "ADMIN"
                    if user.pk in admin_user_ids
                    else "OPERATOR"
                )
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0002_security_recovery_events"),
    ]

    operations = [
        migrations.AlterField(
            model_name="securityevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("LOGIN_BLOCKED", "Login bloqueado"),
                    ("LOGIN_FAILURE", "Falha de login"),
                    ("LOGIN_SUCCESS", "Login realizado"),
                    ("LOCAL_ACCOUNT_RECOVERY", "Recuperação local de acesso"),
                    ("PROFILE_UPDATED", "Perfil atualizado"),
                    ("INTEGRATION_CREATED", "Integração criada"),
                    ("INTEGRATION_UPDATED", "Integração atualizada"),
                    ("INTEGRATION_TESTED", "Integração testada"),
                    ("REPORT_REQUESTED", "Relatório solicitado"),
                    ("REPORT_IMPORTED", "Relatório importado"),
                ],
                db_index=True,
                max_length=32,
                verbose_name="Evento",
            ),
        ),
        migrations.CreateModel(
            name="UserAccessProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("ADMIN", "Administrador"), ("OPERATOR", "Operador de confiança")], db_index=True, default="OPERATOR", max_length=12, verbose_name="Perfil")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Atualizado em")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="access_profile", to=settings.AUTH_USER_MODEL, verbose_name="Usuário")),
            ],
            options={"verbose_name": "Perfil de acesso", "verbose_name_plural": "Perfis de acesso"},
        ),
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(db_index=True, max_length=160, verbose_name="Operação")),
                ("method", models.CharField(db_index=True, max_length=10, verbose_name="Método")),
                ("path", models.CharField(max_length=500, verbose_name="Caminho")),
                ("status_code", models.PositiveSmallIntegerField(default=200, verbose_name="HTTP")),
                ("success", models.BooleanField(db_index=True, default=True, verbose_name="Sucesso")),
                ("request_id", models.CharField(db_index=True, max_length=36, verbose_name="ID da requisição")),
                ("ip_hash", models.CharField(blank=True, db_index=True, max_length=64, verbose_name="Hash do IP")),
                ("detail", models.JSONField(blank=True, default=dict, verbose_name="Detalhes não sensíveis")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Realizado em")),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audit_events", to=settings.AUTH_USER_MODEL, verbose_name="Usuário")),
            ],
            options={
                "verbose_name": "Evento de auditoria",
                "verbose_name_plural": "Eventos de auditoria",
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(fields=["actor", "-created_at"], name="core_audit_actor_time_idx"),
                    models.Index(fields=["action", "-created_at"], name="core_audit_action_time_idx"),
                ],
            },
        ),
        migrations.RunPython(create_existing_profiles, migrations.RunPython.noop),
    ]
