# Content sync

`community_base.content_sync` synchronizes authored files from GitHub into site-owned models through
registered parsers. The package owns checkout security, locking, job dispatch, webhooks, audit
logs, media upload, API routes and Studio operations. Sites own content models and parsers.

## Installation

Add these apps after the kernel and durable jobs apps:

```python
INSTALLED_APPS = [
    "community_base.kernel",
    "community_base.api",
    "community_base.jobs",
    "community_base.studio",
    "community_base.content_sync",
]
```

Mount the public webhook and staff routes:

```python
urlpatterns = [
    path("api/v1/", include((api_urlpatterns(), "cb_api"))),
    path("content-sync/", include("community_base.content_sync.urls")),
    path("studio/", include("community_base.studio.urls")),
    path("studio/", include("community_base.content_sync.studio_urls")),
]
```

Run migrations and seed the declared sources:

```text
uv run python manage.py migrate
uv run python manage.py seed_content_sources
```

## Parser contract

Register parsers during app startup with `register_parser(content_type, parser)`. A parser exposes:

- `discover(checkout, source)` returning `SourceItem` values;
- `upsert(item, source, media)` returning an object or `UpsertResult`;
- `soft_delete_missing(seen_keys, source)` returning deleted objects or a count.

The checkout is a read-only manifest snapshot. Read files through `checkout.read_bytes()` or
`checkout.read_text()`; never reopen the source repository. Parsers scope every lookup and soft
delete to the supplied source. A parser failure produces a partial sync and does not prevent other
registered content types from running.

## Configuration

Declare source dictionaries in `COMMUNITY_BASE["CONTENT_SOURCES"]`. Each needs `slug`,
`repo_name` in `owner/repository` form and `webhook_secret`. Optional fields are `is_private`,
`is_enabled` and `max_files`.

Private repositories require `CONTENT_SYNC_GITHUB_APP_ID`,
`CONTENT_SYNC_GITHUB_INSTALLATION_ID` and `CONTENT_SYNC_GITHUB_PRIVATE_KEY`. GitHub API URL,
timeout and archive bounds have safe defaults listed in the kernel README.

Media is unchanged by default. Set `CONTENT_SYNC_MEDIA_BACKEND` to `s3`, install the `s3` extra,
and configure `CONTENT_SYNC_S3_BUCKET`. Region, object-key prefix and public base URL are optional.
AWS credentials use the standard boto3 credential chain and are not package settings.

## Operations

- `sync_content [--source SLUG] [--from-disk PATH] [--force]` runs synchronously.
- The GitHub webhook is `/content-sync/github/webhook/` and requires `X-Hub-Signature-256`,
  `X-GitHub-Delivery` and `X-GitHub-Event`.
- Durable handler `cb_content_sync.sync_source` is chunked as one job per source.
- Studio routes provide source edit, manual sync, history and worker status.
- API scopes are `content_sync.read` and `content_sync.write`; source secrets and raw parser errors
  are never returned.

Successful remote syncs persist the exact 40-character commit. Repeated successful commits are
skipped unless forced. Concurrent attempts set a follow-up request on the source lock, and the
active sync dispatches that request after releasing the lock.
