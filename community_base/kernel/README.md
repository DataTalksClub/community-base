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
| `STUDIO_TITLE` | `str` | `"Community Studio"` |

Site settings override only the keys they need:

```python
COMMUNITY_BASE = {
    "SITE_KEY": "dtc",
    "ACCESS_POLICY": "community_base.kernel.access.RegisteredOnlyPolicy",
    "JOBS_BACKEND": "relay",
    "MAIL_BACKEND": "relay",
    "STUDIO_TITLE": "DataTalks.Club Studio",
}
```

Unknown keys requested through `community_base.kernel.conf.get` raise
`django.core.exceptions.ImproperlyConfigured`.
