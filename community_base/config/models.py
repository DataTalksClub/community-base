from django.db import models


class Setting(models.Model):
    key = models.CharField(max_length=255, unique=True)
    value = models.JSONField()
    value_type = models.CharField(max_length=16)
    source = models.CharField(max_length=32)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("key",)

    def __str__(self) -> str:
        return self.key


class SettingChange(models.Model):
    setting_key = models.CharField(max_length=255, db_index=True)
    old_value = models.JSONField(null=True)
    old_value_redacted = models.BooleanField(default=False)
    new_value = models.JSONField(null=True)
    new_value_redacted = models.BooleanField(default=False)
    actor_ref = models.CharField(max_length=255)
    reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")

    def __str__(self) -> str:
        return f"{self.setting_key}:{self.created_at.isoformat()}"
