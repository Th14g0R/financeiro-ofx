from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserAccessProfile


@receiver(post_save, sender=get_user_model())
def ensure_user_access_profile(sender, instance, created, **kwargs):
    if not created:
        return

    role = (
        UserAccessProfile.Role.ADMIN
        if (instance.is_superuser or instance.is_staff)
        else UserAccessProfile.Role.OPERATOR
    )
    UserAccessProfile.objects.get_or_create(
        user=instance,
        defaults={"role": role},
    )
