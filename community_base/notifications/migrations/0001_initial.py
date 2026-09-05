# Provisional kept-label migration. Finalized by C3.7 before any package tag.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="Notification",
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
                ("title", models.CharField(max_length=300)),
                ("body", models.TextField(blank=True, default="")),
                ("url", models.CharField(blank=True, default="", max_length=500)),
                ("notification_type", models.CharField(default="announcement", max_length=64)),
                ("source_key", models.CharField(blank=True, default="", max_length=64)),
                ("source_id", models.CharField(blank=True, default="", max_length=128)),
                ("dedupe_key", models.CharField(blank=True, default="", max_length=128)),
                ("thread_content_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("read", models.BooleanField(default=False)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": (
                    models.Index(
                        fields=["user", "-created_at"],
                        name="notifications_user_created_idx",
                    ),
                    models.Index(fields=["user", "read"], name="notifications_user_read_idx"),
                ),
                "constraints": (
                    models.UniqueConstraint(
                        condition=models.Q(("dedupe_key__gt", "")),
                        fields=("user", "dedupe_key"),
                        name="notifications_user_dedupe_unique",
                    ),
                ),
            },
        ),
        migrations.CreateModel(
            name="NotificationPreference",
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
                ("source_key", models.CharField(max_length=64)),
                ("enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_preferences",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("source_key",),
                "constraints": (
                    models.UniqueConstraint(
                        fields=("user", "source_key"),
                        name="notifications_preference_unique",
                    ),
                ),
            },
        ),
    ]
