# Testing helpers

`community_base.testing` exports deterministic helpers for package consumers. They do not make
network requests and need no Relay or AWS credentials.

## Synchronous jobs

Use `sync_jobs()` when a test should execute jobs after the surrounding transaction commits. It
temporarily selects the `sync` jobs backend and restores the site's configuration afterward.

```python
from community_base.testing import sync_jobs

with sync_jobs():
    service_that_dispatches_a_job()
```

With pytest-django, mark tests that commit work with `django_db(transaction=True)`.

## Email

`mail_outbox()` selects the memory mail backend, clears the process-local outbox before the test,
yields it, and clears it again afterward.

```python
import pytest

from community_base.testing import mail_outbox


@pytest.fixture
def messages():
    with mail_outbox() as captured:
        yield captured
```

Delivery still occurs only after commit, so transactional mail tests also need
`django_db(transaction=True)`.

## Relay

`FakeRelay` is an in-process transport for the package-pinned task, schedule, transactional mail,
template catalog, public recipient-link and callback contracts. Inject one instance into either
Relay client to exercise a complete lifecycle without patching HTTP globally.

```python
from community_base.jobs.relay import RelayClient
from community_base.testing import FakeRelay

relay = FakeRelay()
client = RelayClient("https://relay.example.com", "relay-test-key", transport=relay)
```

The fake exposes `tasks`, `schedules`, `messages`, `templates`, `calls`, `next_response`,
`suppress_next()`, `deliver()` and `post_callback()` for assertions and controlled failures.
`FakeResponse` can provide a specific next HTTP response. `unreachable_relay()` and
`timing_out_relay()` cover public-link degradation paths.

## Signed requests

`signed_relay_request(payload, secret, ...)` serializes canonical JSON and returns the body and
Relay HMAC headers. Call `django_kwargs()` on the result when posting through Django's test client.
Pass `task_id` to include the task and correlation headers required by job ingress; omit it for a
mail callback.

```python
from community_base.testing import signed_relay_request

signed = signed_relay_request(
    {"intent_id": "00000000-0000-0000-0000-000000000001"},
    "test-webhook-secret",
    task_id="relay-task-1",
    correlation_id="relay-correlation-1",
)
response = client.post("/internal/jobs/run", **signed.django_kwargs())
```

Use only test secrets and synthetic recipient data in fixtures and failure messages.
