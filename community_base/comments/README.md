# Comments

Install `community_base.comments` to add reusable discussion threads to any Django model with a
UUID thread field. The app keeps the Django label `comments` for the later donor migration squash,
but its initial migration remains provisional until C3.7 verifies the donor schema.

## Installation

Install comments after accounts and Django content types. Add notifications when comment owners
need on-site alerts, and add Studio when staff need moderation controls.

```python
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "community_base.accounts",
    "community_base.notifications",
    "community_base.studio",
    "community_base.comments",
]
```

Mount the public API and optional Studio routes.

```python
urlpatterns = [
    path("", include("community_base.comments.urls")),
    path("studio/", include("community_base.studio.urls")),
    path("studio/", include("community_base.comments.studio_urls")),
]
```

Run migrations after installing the app.

```bash
python manage.py migrate
```

## Register a target

Give the target model a stable UUID field, then register it during app startup. Comments retain the
UUID used by the existing routes and also store an optional Django generic relation for staff tools
and integrations.

```python
from community_base.comments.registry import register_comment_target
from events.models import Event
```

Register the model and its access checks.

```python
register_comment_target(
    "events",
    Event,
    content_id_field="comment_content_id",
    can_read=lambda event, user: event.can_view(user),
    can_write=lambda event, user: user.is_authenticated and event.can_comment(user),
    cascade_delete=True,
)
```

The read check receives the target and the current visitor, including anonymous visitors. The write
check receives the same values. If no registered target matches a UUID, anyone can read the thread
and any authenticated member can write. This preserves the donor behavior for public course and
workshop pages.

Set `cascade_delete=True` when deleting the target must delete its thread. The receiver deletes
comments, comment votes, and notifications with the exact `thread_content_id`. It never matches on
URL text.

## Render a thread

Load the template tag on any target page.

```django
{% load comment_tags %}
{% comment_thread event.comment_content_id %}
```

The partial loads `community_base/comments.js`, which lists comments and handles posting, one-level
replies, and top-level votes. It builds text with DOM `textContent`, sends same-origin requests, and
uses Django's CSRF cookie for writes. Override `comments/_thread.html` when your site needs different
markup, but keep its data attributes or replace the controller too.

The package preserves these route names:

- `comments_endpoint`
- `comments_reply`
- `comments_vote`

All responses use private no-store headers. A private target returns 404 for denied reads so the
thread's existence stays hidden, while denied writes return 403.

## Notifications and moderation

After a successful transaction, `comment_created` sends the new `comment` and `content_id`. Connect
a site receiver that resolves recipients and sends the C3.5a `notification_event` for its registered
`comments` source. Comments never import events, plans, content, or book-club modules.

Staff can search comments and hide or restore them under the Studio comments page. Hidden comments
and replies don't appear in the public API. Account privacy exports include comments authored by the
member and votes they cast. Deleting the account removes those rows by cascade.

Set `COMMUNITY_BASE["COMMENTS_MAX_BODY_LENGTH"]` to change the default 10,000-character body limit.
