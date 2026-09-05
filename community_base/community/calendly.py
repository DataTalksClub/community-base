import hashlib
import hmac
import time
from urllib.parse import urlsplit, urlunsplit

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from community_base.accounts.services.email_resolution import resolve_user_by_email
from community_base.community.models import (
    STATUS_BOOKED,
    STATUS_CANCELED,
    BookedCall,
    CallHost,
    UnmatchedBookedCall,
)
from community_base.kernel import conf

EVENT_INVITEE_CREATED = "invitee.created"
EVENT_INVITEE_CANCELED = "invitee.canceled"


def _positive_int(name, default, *, minimum=1):
    try:
        return max(minimum, int(conf.get(name)))
    except (TypeError, ValueError):
        return default


def verify_signature(body, header, *, now=None):
    """Validate one Calendly HMAC signature without retaining its secret."""
    key = str(conf.get("CALENDLY_WEBHOOK_SIGNING_KEY") or "")
    if not key:
        return False
    timestamp = ""
    signatures = []
    for part in str(header or "").split(","):
        name, separator, value = part.strip().partition("=")
        if not separator:
            continue
        if name == "t":
            timestamp = value
        elif name == "v1":
            signatures.append(value)
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError):
        return False
    tolerance = _positive_int("CALENDLY_WEBHOOK_TOLERANCE_SECONDS", 300, minimum=30)
    if abs(int(time.time() if now is None else now) - timestamp_value) > tolerance:
        return False
    try:
        signed = timestamp.encode("ascii") + b"." + body
    except (AttributeError, UnicodeEncodeError):
        return False
    expected = hmac.new(key.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, signature) for signature in signatures)


def webhook_max_bytes():
    return _positive_int("CALENDLY_WEBHOOK_MAX_BYTES", 1_000_000)


def _normalize_url(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def _match_host(resource):
    scheduling_url = _normalize_url(resource.get("scheduling_url"))
    if not scheduling_url:
        return None
    for host in CallHost.objects.exclude(booking_url=""):
        if _normalize_url(host.booking_url) == scheduling_url:
            return host
    return None


def _event_fields(payload):
    resource = payload.get("payload") or {}
    scheduled_event = resource.get("scheduled_event") or {}
    start_time = scheduled_event.get("start_time")
    return resource, {
        "calendly_event_uri": str(scheduled_event.get("uri") or "").strip(),
        "scheduled_at": parse_datetime(start_time) if start_time else None,
        "invitee_email": str(resource.get("email") or "").strip().lower(),
        "invitee_name": str(resource.get("name") or "").strip(),
        "calendly_invitee_uri": str(resource.get("uri") or "").strip(),
        "reschedule_url": str(resource.get("reschedule_url") or "")[:500],
        "cancel_url": str(resource.get("cancel_url") or "")[:500],
    }


def _event_time(payload, resource, *, canceled=False):
    raw = resource.get("canceled_at") if canceled else None
    raw = raw or payload.get("created_at") or resource.get("created_at")
    return (parse_datetime(raw) if raw else None) or timezone.now()


def _latest(first, second):
    return max(value for value in (first, second) if value is not None)


def _increment_load(host):
    CallHost.objects.filter(pk=host.pk).update(current_load=F("current_load") + 1)


def _decrement_load(host):
    CallHost.objects.filter(pk=host.pk, current_load__gt=0).update(
        current_load=F("current_load") - 1
    )


def _update_staged(staged, fields, resource, *, status, event_at):
    staged.member = resolve_user_by_email(fields["invitee_email"]) or staged.member
    for name in (
        "invitee_email",
        "invitee_name",
        "scheduled_at",
        "calendly_invitee_uri",
        "reschedule_url",
        "cancel_url",
    ):
        value = fields[name]
        if value:
            setattr(staged, name, value)
    staged.scheduling_url = str(resource.get("scheduling_url") or "")[:500]
    staged.last_event_at = _latest(staged.last_event_at, event_at)
    if status == STATUS_CANCELED or staged.status == STATUS_CANCELED:
        staged.status = STATUS_CANCELED
        staged.canceled_at = staged.canceled_at or event_at
    else:
        staged.status = STATUS_BOOKED
        staged.canceled_at = None
    staged.save()
    return staged


def _stage(fields, resource, *, status, event_at):
    staged, _created = UnmatchedBookedCall.objects.select_for_update().get_or_create(
        calendly_event_uri=fields["calendly_event_uri"]
    )
    return _update_staged(staged, fields, resource, status=status, event_at=event_at)


def _promote(staged, host):
    booked, created = BookedCall.objects.get_or_create(
        calendly_event_uri=staged.calendly_event_uri,
        defaults={
            "host": host,
            "member": staged.member,
            "invitee_email": staged.invitee_email,
            "invitee_name": staged.invitee_name,
            "scheduled_at": staged.scheduled_at,
            "status": staged.status,
            "calendly_invitee_uri": staged.calendly_invitee_uri,
            "reschedule_url": staged.reschedule_url,
            "cancel_url": staged.cancel_url,
            "canceled_at": staged.canceled_at,
            "last_event_at": staged.last_event_at,
        },
    )
    if created and booked.is_active:
        _increment_load(host)
    if created or booked.host_id == host.pk:
        staged.delete()
    return booked


@transaction.atomic
def handle_invitee_created(payload):
    resource, fields = _event_fields(payload)
    event_uri = fields["calendly_event_uri"]
    if not event_uri:
        return None
    event_at = _event_time(payload, resource)
    host = _match_host(resource)
    staged = (
        UnmatchedBookedCall.objects.select_for_update().filter(calendly_event_uri=event_uri).first()
    )
    if host is None:
        return _stage(fields, resource, status=STATUS_BOOKED, event_at=event_at)
    if staged is not None:
        _update_staged(staged, fields, resource, status=STATUS_BOOKED, event_at=event_at)
        return _promote(staged, host)
    booked = BookedCall.objects.select_for_update().filter(calendly_event_uri=event_uri).first()
    if booked is not None:
        for name in (
            "invitee_email",
            "invitee_name",
            "scheduled_at",
            "calendly_invitee_uri",
            "reschedule_url",
            "cancel_url",
        ):
            value = fields[name]
            if value:
                setattr(booked, name, value)
        booked.member = resolve_user_by_email(fields["invitee_email"]) or booked.member
        booked.last_event_at = _latest(booked.last_event_at, event_at)
        booked.save()
        return booked
    booked = BookedCall.objects.create(
        host=host,
        member=resolve_user_by_email(fields["invitee_email"]),
        status=STATUS_BOOKED,
        last_event_at=event_at,
        **fields,
    )
    _increment_load(host)
    return booked


@transaction.atomic
def handle_invitee_canceled(payload):
    resource, fields = _event_fields(payload)
    event_uri = fields["calendly_event_uri"]
    invitee_uri = fields["calendly_invitee_uri"]
    event_at = _event_time(payload, resource, canceled=True)
    booked = None
    if event_uri:
        booked = BookedCall.objects.select_for_update().filter(calendly_event_uri=event_uri).first()
    if booked is None and invitee_uri:
        booked = (
            BookedCall.objects.select_for_update().filter(calendly_invitee_uri=invitee_uri).first()
        )
    if booked is not None:
        if booked.status == STATUS_BOOKED:
            booked.status = STATUS_CANCELED
            booked.canceled_at = event_at
            booked.last_event_at = _latest(booked.last_event_at, event_at)
            booked.save(update_fields=("status", "canceled_at", "last_event_at", "updated_at"))
            _decrement_load(booked.host)
        return booked
    staged = None
    if event_uri:
        staged = (
            UnmatchedBookedCall.objects.select_for_update()
            .filter(calendly_event_uri=event_uri)
            .first()
        )
    if staged is None and invitee_uri:
        staged = (
            UnmatchedBookedCall.objects.select_for_update()
            .filter(calendly_invitee_uri=invitee_uri)
            .first()
        )
    host = _match_host(resource)
    if staged is not None:
        _update_staged(staged, fields, resource, status=STATUS_CANCELED, event_at=event_at)
        return _promote(staged, host) if host is not None else staged
    if not event_uri:
        return None
    if host is None:
        return _stage(fields, resource, status=STATUS_CANCELED, event_at=event_at)
    return BookedCall.objects.create(
        host=host,
        member=resolve_user_by_email(fields["invitee_email"]),
        status=STATUS_CANCELED,
        canceled_at=event_at,
        last_event_at=event_at,
        **fields,
    )


def process_webhook(payload):
    event = payload.get("event")
    if event == EVENT_INVITEE_CREATED:
        return handle_invitee_created(payload)
    if event == EVENT_INVITEE_CANCELED:
        return handle_invitee_canceled(payload)
    return None
