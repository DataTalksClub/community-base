# Durable jobs

`community_base.jobs` stores an intent before any background work is submitted. The database row
owns deduplication, retry state and lease fencing, while a backend only wakes a runner by intent
ID. Job payloads must contain opaque identifiers and ordinary JSON values, never credentials,
email addresses, message bodies or URLs.

## Register and dispatch work

```python
from django.db import transaction

from community_base.jobs import dispatch_after_commit, register_handler, schedule
from community_base.jobs.runner import RetryableJobError


@register_handler("events.send_reminders")
def send_reminders(context, payload):
    event_id = payload["event_id"]
    # Perform idempotent work. Raise RetryableJobError("provider_unavailable") to retry.


schedule(
    "events.send_reminders",
    cron="*/15 * * * *",
    payload={},
    name="event-reminders",
)

with transaction.atomic():
    intent, created = dispatch_after_commit(
        "events.send_reminders",
        key="event-reminders:42",
        payload={"event_id": 42},
    )
```

Dispatch requires an active database transaction. It writes the intent immediately and submits
only after that transaction commits. Reusing a key with the same immutable input returns the
existing intent; reusing it with different input raises `DispatchConflict`.

Handlers receive a `JobContext` with the job ID, correlation ID, attempt, worker ID and lease
token. Unexpected exceptions and `RetryableJobError` retry with bounded exponential backoff.
`PermanentJobError` moves the intent directly to `dead`. Error text and exception bodies are not
stored.

## Backends

| Backend | Use | Installation |
|---|---|---|
| `sync` | Inline execution after commit, primarily for tests and local development | Base package |
| `django_q` | Submit `run_intent(intent_id)` to a django-q2 cluster | `community-base[django_q]` |
| `relay` | Signed Relay webhook tasks and Relay-owned retries | Base package |

The Relay backend submits `POST /api/tasks` with a namespaced idempotency key, the package ingress
URL and only the durable intent ID. A timeout leaves the intent pending; resubmission uses the same
key so Relay returns the original task. Successful submission stores the Relay task ID in
`external_id` before execution can be accepted.

Sites using `django_q` also add `django_q` to `INSTALLED_APPS`, configure `Q_CLUSTER`, run its
migrations and execute `sync_schedules`. The command creates or updates namespaced cron rows and
also installs the once-per-minute due-intent wake-up.

## Signed Relay ingress

Mount `community_base.jobs.urls` at `/internal/jobs/`. Relay posts JSON containing `intent_id` to
`/internal/jobs/run` with these headers:

- `X-Relay-Task-Id`
- `X-Relay-Correlation-Id`
- `X-Relay-Timestamp`
- `X-Relay-Signature`

The signature is `sha256=<hex digest>` for HMAC-SHA256 over `<timestamp>.<raw body>`. Timestamps
outside five minutes, altered bodies, unsafe context IDs and replayed task IDs are rejected. The
endpoint never logs the body or signing secret. A handler registered with `chunked=True` receives
a `202` response containing `lease_seconds` and keeps its local lease. The continuation finishes
through `complete_chunked_job(intent_id, lease_token)` or
`fail_chunked_job(intent_id, lease_token, error_code=..., retryable=...)`. A stale or expired local
lease is rejected before any completion request reaches Relay. Real completion endpoints require
Relay issue R1.2.

Run `python manage.py jobs_ingress_selftest` after configuring the site URL and webhook secret.
It creates a no-op intent and round-trips an in-process signed request through the site's URL
configuration.

## Commands and Studio

- `jobs_run_due [--limit N]` submits due unleased intents to the configured local backend.
- `jobs_sweep [--limit N]` recovers expired leases or marks exhausted jobs dead.
- `sync_schedules [--dry-run]` reconciles registry schedules for django-q; it is a no-op for sync.
- `sync_relay_schedules [--dry-run]` reconciles this site's namespaced Relay schedules and disables
  stale package-owned rows.
- `jobs_ingress_selftest` verifies ingress signing, routing, persistence and execution.

Mount `community_base.jobs.studio_urls` under `/studio/` for the staff-only durable jobs page. It
lists active and failed intents without rendering payloads, shows registered schedules and local
or Relay last/next run data, projects Relay readiness and task counts, and provides explicitly
confirmed retry and discard actions.
Discarding a running intent clears its lease so a stale worker cannot complete it.

## Settings

All keys live inside Django's `COMMUNITY_BASE` dictionary.

| Key | Purpose | Default |
|---|---|---|
| `JOBS_BACKEND` | `sync`, `django_q`, or `relay` | `"sync"` |
| `SITE_URL` | Public absolute site origin used for Relay callbacks and ingress self-test | `""` |
| `RELAY_BASE_URL` | Relay API origin | `""` |
| `RELAY_API_KEY` | Relay bearer credential | `""` |
| `RELAY_WEBHOOK_SECRET` | Secret that authenticates Relay webhook requests | `""` |

Keep Relay credentials in environment-backed settings. Do not place them in job payloads,
database error fields, logs or Studio output.
