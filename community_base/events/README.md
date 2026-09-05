# Events

Use `community_base.events` for event identity, registration, reminders and integrations. It also
provides public pages, Studio operations and session APIs. The app has no imports from either
website, so each site can supply access rules and optional integrations through package settings.

## Install and mount

Add the app after the package kernel. Registration also needs the package accounts, jobs and mail
apps.

```python
INSTALLED_APPS = [
    "community_base.kernel",
    "community_base.accounts",
    "community_base.events",
    "community_base.api",
    "community_base.jobs",
    "community_base.mail",
    "community_base.studio",
]
```

Mount public routes below `events/`, session APIs below `api/v1/`, and event Studio routes below
the shared Studio prefix.

```python
from django.urls import include, path

from community_base.api.registry import urlpatterns as api_urlpatterns

urlpatterns = [
    path("events/", include("community_base.events.urls")),
    path("api/v1/", include((api_urlpatterns(), "cb_api"))),
    path("studio/", include("community_base.studio.urls")),
    path("studio/", include("community_base.events.studio_urls")),
]
```

Call `api_urlpatterns()` after Django loads the apps because `EventsConfig.ready()` registers the
event API definitions.

## Public routes and templates

Set `COMMUNITY_BASE["EVENT_URL_STYLE"]` to `slug` or `public_id`, and keep both route forms mounted
so requests to the other form receive a permanent redirect to the configured canonical URL.
Use `EventAlias` rows to preserve reviewed historical paths.

The package owns these stable URL names:

- `events_list` and `event_detail`
- `event_register`, `event_unregister` and `event_feedback`
- `event_registration_verify` and `event_registration_manage`
- `event_calendar`

You can override `event_list.html`, `event_detail.html`, `registration_result.html` and
`registration_manage.html` with the same paths under `templates/events/`.

## Configuration and hooks

Configure `SITE_URL`, `ACCESS_POLICY` and `EVENT_URL_STYLE` for every site. Set
`EVENT_PRIVACY_NOTICE_VERSION` and `EVENT_NEWSLETTER_CONSENT_VERSION` to the versions shown by the
site registration form. Set `EVENT_ORGANIZER_EMAIL` and `EVENT_ORGANIZER_NAME` for calendar output.

Set `ZOOM_ENABLED` only after providing the account ID, client ID and client secret. The Zoom
client accepts HTTPS endpoints and a timeout from 1 to 60 seconds. It never stores an OAuth token
or raw provider response.

You can provide these optional callables:

- `HOST_PROFILE_RESOLVER` maps a package host to a site profile URL.
- `EVENT_BANNER_GENERATOR` returns a banner URL.
- `EVENT_WRITEUP_RESOLVER` returns a dictionary with `url` and `title`.
- `EVENT_RECORDING_PROCESSOR` converts an opaque provider reference into safe recording URLs.
- `EVENT_RECORDING_READY_HOOK` runs after recording URLs commit.

Django event callbacks for publish, cancel, reschedule, register and unregister run after the
surrounding transaction commits. Studio mutations call `STUDIO_AUDIT_WRITER` with an actor and
target reference.

## Jobs and mail

The app registers these durable handlers:

- `events.plan_reminders` and `events.send_reminder`
- `events.expire_registration_verifications`
- `events.sync_zoom`
- `events.process_recording`

Reminder planning and verification expiry run every 15 minutes, while provider jobs store scalar
IDs or opaque references. A durable `EventIntegrationAttempt` row prevents a retry from repeating
a Zoom mutation after a worker loses the response.

The app sends registration, reminder and guest-invitation mail through `community_base.mail`.
Verification and management tokens are created inside the mail worker and never stored in job or
delivery context.

## Session API ownership

All event API routes use cookie-session authentication and CSRF protection. Staff can manage
events, series, hosts and registrant lists. They can also queue guest invitations, Zoom sync and
recording processing. Members can read or cancel only their own registration and can submit
feedback only for that registration. Run the OpenAPI command after changing a route.

```bash
uv run python testproject/manage.py openapi --output community_base/api/openapi.json
uv run python testproject/manage.py openapi --check --output community_base/api/openapi.json
```

## Migration status

The package keeps the donor `events` app label. Its migrations are provisional and must remain
untagged until C4.3 records the exact donor migration inventory, verifies `replaces`, compares the
schemas and completes the database rehearsals.
