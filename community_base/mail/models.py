from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class EmailDelivery(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        QUEUED = "queued", "Queued"
        LEASED = "leased", "Leased"
        PROVIDER_ACCEPTED = "provider_accepted", "Provider accepted"
        DELIVERED = "delivered", "Delivered"
        RETRYABLE = "retryable", "Retryable"
        AMBIGUOUS = "ambiguous", "Ambiguous"
        SUPPRESSED = "suppressed", "Suppressed"
        DEAD = "dead", "Dead"
        HARD_BOUNCED = "hard_bounced", "Hard bounced"
        COMPLAINED = "complained", "Complained"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.CharField(max_length=200, unique=True)
    purpose = models.CharField(max_length=128)
    category = models.CharField(max_length=64, blank=True, default="")
    template_key = models.CharField(max_length=128)
    template_version = models.PositiveIntegerField(default=1)
    recipient_email = models.EmailField(max_length=254)
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="community_base_email_deliveries",
    )
    context_hash = models.CharField(max_length=64)
    sender_id = models.CharField(max_length=128, blank=True, default="")
    state = models.CharField(max_length=32, choices=State.choices, default=State.PENDING)
    external_message_id = models.CharField(max_length=128, blank=True, default="")
    reason_code = models.CharField(max_length=128, blank=True, default="")
    job = models.ForeignKey(
        "cb_jobs.JobIntent",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="email_deliveries",
    )
    related_object_type = models.CharField(max_length=128, blank=True, default="")
    related_object_id = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "id")
        indexes = [
            models.Index(fields=("state", "created_at"), name="cb_mail_state_created"),
            models.Index(fields=("purpose", "created_at"), name="cb_mail_purpose_created"),
        ]

    def __str__(self) -> str:
        return f"{self.purpose}:{self.id}"


class PendingUnsubscribe(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPLIED = "applied", "Applied"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unsubscribe_token = models.CharField(max_length=128, unique=True)
    token_fingerprint = models.CharField(max_length=32, db_index=True)
    scope = models.CharField(max_length=16)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    last_outcome = models.CharField(max_length=32, blank=True, default="")
    accepted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=("status", "accepted_at"), name="cb_mail_unsub_status")]

    def __str__(self) -> str:
        return self.token_fingerprint


class CallbackEvent(models.Model):
    event_id = models.CharField(max_length=128, unique=True)
    delivery = models.ForeignKey(
        EmailDelivery,
        on_delete=models.CASCADE,
        related_name="callback_events",
    )
    state = models.CharField(max_length=32, choices=EmailDelivery.State.choices)
    reason_code = models.CharField(max_length=128, blank=True, default="")
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("received_at", "id")

    def __str__(self) -> str:
        return self.event_id
