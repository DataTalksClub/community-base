# Kernel

The kernel contains the model-free settings, hooks, access, execution-context, redaction,
idempotency and service contracts used by all shared apps.

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
