import uuid

from django.core.exceptions import ValidationError
from django.db import models


class SyncStatus(models.TextChoices):
    SUCCESS = "success", "Success"
    PARTIAL = "partial", "Partial"
    FAILED = "failed", "Failed"
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SKIPPED = "skipped", "Skipped"


class ContentSource(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=100, unique=True)
    repo_name = models.CharField(max_length=300, unique=True)
    webhook_secret = models.CharField(max_length=200, blank=True, default="")
    is_private = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(
        max_length=20, blank=True, default="", choices=SyncStatus.choices
    )
    last_sync_log = models.TextField(blank=True, default="")
    sync_locked_at = models.DateTimeField(null=True, blank=True)
    sync_requested = models.BooleanField(default=False)
    last_webhook_at = models.DateTimeField(null=True, blank=True)
    last_synced_commit = models.CharField(max_length=40, blank=True, default="", db_index=True)
    max_files = models.PositiveIntegerField(default=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("repo_name",)

    def __str__(self):
        return self.repo_name

    def clean(self):
        super().clean()
        self.webhook_secret = (self.webhook_secret or "").strip()
        if not self.webhook_secret:
            raise ValidationError({"webhook_secret": "A nonblank webhook secret is required."})

    @property
    def short_name(self):
        return self.repo_name.rsplit("/", 1)[-1]

    @property
    def short_synced_commit(self):
        return self.last_synced_commit[:7]


class SyncLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(ContentSource, on_delete=models.CASCADE, related_name="sync_logs")
    batch_id = models.UUIDField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=SyncStatus.choices, default=SyncStatus.RUNNING)
    items_created = models.IntegerField(default=0)
    items_updated = models.IntegerField(default=0)
    items_unchanged = models.IntegerField(default=0)
    items_deleted = models.IntegerField(default=0)
    items_detail = models.JSONField(default=list, blank=True)
    commit_sha = models.CharField(max_length=40, blank=True, default="")
    errors = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ("-started_at",)
        indexes = (
            models.Index(
                fields=("source", "status", "-started_at"),
                name="cb_sync_src_status_idx",
            ),
            models.Index(fields=("batch_id", "-started_at"), name="cb_sync_batch_started_idx"),
        )

    def __str__(self):
        return f"{self.source.repo_name} - {self.status} at {self.started_at}"

    @property
    def total_items(self):
        return self.items_created + self.items_updated + self.items_deleted

    @property
    def duration_seconds(self):
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class WebhookLog(models.Model):
    service = models.CharField(max_length=100)
    event_type = models.CharField(max_length=200, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed = models.BooleanField(default=False)
    deduplication_key = models.CharField(max_length=128, blank=True, null=True, unique=True)
    attempts = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-received_at",)
        indexes = (
            models.Index(
                fields=("service", "processed", "received_at"),
                name="cb_sync_service_state_idx",
            ),
        )

    def __str__(self):
        return f"{self.service} - {self.event_type} at {self.received_at}"
