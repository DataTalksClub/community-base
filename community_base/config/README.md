# Config app

`community_base.config` is the typed runtime configuration registry shared by package apps and
sites. Install it after `community_base.kernel` and `community_base.api`, then mount
`community_base.config.urls` below `/studio/`.

## Declare a key

Each app declares its keys in `settings_keys.py`. The config app imports those modules from every
installed app during Django startup.

```python
from community_base.config.registry import declare

ZOOM_CLIENT_ID = declare(
    key="ZOOM_CLIENT_ID",
    group="zoom",
    label="Zoom client id",
    description="OAuth client id from the Zoom marketplace app.",
    value_type="str",
    default="",
    secret=False,
    env_var="ZOOM_CLIENT_ID",
    docs_url="docs/integrations/zoom.md#zoom-client-id",
)
```

Supported `value_type` values are `str`, `int`, `bool`, `json`, and `list`. Metadata flags are
`secret`, `multiline`, `optional`, `is_email`, `django_settings_fallback`, and `docs_url`.
`django_settings_fallback=True` reads the key's own Django setting name; a string names a different
explicit attribute. Conflicting declarations fail during startup.

Read values with:

```python
from community_base.config import get, is_enabled

client_id = get("ZOOM_CLIENT_ID")
feature_on = is_enabled("FEATURE_ENABLED")
```

## Resolution and cache

Resolution order is:

1. typed database override;
2. the declared environment variable;
3. the explicitly declared Django setting fallback;
4. the registry default, or the call-specific default supplied to `get`.

Web processes cache database values in memory and compare a stamp in Django's default cache on
each lookup. A successful write publishes a new opaque stamp after commit, so other readers reload.
Deployments should configure the default cache as a process-shared backend. Django-Q workers bypass
the in-process value cache and read the database directly. Missing tables during bootstrap fall
through safely to the other layers.

## Storage and audit

`Setting` stores typed JSON values. Secret definitions are encrypted with Fernet using a
purpose-specific key derived from Django's `SECRET_KEY`; plaintext is never stored. Every write
creates a `SettingChange` containing the actor, reason, source, and old/new values. Secret audit
values are always `[REDACTED]`.

`service.export()` returns every declared key and masks all secrets. `service.import_()` updates an
object atomically and skips masked secret placeholders, so an export can be restored without
destroying existing credentials.

## Studio and API

Staff users edit groups at `/studio/settings/`, see a source badge for every value, and can import
or export JSON. Secret fields render empty and preserve the stored value when left blank.

API routes are registered under `/api/v1/settings`:

| Method and path | Scope | Purpose |
|---|---|---|
| `GET /settings` | `settings.read` | paginated definitions and effective values |
| `GET /settings/{key}` | `settings.read` | one definition and effective value |
| `PUT /settings/{key}` | `settings.write` | validate and store one override |
| `GET /settings/export` | `settings.read` | masked JSON export |
| `POST /settings/import` | `settings.write` | atomic JSON import |

List, detail, export, audit, and error responses never contain secret plaintext.
