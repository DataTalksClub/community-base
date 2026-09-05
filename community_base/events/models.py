import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from community_base.kernel.access import LEVEL_OPEN

EVENT_STATUSES = (
    ("draft", "Draft"),
    ("upcoming", "Upcoming"),
    ("completed", "Completed"),
    ("cancelled", "Cancelled"),
    ("archived", "Archived"),
)
EVENT_KINDS = (
    ("standard", "Standard"),
    ("workshop", "Workshop"),
    ("meetup", "Meetup"),
    ("q_and_a", "Q&A"),
)
EVENT_PLATFORMS = (("zoom", "Zoom"), ("custom", "Custom URL"), ("in_person", "In person"))
HOST_KINDS = (("host", "Host"), ("instructor", "Instructor"), ("speaker", "Speaker"))
SERIES_CADENCES = (("weekly", "Weekly"), ("none", "No fixed cadence"))
WEEKDAYS = tuple(
    enumerate(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"))
)
ALIAS_KINDS = (
    ("legacy_date_path", "Legacy date/title path"),
    ("legacy_uuid", "Legacy UUID path"),
    ("legacy_path", "Legacy path"),
    ("title_slug", "Previous title slug"),
    ("reviewed", "Reviewed alias"),
)


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Host(TimestampedModel):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    kind = models.CharField(max_length=20, choices=HOST_KINDS, default="host")
    external_ref = models.CharField(max_length=255, blank=True, default="")
    title = models.CharField(max_length=200, blank=True, default="")
    bio = models.TextField(blank=True, default="")
    bio_html = models.TextField(blank=True, default="")
    photo_url = models.URLField(max_length=500, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name", "pk")

    def __str__(self):
        return self.name


class EventSeries(TimestampedModel):
    name = models.CharField(max_length=300)
    slug = models.SlugField(max_length=300, unique=True)
    description = models.TextField(blank=True, default="")
    description_html = models.TextField(blank=True, default="")
    cadence = models.CharField(max_length=20, choices=SERIES_CADENCES, default="weekly")
    day_of_week = models.IntegerField(choices=WEEKDAYS, null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    timezone = models.CharField(max_length=100, default="Europe/Berlin")
    required_level = models.IntegerField(default=LEVEL_OPEN)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:300]
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.cadence == "weekly" and (self.day_of_week is None or self.start_time is None):
            raise ValidationError("Weekly series require a day and start time.")
        if self.cadence == "none" and (self.day_of_week is not None or self.start_time is not None):
            raise ValidationError("Cadence-free series cannot define a day or start time.")

    @property
    def event_count(self):
        return self.events.count()


class Event(TimestampedModel):
    content_id = models.UUIDField(unique=True, null=True, blank=True)
    public_id = models.PositiveIntegerField(unique=True, null=True, blank=True, editable=False)
    slug = models.SlugField(max_length=300, db_index=True)
    title = models.CharField(max_length=1000)
    description = models.TextField(blank=True, default="")
    description_html = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=20, choices=EVENT_KINDS, default="standard")
    platform = models.CharField(max_length=20, choices=EVENT_PLATFORMS, default="zoom")
    start_datetime = models.DateTimeField(db_index=True)
    end_datetime = models.DateTimeField(null=True, blank=True)
    timezone = models.CharField(max_length=100, default="Europe/Berlin")
    zoom_meeting_id = models.CharField(max_length=255, blank=True, default="")
    zoom_join_url = models.URLField(max_length=500, blank=True, default="")
    location = models.CharField(max_length=300, blank=True, default="")
    tags = models.JSONField(default=list, blank=True)
    required_level = models.IntegerField(default=LEVEL_OPEN)
    status = models.CharField(max_length=20, choices=EVENT_STATUSES, default="draft", db_index=True)
    max_participants = models.PositiveIntegerField(null=True, blank=True)
    recording_url = models.URLField(max_length=500, blank=True, default="")
    recording_s3_url = models.URLField(max_length=500, blank=True, default="")
    recording_embed_url = models.URLField(max_length=500, blank=True, default="")
    transcript_url = models.URLField(max_length=500, blank=True, default="")
    transcript_text = models.TextField(blank=True, default="")
    timestamps = models.JSONField(default=list, blank=True)
    materials = models.JSONField(default=list, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    ics_sequence = models.PositiveIntegerField(default=0)
    calendar_uid = models.CharField(max_length=400, unique=True, null=True, blank=True)
    source_repo = models.CharField(  # noqa: DJ001 -- provisional AISL schema compatibility.
        max_length=300, null=True, blank=True, default=None
    )
    source_path = models.CharField(  # noqa: DJ001 -- provisional AISL schema compatibility.
        max_length=500, null=True, blank=True, default=None
    )
    source_commit = models.CharField(  # noqa: DJ001 -- provisional AISL schema compatibility.
        max_length=64, null=True, blank=True, default=None
    )
    event_series = models.ForeignKey(
        EventSeries, null=True, blank=True, on_delete=models.SET_NULL, related_name="events"
    )
    series_position = models.PositiveIntegerField(null=True, blank=True)
    title_is_auto = models.BooleanField(default=True)
    hosts = models.ManyToManyField(Host, through="EventHost", related_name="events", blank=True)

    class Meta:
        ordering = ("-start_datetime", "pk")
        constraints = (
            models.CheckConstraint(
                condition=Q(end_datetime__isnull=True)
                | Q(end_datetime__gte=models.F("start_datetime")),
                name="events_event_end_after_start",
            ),
            models.CheckConstraint(
                condition=Q(public_id__isnull=True) | Q(public_id__gt=0),
                name="events_event_public_id_positive",
            ),
            models.UniqueConstraint(
                fields=("event_series", "series_position"),
                condition=Q(event_series__isnull=False, series_position__isnull=False),
                name="events_event_series_position_unique",
            ),
        )

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:70]
        if not self.calendar_uid:
            self.calendar_uid = f"event-{uuid.uuid4()}@community-base"
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).values_list("public_id", flat=True)
            if original.exists() and original.get() != self.public_id:
                raise ValidationError("Event public_id is immutable.")
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.end_datetime is not None and self.end_datetime < self.start_datetime:
            raise ValidationError({"end_datetime": "Event end must not precede its start."})
        if bool(self.event_series_id) != bool(self.series_position):
            raise ValidationError("Series and series position must be set together.")

    @property
    def effective_end_datetime(self):
        return self.end_datetime or self.start_datetime + timedelta(hours=1)

    @property
    def is_upcoming(self):
        return self.status == "upcoming" and timezone.now() < self.effective_end_datetime

    @property
    def is_past(self):
        if self.status in {"completed", "cancelled", "archived"}:
            return True
        return self.status == "upcoming" and timezone.now() >= self.effective_end_datetime

    @property
    def ordered_hosts(self):
        return [
            link.host for link in self.event_host_links.select_related("host").order_by("position")
        ]


class EventHost(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="event_host_links")
    host = models.ForeignKey(Host, on_delete=models.PROTECT, related_name="event_host_links")
    position = models.PositiveIntegerField(default=0)
    role = models.CharField(max_length=20, choices=HOST_KINDS, default="host")

    class Meta:
        ordering = ("position", "pk")
        constraints = (
            models.UniqueConstraint(
                fields=("event", "host", "role"), name="events_event_host_role_unique"
            ),
            models.UniqueConstraint(
                fields=("event", "position"), name="events_event_host_position_unique"
            ),
        )

    def __str__(self):
        return f"{self.event} - {self.host} ({self.role})"


class EventAlias(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="aliases")
    source_path = models.CharField(max_length=1024, unique=True)
    kind = models.CharField(max_length=24, choices=ALIAS_KINDS)
    reason = models.CharField(max_length=255)
    source_repository = models.CharField(max_length=255, blank=True, default="")
    source_revision = models.CharField(max_length=64, blank=True, default="")
    source_key = models.CharField(max_length=512, blank=True, default="")
    activated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("source_path",)
        constraints = (
            models.CheckConstraint(
                condition=Q(source_path__startswith="/events/")
                & ~Q(source_path__contains="?")
                & ~Q(source_path__contains="#"),
                name="events_alias_path_shape",
            ),
        )

    def __str__(self):
        return self.source_path

    def clean(self):
        super().clean()
        if (
            not self.source_path.startswith("/events/")
            or "?" in self.source_path
            or "#" in self.source_path
        ):
            raise ValidationError(
                {"source_path": "Event aliases must be clean paths below /events/."}
            )


class EventPublicIdSequence(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    next_public_id = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = (
            models.CheckConstraint(condition=Q(id=1), name="events_public_id_sequence_singleton"),
            models.CheckConstraint(
                condition=Q(next_public_id__gt=0), name="events_public_id_sequence_positive"
            ),
        )

    def __str__(self):
        return f"Next public event ID: {self.next_public_id}"
