# Kernel

The kernel contains the model-free settings, hooks, access, execution-context, redaction,
idempotency and service contracts used by all shared apps.

## `COMMUNITY_BASE` settings

| Key | Type | Default |
|---|---|---|
| `SITE_KEY` | `str` | `""` |
| `ACCESS_POLICY` | dotted path or policy object | `"community_base.kernel.access.OpenPolicy"` |
| `JOBS_BACKEND` | `str` | `"sync"` |
| `MAIL_BACKEND` | `str` | `"memory"` |
| `MAIL_PREFERENCE_RESOLVER` | dotted path or callable | `"community_base.mail.preferences.allow_all"` |
| `MAIL_SEND_RECORDER` | dotted path, callable or `None` | `None` |
| `MAIL_TEMPLATE_DIR` | path or `None` | `None` |
| `MAIL_TEMPLATE_OVERRIDE_LOADER` | dotted path, callable or `None` | `None` |
| `MAIL_UNSUBSCRIBE_URL_BUILDER` | dotted path, callable or `None` | `None` |
| `RELAY_API_KEY` | `str` | `""` |
| `RELAY_BASE_URL` | `str` | `""` |
| `RELAY_WEBHOOK_SECRET` | `str` | `""` |
| `SITE_URL` | absolute URL | `""` |
| `STUDIO_TITLE` | `str` | `"Community Studio"` |

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
