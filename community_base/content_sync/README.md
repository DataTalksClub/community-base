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

## Content format and kind registry

`FORMAT.md` in this directory is the normative content format, version 1 (decision D23): the
`content.yaml` repository manifest, the two file shapes, the core keys, naming and identity,
nesting, assets, cross-references, the kind registry and the markdown dialect. A content repository
is checked against that file and against nothing else.

`community_base.content_sync.kinds` registers the kinds that enforce it. The package owns `course`,
`article`, `person`, `wiki`, `docs` and `data`. A site registers its own from `AppConfig.ready()`,
the way it registers a parser:

```python
from community_base.content_sync.kinds import KeySpec, KindSpec, register_kind
from community_base.content_sync.kinds.layouts import ItemDirectoryLayout

register_kind(
    "workshop",
    KindSpec(
        name="workshop",
        shape="manifest",
        layout=ItemDirectoryLayout(part="workshop", document="workshop.yaml"),
        keys={"instructors": KeySpec("reference_list", reference_kind="person")},
        requires_date=True,
        route=lambda path: f"workshops/{path}",
    ),
)
```

A kind declares its file shape, its layout, its keys with type, required flag and default, which
keys are asset references, which are typed references, the kinds it depends on, and a route
resolver. A kind may add keys; it may never remove, rename or retype a core key, and `register_kind`
refuses a specification that tries. `extra` is the only site escape hatch.

`kind_order()` returns the registered kinds in dependency order: a kind depends on the kinds its
reference keys name, or on the list it declares in `depends_on` when body references make the
derivation incomplete. Ordering sources by the kinds their collections declare is what `C7.9b` uses
instead of a hand-written list.

## Checking a repository

```text
uv run python -m community_base.content_sync.check <path>
uv run python manage.py check_content <path>
```

Both entry points call `check.run_check`, need no database and exit non-zero on any error. Each
diagnostic names the repository-relative file, a YAML pointer into it (`/` is the whole file) and
the rule number in `FORMAT.md`:

```text
articles/no-id/index.md:/content_id: [3.3] required key content_id is missing
wiki/liquid.md:12:/body: [4.1] Liquid is not part of the dialect: {% include x.html %}
```

The module form knows the package kinds only; pass `--kinds <dotted.module>` (repeatable) to import
a module that registers a site kind. The management command needs no flag, because the site's apps
have already registered them.

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
