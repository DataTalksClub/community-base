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
| `CONTENT_SYNC_NULL_MEDIA_URL_PREFIX` | site-absolute path prefix | `"/media/content-sync/"` |
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
| `MARKDOWN_EXTENSIONS` | list of dotted paths appended to the package markdown extension list | `[]` |
| `RELAY_API_KEY` | `str` | `""` |
| `RELAY_BASE_URL` | `str` | `""` |
| `RELAY_WEBHOOK_SECRET` | `str` | `""` |
| `SITE_URL` | absolute URL, required at first use once a purpose needs it | `""` |
| `STUDIO_TITLE` | `str` | `"Community Studio"` |
| `STUDIO_AUDIT_WRITER` | dotted path or callable | `"community_base.studio.audit.discard_audit_event"` |
| `STUDIO_EXTRA_CSS` | `str`, or a list/tuple of `str` | `()` |
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

## The public template seam

`community_base/kernel/templates/community_base/public/base.html` is the one place the package
touches a consuming site's own chrome. Every shared public page template extends it rather than
`base.html`, and the shipped copy is a pass-through whose entire body is
`{% extends "base.html" %}`.

A site whose base defines `title`, `meta_description`, `page_head_metadata`, `content` and
`extra_js` (`docs/02-architecture.md` section 5) does nothing, and the seam changes no byte of any
shared public page there. A site whose base names those slots differently overrides that one path
in its own `templates/` directory and maps its names onto the contracted ones, instead of adding
package-named blocks to the file every page on the site inherits from.

`community_base/kernel/template_contract.py` is the contract as data: which template fills which
block, and how badly the page fails when a block has nowhere to render.
`community_base/kernel/checks.py` reads the chain above the seam at `manage.py check` time and
reports what is missing, because Django drops the content of an undefined block in silence.
`community_base.kernel.E001` (a missing `content`) is an error; the other four are warnings;
`community_base.kernel.E002` means the chain could not be read at all. The reasoning is in
`docs/plan/evidence/c7.25-block-contract-decision-2026-09-18.md`.

## Settings that must not degrade silently

The package has had exactly one adopting site, and a setting shape that only happens to match
that site's configuration is untested against any other legal shape (issue C7.22). Three
instances of this reached `main` before being fixed by C7.27: an empty `SITE_URL` silently turned
outbound mail links relative instead of failing the send; `STUDIO_EXTRA_CSS` set to a single
string iterated as fifteen characters instead of one stylesheet; and a raw
`"community_base.events" in INSTALLED_APPS` membership test silently failed to recognise the
AppConfig-path spelling Django accepts everywhere. All three were true "it works here" bugs: fine
on AI-Shipping-Labs' actual settings, wrong (silently, in two of the three cases) on any other
legal Django configuration. The rules below are what the fix settled on, so the next setting a
module reads leans the same way instead of adding a fourth instance.

An empty or missing value: raise, at first use, not at import or `ready()` time. If a feature
cannot do its job without a value, calling it with an empty one is a bug in the site's
configuration, not a degraded mode the package should quietly accept: a relative link in an
email is not a smaller version of the feature, it is a broken one. Raise where the value is about
to be used, inside the branch that needs it, not once for the whole enclosing function: a
resolver, view or job handler that serves several purposes only some of which need the setting
must not fail the ones that do not. `community_base.kernel.conf.require(name)` is `get(name)`
plus this check, for exactly that call site.

Raising at first use rather than at startup matters for a site mid-adoption: `python manage.py
check`, migrations, and every other purpose the package serves keep working without the setting,
and a site that never triggers the one purpose that needs it (an events subsystem it does not
use, a password-reset flow replaced by SSO) is never affected by never having configured it. This
is also why the fix could not be "add a Django system check that requires `SITE_URL`": that would
force every site to set it, including ones with no present use for it, the opposite of the rule.
A site that sends the mail purposes needing `SITE_URL` (`accounts.verify_email`,
`accounts.password_reset`, `accounts.email_change_confirm`, `events.verify_registration`,
`events.registration_confirmed`, `events.guest_invitation`; also required already, unrelated to
this issue, by `events/integrations/calendar.py`, `jobs/relay.py`, `jobs/relay_scheduling.py`)
must configure it or those specific sends fail loudly, logged and retried by the job runner like
any other handler error, rather than delivering a mail nobody can act on.

A value whose shape can vary: accept the string shape a site would reasonably reach for, do not
iterate blind. A Python `str` is itself a sequence, so a setting typed as "a list of paths" or "a
list of channel ids" silently accepts a single string too, walks its characters, and produces a
result of the right type and the wrong content, no exception anywhere: `STUDIO_EXTRA_CSS =
"site/studio.css"` iterated into fifteen one-character stylesheet links. Where the natural site
config for the common one-item case is a bare string, accept it explicitly (wrap it as the single
item) rather than let it fall into the iteration meant for the multi-item case; refuse (raise)
any other shape rather than iterate it on faith.

`community_base.community.services._channel_ids` already does this for
`SLACK_COMMUNITY_CHANNEL_IDS` (splits a string on commas); `studio_filters.studio_extra_css` now
does it for `STUDIO_EXTRA_CSS` (wraps a string as one item, since one stylesheet path has no
natural comma-list reading). `CONTENT_SOURCES` was already fine: it requires a `list` outright and
raises `CommandError` on anything else, so a string was already refused rather than iterated.
Grep for a bare `for ... in get(...)` or a bare `*get(...)` unpacking before adding a new
sequence-shaped setting; `content_sync.rendering.markdown_extensions`'s `*configured` spread over
`MARKDOWN_EXTENSIONS` has the same shape and was not confirmed by the C7.22 audit (`content_sync`
rendering was out of its scope), so it is not fixed here, only flagged.

A value that names another app: use `django.apps.apps.is_installed(app_name)`, never a
membership test against `settings.INSTALLED_APPS` strings. Django accepts both the plain module
path (`"community_base.events"`) and the AppConfig dotted path
(`"community_base.events.apps.EventsConfig"`) in `INSTALLED_APPS`, resolves both to the same
`AppConfig.name`, and a site is free to use either everywhere Django itself accepts an app entry.
`apps.is_installed()` already handles both; a raw `in` test against the configured list only
recognises the spelling the check happened to be written against. Nine call sites already did
this correctly before C7.27; `community_base/curriculum/apps.py` was the only one that did not.
