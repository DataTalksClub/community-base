from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models

STATUS_BOOKED = "booked"
STATUS_CANCELED = "canceled"
STATUS_CHOICES = ((STATUS_BOOKED, "Booked"), (STATUS_CANCELED, "Canceled"))
_HTTP_URL_VALIDATOR = URLValidator(schemes=("http", "https"))


def is_usable_http_url(value):
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    try:
        _HTTP_URL_VALIDATOR(value)
    except ValidationError:
        return False
    return True


class CommunityAuditLog(models.Model):
    class Action(models.TextChoices):
        INVITE = "invite", "Invite"
        REMOVE = "remove", "Remove"
        REACTIVATE = "reactivate", "Reactivate"
        LINK = "link", "Link"
        CHECK = "check", "Check"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="community_audit_logs",
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-timestamp",)
        verbose_name = "Community Audit Log"
        verbose_name_plural = "Community Audit Logs"

    def __str__(self):
        return f"{self.action} - {self.user_id} at {self.timestamp}"


class SlackAccessGrant(models.Model):
    class Source(models.TextChoices):
        ELIGIBILITY = "eligibility", "Eligibility"
        ONBOARDING = "onboarding", "Onboarding"
        OPERATOR = "operator", "Operator"
        IMPORT = "import", "Import"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="slack_access_grant",
    )
    invite_version = models.CharField(max_length=64)
    source = models.CharField(max_length=20, choices=Source.choices)
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-granted_at",)

    def __str__(self):
        return f"SlackAccessGrant({self.user_id}, {self.invite_version})"

    @property
    def active(self):
        return self.revoked_at is None


class CallHost(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    role_label = models.CharField(max_length=160, blank=True)
    photo_url = models.CharField(max_length=500, blank=True)
    booking_url = models.URLField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    capacity = models.PositiveIntegerField(default=0)
    current_load = models.PositiveIntegerField(default=0)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("order", "name")
        verbose_name = "Call profile"
        verbose_name_plural = "Call profiles"

    def __str__(self):
        return self.name

    @property
    def is_available(self):
        return self.is_active and is_usable_http_url(self.booking_url)

    @property
    def usable_booking_url(self):
        return self.booking_url if is_usable_http_url(self.booking_url) else ""

    @property
    def display_photo_url(self):
        return self.photo_url


class BookedCall(models.Model):
    host = models.ForeignKey(CallHost, on_delete=models.PROTECT, related_name="booked_calls")
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="booked_calls",
    )
    invitee_email = models.EmailField()
    invitee_name = models.CharField(max_length=200, blank=True, default="")
    scheduled_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_BOOKED)
    calendly_event_uri = models.CharField(max_length=500, unique=True)
    calendly_invitee_uri = models.CharField(max_length=500, blank=True, default="")
    reschedule_url = models.URLField(max_length=500, blank=True, default="")
    cancel_url = models.URLField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    last_event_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-scheduled_at", "-created_at")
        indexes = (
            models.Index(fields=("member", "status"), name="community_member_status_idx"),
            models.Index(fields=("host", "status"), name="community_host_status_idx"),
        )

    def __str__(self):
        return f"BookedCall({self.member_id or self.invitee_email}, {self.status})"

    @property
    def is_active(self):
        return self.status == STATUS_BOOKED


class UnmatchedBookedCall(models.Model):
    source_booked_call_id = models.BigIntegerField(null=True, blank=True, unique=True)
    source_created_at = models.DateTimeField(null=True, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="unmatched_booked_calls",
    )
    invitee_email = models.EmailField(blank=True, default="")
    invitee_name = models.CharField(max_length=200, blank=True, default="")
    scheduled_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_BOOKED)
    calendly_event_uri = models.CharField(max_length=500, unique=True)
    calendly_invitee_uri = models.CharField(max_length=500, blank=True, default="", db_index=True)
    scheduling_url = models.URLField(max_length=500, blank=True, default="")
    reschedule_url = models.URLField(max_length=500, blank=True, default="")
    cancel_url = models.URLField(max_length=500, blank=True, default="")
    canceled_at = models.DateTimeField(null=True, blank=True)
    last_event_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-scheduled_at", "-created_at")

    def __str__(self):
        return f"UnmatchedBookedCall({self.pk}, {self.status})"
