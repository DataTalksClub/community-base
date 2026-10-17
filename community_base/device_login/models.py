from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class DeviceGrantStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    DENIED = "denied", "Denied"


class DeviceGrant(models.Model):
    """One short-lived device authorization grant.

    Only SHA-256 digests of the codes are stored. The plaintext user code
    is shown once to the CLI operator; the device code is returned once to
    the polling CLI and never printed.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_code_hash = models.CharField(max_length=64, unique=True)
    user_code_hash = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=16, choices=DeviceGrantStatus.choices, default=DeviceGrantStatus.PENDING
    )
    label = models.CharField(max_length=80, default="CLI")
    request_ip = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="device_grants_approved",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_poll_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"device-grant:{self.pk}:{self.status}"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at
