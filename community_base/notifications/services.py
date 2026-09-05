import logging
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from community_base.notifications.models import Notification, NotificationPreference
from community_base.notifications.registry import SOURCE_KEY, NotificationDraft, notification_source

logger = logging.getLogger(__name__)


def safe_notification_url(value):
    raw = str(value or "").strip()
    if not raw or "\\" in raw or raw.startswith("//"):
        return "" if raw else raw
    parts = urlsplit(raw)
    if parts.scheme:
        return raw if parts.scheme in {"http", "https"} and parts.netloc else ""
    return raw if raw.startswith("/") else ""


def notifications_enabled(user, source_key):
    values = dict(
        NotificationPreference.objects.filter(
            user=user, source_key__in=("*", source_key)
        ).values_list("source_key", "enabled")
    )
    return values.get(source_key, values.get("*", True))


def set_notification_preference(user, source_key, enabled):
    if source_key != "*" and not SOURCE_KEY.fullmatch(str(source_key)):
        raise ValueError("invalid notification preference source")
    preference, _created = NotificationPreference.objects.update_or_create(
        user=user,
        source_key=source_key,
        defaults={"enabled": bool(enabled)},
    )
    return preference


@transaction.atomic
def create_notification(draft, *, source_key):
    if not isinstance(draft, NotificationDraft):
        raise TypeError("notification sources must return NotificationDraft objects")
    user = get_user_model().objects.filter(pk=draft.recipient_id, is_active=True).first()
    if user is None or not notifications_enabled(user, source_key):
        return None, False
    values = {
        "title": str(draft.title).strip()[:300],
        "body": str(draft.body or ""),
        "url": safe_notification_url(draft.url)[:500],
        "notification_type": str(draft.notification_type or "announcement")[:64],
        "source_key": source_key,
        "source_id": str(draft.source_id or "")[:128],
    }
    if not values["title"]:
        raise ValueError("notification title is required")
    dedupe_key = str(draft.dedupe_key or "")[:128]
    if dedupe_key:
        notification, created = Notification.objects.get_or_create(
            user=user,
            dedupe_key=dedupe_key,
            defaults=values,
        )
        return notification, created
    return Notification.objects.create(user=user, dedupe_key="", **values), True


def emit_notification(source_key, event, payload=None):
    drafts = notification_source(source_key)(event=event, payload=payload or {})
    created = []
    for draft in drafts or ():
        notification, was_created = create_notification(draft, source_key=source_key)
        if was_created:
            created.append(notification)
    return tuple(created)


def emit_notification_safely(source_key, event, payload=None):
    try:
        return emit_notification(source_key, event, payload)
    except Exception:
        logger.warning(
            "notification_source_failed",
            extra={"notification_source": source_key, "notification_event": str(event)[:64]},
        )
        return ()


def mark_notification_read(user, notification_id):
    return Notification.objects.filter(pk=notification_id, user=user).update(
        read=True, read_at=timezone.now()
    )


def mark_all_notifications_read(user):
    return Notification.objects.filter(user=user, read=False).update(
        read=True, read_at=timezone.now()
    )
