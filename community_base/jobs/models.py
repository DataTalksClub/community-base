from __future__ import annotations

import uuid

from django.db import models
from django.db.models import F, Q


class JobIntent(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUBMITTED = "submitted", "Submitted"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        DEAD = "dead", "Dead"

    TERMINAL_STATUSES = frozenset({Status.SUCCEEDED, Status.DEAD})
    CLAIMABLE_STATUSES = frozenset({Status.PENDING, Status.SUBMITTED, Status.FAILED})

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    handler = models.CharField(max_length=128)
    key_hash = models.CharField(max_length=64, unique=True)
    payload = models.JSONField(default=dict)
    payload_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    available_at = models.DateTimeField()
    lease_token = models.UUIDField(null=True, blank=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    correlation_id = models.CharField(max_length=128, blank=True, default="")
    external_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    last_error = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("available_at", "created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(max_attempts__gte=1),
                name="cb_jobs_max_attempts_positive",
            ),
            models.CheckConstraint(
                condition=Q(attempts__lte=F("max_attempts")),
                name="cb_jobs_attempts_bounded",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="running",
                        lease_token__isnull=False,
                        lease_expires_at__isnull=False,
                    )
                    | (
                        ~Q(status="running")
                        & Q(lease_token__isnull=True)
                        & Q(lease_expires_at__isnull=True)
                    )
                ),
                name="cb_jobs_lease_state_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "available_at"), name="cb_jobs_due"),
            models.Index(fields=("status", "lease_expires_at"), name="cb_jobs_lease"),
            models.Index(fields=("correlation_id",), name="cb_jobs_correlation"),
        ]

    def __str__(self) -> str:
        return f"{self.handler}:{self.id}"
