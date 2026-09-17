# Kernel

The kernel contains the settings, hooks, access, execution-context, redaction, idempotency and
service contracts used by all shared apps, plus two model base classes. Neither base class defines
a concrete model of its own, so the kernel still ships no table and needs no migration; a consuming
app's own concrete model gets one only when it inherits `RevisionedModel` or points its `objects`
manager at `AppendOnlyManager`.

## Model bases

`community_base.kernel.models` (moved from DTC `core/models.py`, decision D19, issue C7.5):

| Class | Use it for |
|---|---|
| `RevisionedModel` | An abstract model with a `revision` field and a conditional `save()`: optimistic concurrency for a row a service mutates over time. |
| `AppendOnlyManager` | A manager whose queryset blocks `update()`, `delete()`, `bulk_create()` and `bulk_update()`: evidence rows nothing may rewrite once written. |

### `RevisionedModel`

Add `revision = models.PositiveBigIntegerField(default=1)` by inheriting the base, then on every
mutation: load the row, increment `instance.revision` by exactly one, and call
`instance.save(update_fields=[..., "revision"])`, always including `"revision"` in
`update_fields`. The base turns that call into one conditional `UPDATE ... WHERE pk = ? AND
revision = ?` (the persisted value one less than the new one), so SQLite and deployed PostgreSQL
run the same compare-and-swap without a database-specific row lock.

A plain `save()` (creation, or an update whose `update_fields` omits `"revision"`) is not
intercepted; it goes through Django's ordinary `save()` unchanged.

The conflict a caller must handle:

```python
from community_base.kernel.models import RevisionConflict

try:
    record.revision += 1
    record.save(update_fields=["label", "revision"])
except RevisionConflict as exc:
    # exc.expected: the revision this save assumed was current
    # exc.actual: the revision actually persisted
    ...
```

`RevisionConflict` is a `RuntimeError` carrying `expected` and `actual` revision numbers. It is
raised instead of silently overwriting a row another writer changed first; the losing writer's
values never reach the database. A caller that meant `expected_revision` to gate a stale read
(rather than only guard the write) reloads the row and decides whether to retry; the base class
itself does not retry.

Two narrower failures on the same conditional path: `ValueError` if the caller passes positional
arguments or `force_insert`, or sets `revision` to less than 2 (an update must always have
already incremented it past its initial value of 1); the model's own `DoesNotExist` if the row was
deleted before the conditional update ran.

### `AppendOnlyManager`

```python
class AuditRow(models.Model):
    ...
    objects = AppendOnlyManager()

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
```

`AppendOnlyManager.objects.filter(...).update(...)`, `.delete()`, `.bulk_create(...)` and
`.bulk_update(...)` all raise `AppendOnlyViolation` (a `RuntimeError`) unconditionally; only
`.create()` (a plain `INSERT`) succeeds. This guards the manager-level API. A plain
`instance.save()` on an existing row, or `instance.delete()` on a row with no dependents, goes
through Django's low-level single-row SQL path and does not reach the queryset, so it is not
blocked by this base alone; a model that needs that too adds its own thin `save()`/`delete()`
override, the same way DTC's `AuditEvent` does.

The donor's queryset also let `AuditEvent` null two specific foreign keys (`actor`,
`api_principal`) through Django's `on_delete=SET_NULL` cascade, so a deleted user is forgotten
without rewriting the append-only audit trail otherwise. That carve-out named the concrete DTC
model inside the shared queryset and did not move here: `AuditEvent` stays DTC-owned (decision
D19 excludes the eleven consuming models from this issue), and copying the carve-out verbatim
would require importing a site model into the kernel. The kernel's `AppendOnlyManager` is
unconditionally append-only. This changes nothing for what actually moved: none of DTC's
`RevisionedModel` subclasses use `AppendOnlyManager`, only `AuditEvent` does, and `AuditEvent` is
not part of this move. A later issue that migrates `AuditEvent` onto this base decides, from the
DTC side, how to keep that allowance if it still needs it.

## `COMMUNITY_BASE` settings

| Key | Type | Default |
|---|---|---|
| `ACCOUNT_BEFORE_DELETE_HOOK` | dotted path, callable or `None` | `None` |
| `ACCOUNT_DELETION_BLOCKER` | dotted path, callable or `None` | `None` |
| `ACCOUNT_MERGE_HOOK` | dotted path, callable or `None` | `None` |
| `ACCOUNT_PRIVACY_EXPORT_HOOK` | dotted path, callable or `None` | `None` |
| `ACCOUNT_UNVERIFIED_TTL_DAYS` | positive integer days | `7` |
| `CONTENT_SOURCES` | list of source dictionaries | `[]` |
| `CONTENT_SYNC_GITHUB_API_URL` | absolute URL | `"https://api.github.com"` |
| `CONTENT_SYNC_GITHUB_APP_ID` | `str` | `""` |
| `CONTENT_SYNC_GITHUB_INSTALLATION_ID` | `str` | `""` |
| `CONTENT_SYNC_GITHUB_PRIVATE_KEY` | PEM `str` | `""` |
| `CONTENT_SYNC_HTTP_TIMEOUT` | positive seconds | `30` |
| `CONTENT_SYNC_MAX_ARCHIVE_BYTES` | positive bytes | `100000000` |
| `CONTENT_SYNC_MEDIA_BACKEND` | `"null"` or `"s3"` | `"null"` |
| `CONTENT_SYNC_S3_BUCKET` | `str` | `""` |
| `CONTENT_SYNC_S3_PREFIX` | object-key prefix | `"content-sync"` |
| `CONTENT_SYNC_S3_PUBLIC_URL` | absolute URL or empty | `""` |
| `CONTENT_SYNC_S3_REGION` | AWS region or empty | `""` |
| `SITE_KEY` | `str` | `""` |
| `ACCESS_POLICY` | dotted path or policy object | `"community_base.kernel.access.OpenPolicy"` |
| `JOBS_BACKEND` | `str` | `"sync"` |
| `MAIL_BACKEND` | `str` | `"memory"` |
| `MAIL_CONTEXT_RESOLVER` | dotted path, callable or `None` | `"community_base.accounts.mail_context.resolve_delivery_context"` |
| `MAIL_PREFERENCE_RESOLVER` | dotted path or callable | `"community_base.accounts.preferences.resolve_mail_preference"` |
| `MAIL_SEND_RECORDER` | dotted path, callable or `None` | `None` |
| `MAIL_TEMPLATE_DIR` | path or `None` | `None` |
| `MAIL_TEMPLATE_OVERRIDE_LOADER` | dotted path, callable or `None` | `None` |
| `MAIL_UNSUBSCRIBE_URL_BUILDER` | dotted path, callable or `None` | `None` |
| `MAIL_VERIFY_EMAIL_URL_BUILDER` | dotted path, callable or `None` | `None` |
| `RELAY_API_KEY` | `str` | `""` |
| `RELAY_BASE_URL` | `str` | `""` |
| `RELAY_WEBHOOK_SECRET` | `str` | `""` |
| `SITE_URL` | absolute URL | `""` |
| `STUDIO_TITLE` | `str` | `"Community Studio"` |
| `STUDIO_AUDIT_WRITER` | dotted path or callable | `"community_base.studio.audit.discard_audit_event"` |
| `USER_TAGS_ACCESSOR` | dotted path or accessor object | `"community_base.studio.user_tags.AttributeTagsAccessor"` |

Site settings override only the keys they need:

```python
COMMUNITY_BASE = {
    "SITE_KEY": "dtc",
    "ACCESS_POLICY": "community_base.kernel.access.RegisteredOnlyPolicy",
    "JOBS_BACKEND": "relay",
    "MAIL_BACKEND": "relay",
    "RELAY_API_KEY": env("RELAY_API_KEY"),
    "RELAY_BASE_URL": "https://relay.example.com",
    "RELAY_WEBHOOK_SECRET": env("RELAY_WEBHOOK_SECRET"),
    "SITE_URL": "https://community.example.com",
    "STUDIO_TITLE": "DataTalks.Club Studio",
}
```

Unknown keys requested through `community_base.kernel.conf.get` raise
`django.core.exceptions.ImproperlyConfigured`.
