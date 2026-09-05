from django.conf import settings
from django.db import models
from django.db.models import Q


class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    title = models.CharField(max_length=300)
    body = models.TextField(blank=True, default="")
    url = models.CharField(max_length=500, blank=True, default="")
    notification_type = models.CharField(max_length=64, default="announcement")
    source_key = models.CharField(max_length=64, blank=True, default="")
    source_id = models.CharField(max_length=128, blank=True, default="")
    dedupe_key = models.CharField(max_length=128, blank=True, default="")
    thread_content_id = models.UUIDField(null=True, blank=True, db_index=True)
    read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("user", "-created_at"), name="notifications_user_created_idx"),
            models.Index(fields=("user", "read"), name="notifications_user_read_idx"),
        )
        constraints = (
            models.UniqueConstraint(
                fields=("user", "dedupe_key"),
                condition=Q(dedupe_key__gt=""),
                name="notifications_user_dedupe_unique",
            ),
        )

    def __str__(self):
        return f"{self.title} ({self.notification_type})"


class NotificationPreference(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    source_key = models.CharField(max_length=64)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("source_key",)
        constraints = (
            models.UniqueConstraint(
                fields=("user", "source_key"), name="notifications_preference_unique"
            ),
        )

    def __str__(self):
        return f"{self.user_id}:{self.source_key}={self.enabled}"
