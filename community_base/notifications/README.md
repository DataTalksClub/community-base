# Notifications

Install `community_base.notifications` to give signed-in members an on-site notification list and
bell. The app keeps the Django label `notifications` for the later donor migration squash, but its
initial migration remains provisional until C3.7 verifies the donor schema.

## Installation

Install notifications after accounts.

```python
INSTALLED_APPS = [
    "community_base.kernel",
    "community_base.accounts",
    "community_base.notifications",
]
```

Mount the page routes and API routes separately to preserve the existing names and paths.

```python
from community_base.notifications.urls import api_urlpatterns

urlpatterns = [
    path("", include("community_base.notifications.urls")),
    path("api/", include(api_urlpatterns)),
]
```

Run migrations after installing the app.

```bash
python manage.py migrate
```

## Register a source

Each site registers builders for the events it owns. A builder receives an event name and a
payload, then returns `NotificationDraft` objects with explicit recipient IDs. This removes imports
from notifications into events, plans, content, or book-club code.

```python
from community_base.notifications.registry import (
    NotificationDraft,
    register_notification_source,
)
```

Register the builder during app startup.

```python
@register_notification_source("events")
def event_notifications(*, event, payload):
    if event != "published":
        return ()
    return (
        NotificationDraft(
            recipient_id=payload["recipient_id"],
            title=f"New event: {payload['title']}",
            url=payload["url"],
            notification_type="event",
            source_id=str(payload["event_id"]),
            dedupe_key=f"event-published:{payload['event_id']}",
        ),
    )
```

Call `emit_notification("events", "published", payload)` when you want errors to reach the caller,
or use `notification_event` or `emit_notification_safely()` for best-effort fan-out. The safe path
logs only the source key and event name, without the payload or exception text.

Use a stable `dedupe_key` for an event that must notify each recipient once. The database enforces
that key per recipient. Leave it empty when repeated notifications are intentional.

## Preferences and ownership

Call `set_notification_preference(user, source_key, enabled)` to store an opt-out or opt-in. The
special source `*` sets the default, while a source-specific row takes precedence. New sources are
enabled unless the member has disabled the global default.

The service skips inactive accounts and disabled sources. Every list, count, and write endpoint
filters by the signed-in member, so someone can't read or mark another member's notification.
Account privacy exports include notification text, source metadata, read state, and preferences.
Account deletion removes those rows by cascade.

## Pages, API, and bell

The package preserves these route names:

- `notification_list`
- `api_notification_list`
- `api_unread_count`
- `api_mark_read`
- `api_mark_all_read`

The list API accepts `filter=all` or `filter=unread` and returns 20 rows per page. Member responses
use private no-store headers. Notification URLs accept site-relative paths or full HTTP and HTTPS
URLs. The service removes unsafe schemes, protocol-relative links, and backslash redirects before
storage.

Load the template tags and render the bell where your site needs it.

```django
{% load notification_tags %}
{% notification_bell %}
```

Override `notifications/_bell.html` or `notifications/notification_list.html` in the site template
directory when the site needs different markup. Keep the route names and context variables intact.
