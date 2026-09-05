# Community access and calls

Install `community_base.community` when your site needs Slack access grants, workspace membership
sync, or optional community calls. The app keeps the existing Django label `community` so it can
replace a donor app during the later migration squash.

## Installation

Install the app after accounts. Add jobs and Studio when you need background Slack operations and
staff pages.

```python
INSTALLED_APPS = [
    "community_base.kernel",
    "community_base.accounts",
    "community_base.jobs",
    "community_base.studio",
    "community_base.community",
]
```

Mount the member and staff routes. You choose the outer prefix, so the package can preserve an
existing site's URL names and paths.

```python
urlpatterns = [
    path("accounts/community/", include("community_base.community.urls")),
    path("studio/", include("community_base.studio.urls")),
    path("studio/", include("community_base.community.studio_urls")),
]
```

Run migrations after installing the app.

```bash
python manage.py migrate
```

## Slack access grants

`SlackAccessGrant` records who can reveal the current invite and which non-secret invite version
they received. It never stores the invite URL. Configure that URL from an environment-backed
setting and rotate `SLACK_INVITE_VERSION` whenever you rotate the provider link.

```python
COMMUNITY_BASE = {
    "SLACK_INVITE_URL": os.environ["SLACK_INVITE_URL"],
    "SLACK_INVITE_VERSION": "2026-09",
}
```

The default eligibility check requires an active, authenticated member with a verified email.
Override `COMMUNITY_ELIGIBILITY` with a callable or dotted path when your site ties Slack access to
a paid tier. Onboarding completion creates a grant automatically when you install
`community_base.onboarding`.

Members reveal the invite through `community_base_slack_access`. The response is private and sends
`Cache-Control: private, no-store, max-age=0`, `Referrer-Policy: no-referrer`, and a no-index robots
header. Invite mail stores only `{"invite_version": "..."}` in its durable context. The mail
context resolver reads the live URL when it renders the message.

## Slack API and durable jobs

Enable the API client when you want the package to look up workspace members and add or remove them
from managed channels.

```python
COMMUNITY_BASE = {
    "SLACK_ENABLED": True,
    "SLACK_BOT_TOKEN": os.environ["SLACK_BOT_TOKEN"],
    "SLACK_COMMUNITY_CHANNEL_IDS": ["C0123", "C0456"],
    "SLACK_TEAM_ID": "T0123",
}
```

The client retries one rate-limited request, caps the provider-request timeout, and records bounded
error codes instead of response bodies or credentials. `slack_import_rows()` paginates through
workspace members and supplies the accounts import service with verified identities, Slack IDs,
time zones, and normalized tags.

Inside a transaction, call `queue_user_action()` with only the account's numeric ID in the job
payload. It accepts `invite` and `reactivate`, plus `remove` and `check_membership`. When you install
`community_base.jobs`, the app registers a 30-minute stale-membership schedule. Tune its work with
`SLACK_MEMBERSHIP_BATCH_SIZE` and `SLACK_MEMBERSHIP_REFRESH_DAYS`.

Set `COMMUNITY_JOINED_HOOK` when staff or analytics need a notification after a previously checked
account becomes a confirmed workspace member. The hook receives `user` as a keyword argument.

## Optional Calendly calls

Set `CALENDLY` to `True` to expose the call-host page and webhook. Keep it false on sites that don't
offer booked community calls.

```python
COMMUNITY_BASE = {
    "CALENDLY": True,
    "CALENDLY_WEBHOOK_SIGNING_KEY": os.environ["CALENDLY_WEBHOOK_SIGNING_KEY"],
    "CALENDLY_WEBHOOK_TOLERANCE_SECONDS": 300,
}
```

Point Calendly at the mounted `community_base_calendly_webhook` route. The endpoint fails closed
when the signing key or HMAC signature is missing. It also rejects stale signatures and oversized
bodies, then handles provider retries idempotently by event URI.

In Studio, create `CallHost` rows so signed-in members can see active hosts with valid HTTP booking
URLs alongside their own active bookings. Webhooks resolve primary and alias emails, update
host load atomically, preserve cancellation tombstones, and stage events whose host URL doesn't
match yet. Staff can look at those staged events before correcting the host configuration.

## Studio

Mount `community_base.community.studio_urls` under the same prefix as the Studio shell. Staff can
search access grants and audit records, configure call hosts, and review booked or unmatched calls.
Staff see the invite version and revocation state on the grant page, but the view never receives the
Slack invite URL or bot token.
