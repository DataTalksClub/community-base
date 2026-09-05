from __future__ import annotations

import secrets
import uuid

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.crypto import salted_hmac


def generate_key_identifier() -> str:
    return f"key_{uuid.uuid4().hex}"


class APIKey(models.Model):
    class Kind(models.TextChoices):
        STAFF = "staff", "Staff"
        MEMBER = "member", "Member"

    LOOKUP_PREFIX_LENGTH = 24
    PREFIXES = {
        Kind.STAFF: "cb_staff_",
        Kind.MEMBER: "cb_member_",
    }

    id = models.CharField(primary_key=True, max_length=40, default=generate_key_identifier)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="community_base_api_keys",
    )
    name = models.CharField(max_length=120)
    key_hash = models.CharField(max_length=128)
    lookup_prefix = models.CharField(max_length=32, db_index=True)
    scopes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_ip_hash = models.CharField(max_length=64, blank=True, default="")
    kind = models.CharField(max_length=16, choices=Kind.choices)

    class Meta:
        ordering = ("-created_at", "id")
        indexes = [
            models.Index(fields=("lookup_prefix", "revoked_at"), name="cb_api_key_lookup"),
            models.Index(fields=("user", "revoked_at"), name="cb_api_key_owner"),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.id}:{self.name}"

    def save(self, *args, **kwargs) -> None:
        self.name = self.name.strip()
        self.scopes = sorted(set(self.scopes))
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        self.name = self.name.strip()
        if not self.name:
            raise ValidationError({"name": "Name is required."})
        if self.kind == self.Kind.STAFF and not getattr(self.user, "is_staff", False):
            raise ValidationError({"user": "Staff API keys require a staff user."})
        if not isinstance(self.scopes, list) or not self.scopes:
            raise ValidationError({"scopes": "At least one scope is required."})
        if any(not isinstance(scope, str) or not scope.strip() for scope in self.scopes):
            raise ValidationError({"scopes": "Scopes must be non-empty strings."})

    @classmethod
    def create_for_user(
        cls,
        *,
        user,
        name: str,
        scopes: list[str] | tuple[str, ...],
        kind: str,
    ) -> tuple[APIKey, str]:
        try:
            prefix = cls.PREFIXES[cls.Kind(kind)]
        except (KeyError, ValueError) as error:
            raise ValidationError({"kind": "Unsupported API key kind."}) from error
        plaintext = f"{prefix}{secrets.token_urlsafe(32)}"
        api_key = cls(
            user=user,
            name=name,
            key_hash=make_password(plaintext),
            lookup_prefix=plaintext[: cls.LOOKUP_PREFIX_LENGTH],
            scopes=list(scopes),
            kind=kind,
        )
        api_key.save()
        return api_key, plaintext

    @classmethod
    def authenticate(cls, plaintext: str | None) -> APIKey | None:
        if not plaintext:
            return None
        lookup_prefix = plaintext[: cls.LOOKUP_PREFIX_LENGTH]
        candidates = cls.objects.select_related("user").filter(
            lookup_prefix=lookup_prefix,
            revoked_at__isnull=True,
            user__is_active=True,
        )
        for candidate in candidates:
            if check_password(plaintext, candidate.key_hash):
                return candidate
        return None

    def allows(self, required_scopes: tuple[str, ...]) -> bool:
        available = set(self.scopes)
        return "*" in available or set(required_scopes).issubset(available)

    def revoke(self) -> None:
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=("revoked_at",))

    def mark_used(self, request) -> None:
        remote_addr = request.META.get("REMOTE_ADDR", "")
        ip_hash = (
            salted_hmac("community-base-api-key-ip", remote_addr).hexdigest() if remote_addr else ""
        )
        type(self).objects.filter(pk=self.pk).update(
            last_used_at=timezone.now(),
            last_used_ip_hash=ip_hash,
        )

    @property
    def masked_prefix(self) -> str:
        return f"{self.lookup_prefix}..."

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None
