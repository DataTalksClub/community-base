from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models

IMPORT_SOURCE_MANUAL = "manual"
IMPORT_SOURCE_SLACK = "slack"
IMPORT_SOURCE_COURSE_DB = "course_db"
IMPORT_SOURCE_STRIPE = "stripe"
IMPORT_SOURCE_CHOICES = (
    (IMPORT_SOURCE_MANUAL, "Manual / self signup"),
    (IMPORT_SOURCE_SLACK, "Slack workspace"),
    (IMPORT_SOURCE_COURSE_DB, "Course database"),
    (IMPORT_SOURCE_STRIPE, "Stripe customers"),
)
IMPORT_BATCH_SOURCE_CHOICES = IMPORT_SOURCE_CHOICES[1:]

SIGNUP_SOURCE_UNKNOWN = "unknown"
SIGNUP_SOURCE_NEWSLETTER = "newsletter"
SIGNUP_SOURCE_DOWNLOAD = "download"
SIGNUP_SOURCE_SIGNUP = "signup"
SIGNUP_SOURCE_OAUTH = "oauth"
SIGNUP_SOURCE_IMPORTED = "imported"
SIGNUP_SOURCE_STAFF_CREATE = "staff_create"
SIGNUP_SOURCE_CHOICES = (
    (SIGNUP_SOURCE_UNKNOWN, "Unknown (pre-existing row)"),
    (SIGNUP_SOURCE_NEWSLETTER, "Newsletter subscribe"),
    (SIGNUP_SOURCE_DOWNLOAD, "Download request"),
    (SIGNUP_SOURCE_SIGNUP, "Email + password signup"),
    (SIGNUP_SOURCE_OAUTH, "OAuth signup"),
    (SIGNUP_SOURCE_IMPORTED, "Bulk import"),
    (SIGNUP_SOURCE_STAFF_CREATE, "Staff-created"),
)


class BounceState(models.TextChoices):
    NONE = "none", "No bounce"
    SOFT = "soft", "Soft bounce"
    PERMANENT = "permanent", "Permanent bounce"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField("email address", unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()
    BounceState = BounceState

    email_verified = models.BooleanField(default=False)
    verification_expires_at = models.DateTimeField(null=True, blank=True)
    verification_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    verification_resend_claimed_at = models.DateTimeField(null=True, blank=True)
    verification_resend_claim_token = models.UUIDField(null=True, blank=True, editable=False)
    unsubscribed = models.BooleanField(default=False)
    email_preferences = models.JSONField(default=dict, blank=True)
    soft_bounce_count = models.PositiveSmallIntegerField(default=0)
    bounce_state = models.CharField(
        max_length=16,
        choices=BounceState.choices,
        default=BounceState.NONE,
        db_index=True,
    )
    bounce_recorded_at = models.DateTimeField(null=True, blank=True)
    last_bounce_diagnostic = models.TextField(blank=True, default="")
    slack_user_id = models.CharField(max_length=255, blank=True, default="")
    slack_member = models.BooleanField(default=False, db_index=True)
    slack_checked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    theme_preference = models.CharField(max_length=10, blank=True, default="")
    preferred_timezone = models.CharField(max_length=100, blank=True, default="")
    dashboard_dismissals = models.JSONField(default=list, blank=True)
    tags = models.JSONField(default=list, blank=True)
    signup_source = models.CharField(
        max_length=32,
        choices=SIGNUP_SOURCE_CHOICES,
        default=SIGNUP_SOURCE_UNKNOWN,
        db_index=True,
    )
    account_activated = models.BooleanField(default=False, db_index=True)
    import_source = models.CharField(
        max_length=32,
        choices=IMPORT_SOURCE_CHOICES,
        default=IMPORT_SOURCE_MANUAL,
        db_index=True,
    )
    imported_at = models.DateTimeField(null=True, blank=True, db_index=True)
    import_metadata = models.JSONField(default=dict, blank=True)

    class Meta(AbstractUser.Meta):
        db_table = "accounts_user"
        ordering = ("-date_joined",)

    def __str__(self):
        return self.email


class EmailAlias(models.Model):
    class Source(models.TextChoices):
        MERGE = "merge", "Added by an account merge"
        MANUAL = "manual", "Operator-added"
        STRIPE_RELAY = "stripe_relay", "Billing relay address"
        ACCOUNT_CHANGE = "account_change", "Former login email after account change"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_aliases",
    )
    email = models.EmailField(unique=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Email Alias"
        verbose_name_plural = "Email Aliases"

    def __str__(self):
        return f"EmailAlias({self.email} -> {self.user_id})"


class EmailChangeRequest(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_change_requests",
    )
    old_email = models.EmailField()
    new_email = models.EmailField()
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField(db_index=True)
    confirmed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    invalidated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_sent_at = models.DateTimeField()

    class Meta:
        ordering = ("-created_at",)
        constraints = (
            models.UniqueConstraint(
                fields=("user",),
                condition=models.Q(confirmed_at__isnull=True, invalidated_at__isnull=True),
                name="unique_active_email_change_request_per_user",
            ),
        )

    def __str__(self):
        return f"EmailChangeRequest({self.old_email} -> {self.new_email})"

    @property
    def is_pending(self):
        return self.confirmed_at is None and self.invalidated_at is None


class PrivacyRequestLog(models.Model):
    class RequestType(models.TextChoices):
        EXPORT = "export", "Export"
        DELETE = "delete", "Delete"
        DELETION_REQUEST = "deletion_request", "Deletion request"

    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"
        BLOCKED = "blocked", "Blocked"
        PENDING_DELIVERY = "pending_delivery", "Pending delivery"
        REQUESTED = "requested", "Requested"
        DELIVERY_FAILED = "delivery_failed", "Delivery failed"

    request_type = models.CharField(max_length=16, choices=RequestType.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    old_user_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    normalized_email_hash = models.CharField(max_length=64, db_index=True)
    email_domain = models.CharField(max_length=255, blank=True, default="")
    requested_at = models.DateTimeField(auto_now_add=True)
    row_count_summary = models.JSONField(default=dict, blank=True)
    blocker_reason = models.CharField(max_length=64, blank=True, default="")
    request_ip_hash = models.CharField(max_length=64, blank=True, default="")
    user_agent_hash = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ("-requested_at",)
        indexes = (
            models.Index(
                fields=("request_type", "status", "-requested_at"),
                name="accounts_privacy_state_idx",
            ),
            models.Index(fields=("blocker_reason",), name="accounts_privacy_block_idx"),
        )
        constraints = (
            models.UniqueConstraint(
                fields=("old_user_id",),
                condition=(
                    models.Q(request_type="deletion_request")
                    & models.Q(status__in=("pending_delivery", "requested"))
                    & models.Q(old_user_id__isnull=False)
                ),
                name="unique_active_deletion_request",
            ),
        )

    def __str__(self):
        return f"{self.request_type}:{self.status}:{self.old_user_id or 'unknown'}"


class ImportBatch(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    source = models.CharField(max_length=32, choices=IMPORT_BATCH_SOURCE_CHOICES, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="import_batches",
        null=True,
        blank=True,
    )
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True, db_index=True)
    dry_run = models.BooleanField(default=False, db_index=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.RUNNING, db_index=True
    )
    users_created = models.PositiveIntegerField(default=0)
    users_updated = models.PositiveIntegerField(default=0)
    users_skipped = models.PositiveIntegerField(default=0)
    emails_queued = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    summary = models.TextField(blank=True, default="")
    params = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-started_at",)

    def __str__(self):
        return f"ImportBatch({self.source}, {self.status}, {self.started_at:%Y-%m-%d %H:%M})"


class WorkStatus(models.TextChoices):
    EMPLOYED = "employed", "Employed"
    SELF_EMPLOYED = "self_employed", "Self-employed"
    STUDENT = "student", "Student"
    BETWEEN_ROLES = "between_roles", "Between roles"
    NOT_WORKING = "not_working", "Not working"
    PREFER_NOT_TO_SAY = "prefer_not_to_say", "Prefer not to say"


class ProfessionalRole(models.TextChoices):
    DATA_ENGINEER = "data_engineer", "Data engineer"
    DATA_SCIENTIST = "data_scientist", "Data scientist"
    DATA_ANALYST = "data_analyst", "Data analyst"
    ML_ENGINEER = "ml_engineer", "Machine-learning engineer"
    SOFTWARE_ENGINEER_BACKEND = "software_engineer_backend", "Backend software engineer"
    SOFTWARE_ENGINEER_OTHER = "software_engineer_other", "Other software engineer"
    STUDENT_STEM = "student_stem", "STEM student"
    STUDENT_NON_STEM = "student_non_stem", "Non-STEM student"
    OTHER = "other", "Other"
    PREFER_NOT_TO_SAY = "prefer_not_to_say", "Prefer not to say"


class Seniority(models.TextChoices):
    LEARNING = "learning", "Learning"
    ENTRY = "entry", "Entry"
    MID = "mid", "Mid-level"
    SENIOR = "senior", "Senior"
    LEAD_OR_MANAGER = "lead_or_manager", "Lead or manager"
    EXECUTIVE_OR_FOUNDER = "executive_or_founder", "Executive or founder"
    NOT_APPLICABLE = "not_applicable", "Not applicable"
    PREFER_NOT_TO_SAY = "prefer_not_to_say", "Prefer not to say"


ISO_ALPHA2_CODES = frozenset(
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO "
    "BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK "
    "DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR "
    "GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM "
    "KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP "
    "MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL "
    "PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST "
    "SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG "
    "VI VN VU WF WS YE YT ZA ZM ZW".split()
)
http_url_validator = URLValidator(schemes=("http", "https"))


def validate_country_code(value):
    if value and value.upper() not in ISO_ALPHA2_CODES:
        raise ValidationError("Country must be an ISO 3166-1 alpha-2 code.")


def validate_profile_url(value):
    if not value:
        return
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValidationError("Profile URL contains control characters.")
    http_url_validator(value)
    parsed = urlsplit(value)
    if parsed.username is not None or parsed.password is not None or not parsed.hostname:
        raise ValidationError("Profile URL must not contain user information.")


class MemberProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="member_profile",
    )
    country = models.CharField(max_length=2, blank=True, validators=(validate_country_code,))
    work_status = models.CharField(max_length=24, blank=True, choices=WorkStatus.choices)
    organisation = models.CharField(max_length=160, blank=True, default="")
    professional_role = models.CharField(
        max_length=32,
        blank=True,
        choices=ProfessionalRole.choices,
    )
    seniority = models.CharField(max_length=24, blank=True, choices=Seniority.choices)
    about = models.TextField(max_length=1000, blank=True, default="")
    ambitions = models.TextField(max_length=1000, blank=True, default="")
    why_joined = models.TextField(max_length=1000, blank=True, default="")
    github_url = models.URLField(max_length=500, blank=True, validators=(validate_profile_url,))
    linkedin_url = models.URLField(max_length=500, blank=True, validators=(validate_profile_url,))
    website_url = models.URLField(max_length=500, blank=True, validators=(validate_profile_url,))
    completion_version = models.PositiveSmallIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveBigIntegerField(default=0)
    confirmed_revision = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("user_id",)

    def __str__(self):
        return f"MemberProfile({self.user_id}, revision={self.revision})"

    def clean(self):
        super().clean()
        self.country = self.country.strip().upper()
        for field in ("organisation", "about", "ambitions", "why_joined"):
            setattr(self, field, getattr(self, field).strip())
