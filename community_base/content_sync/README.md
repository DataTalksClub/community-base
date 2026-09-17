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

## Reading a repository: the document toolkit

`community_base.content_sync.documents` is the reading half of the format. It turns a checkout plus
its `content.yaml` into validated `ParsedDocument` values, and a parser uses it instead of walking
files, parsing YAML or validating keys of its own:

```python
from community_base.content_sync.documents import read_repository

result = read_repository(checkout)  # a directory path works too
if not result.ok:
    for diagnostic in result.errors:
        log.error(diagnostic.render())
for document in result.by_kind("wiki"):
    upsert(document)
```

`read_repository` never raises on a malformed repository. Every violation it finds is one
`Diagnostic` naming the file, a YAML pointer into it and the rule number in `FORMAT.md`, and the
walk continues, so one pass reports every problem a collection has rather than the first.

`ReadResult` carries `manifest`, `documents`, `diagnostics` and the helpers `ok`, `errors`,
`by_kind`, `by_part` and `by_path`.

`ParsedDocument` fields:

| Field | Meaning |
|---|---|
| `collection` | the `content.yaml` entry this item came from: its kind, path and index |
| `part` | the `PartSpec` the file was read against; a simple kind has one, `course` has five |
| `raw` | what the layout found: the repository path, the container, the name and the parent |
| `content` | the file as it parsed: the front-matter mapping, the manifest mapping, or a `data` file's value untouched |
| `data` | the declared mapping, or `{}` for a `data` file that is not a mapping |
| `values` | `data` with the registry's defaults filled in; a key with no default stays absent |
| `body` | the markdown after the front matter, unrendered; `""` for a manifest |
| `body_line` | the one-based line the body starts on, for a diagnostic |
| `slug` | section 3.4: the declared slug, else the name with its ordering prefix removed |
| `sort_order` | section 3.4: the declared value, else the `NN-` prefix of the name, else `0` |
| `required_level` | section 3.3: the declared level, else the parent item's, else `0` |
| `path` | the chain of ancestor slugs below the collection root; for `data`, the file path without its extension |
| `is_document` | whether the file was a `.md` document rather than a manifest |
| `checksum` | sha256 over the whole derived record, not over the file bytes |

Derived, not stored: `kind`, `source_path`, `content_id`, `title`, `sort_key` and `key`.

The checksum covers `record()`, which is where the item sits, what it derived and what it holds.
Two files with the same bytes in different places are two records and have two checksums, so a
consumer sees a move or a rename as a change.

`content.yaml` keys, all of section 3.1:

| Key | Type | Required | Default | Rule |
|---|---|---|---|---|
| `schema_version` | integer | yes | none | must equal `1` |
| `collections` | list | yes | none | at least one entry |
| `collections[].kind` | string | yes | none | a kind registered in the package or by the site |
| `collections[].path` | string | yes | none | repository-relative directory; `.` is the whole repository and then no other collection may be declared; two collections never nest |
| `ignore` | list of globs | no | `[]` | `PurePosixPath.full_match` syntax against repository-relative paths; a matched file is invisible to every collection, assets included |
| `strict_references` | boolean | no | `true` | `false` degrades an unresolved reference to a warning |
| `theme_pairs` | boolean | no | `false` | `true` pairs a `name.dark.ext` sibling with `name.ext` |

An unknown top-level key in `content.yaml` is an error. Files outside every collection path are
ignored rather than errors.

The toolkit ships the reading half only. Asset upload, reference resolution and the rendered HTML
are `C7.9b`; the package parsers that consume `ParsedDocument` are `C7.9c` and `C7.10`.

## Checking a repository

```text
uv run python -m community_base.content_sync.check <path>
uv run python manage.py check_content <path>
```

Both entry points call `check.run_check`, need no database and exit non-zero on any error.
`run_check` reads the repository through `documents.read_repository` and adds sections 3.6, 3.7
and 4.1 to what the toolkit already reported, so the validator and a parser cannot disagree
about a manifest, a key, a slug, the nesting or an identity. Each
diagnostic names the repository-relative file, a YAML pointer into it (`/` is the whole file) and
the rule number in `FORMAT.md`:

```text
articles/no-id/index.md:/content_id: [3.3] required key content_id is missing
wiki/liquid.md:12:/body: [4.1] Liquid is not part of the dialect: {% include x.html %}
```

The module form knows the package kinds only; pass `--kinds <dotted.module>` (repeatable) to import
a module that registers a site kind. The management command needs no flag, because the site's apps
have already registered them.

## Rendering

`rendering.py` is the one renderer and the one sanitiser for synced content (`FORMAT.md`
section 4.2). A second markdown path or a second allowlist is a defect, not an extension point.

| Name | What it does |
|---|---|
| `render_document(body, title="")` | the whole pipeline; returns `html`, `headings` and search `text` |
| `render_markdown(text)` | the same pipeline when only the HTML is wanted |
| `inject_heading_ids(html)` | adds the ids and returns the heading list |
| `sanitize_rendered_html(html)` | the one nh3 allowlist, for HTML a parser rendered itself |
| `plain_text(html)` | the search text of rendered HTML |
| `strip_leading_title_h1(body, title)` | drops a leading H1 that repeats the title |

The order is render, inject heading ids, sanitise. Sanitising is always last, so nothing an
extension emits reaches storage unchecked, and it is idempotent, so re-saving stored HTML leaves it
byte for byte alone.

The dialect is python-markdown with `fenced_code`, `tables` and `sane_lists`, plus the package
`mermaid` and `embed` fences. `attr_list` and `md_in_html` are not enabled, so a kramdown attribute
list is inert text the validator rejects.

Heading ids use the DataTalks.Club algorithm: NFKD, ASCII, lowercase, non-alphanumerics to `-`, an
empty result becoming `section`, and a repeat suffixed by the number of times the id was already
seen. Three `Setup` headings give `setup`, `setup-1`, `setup-2`. `check.py` assigns ids with the
same `HeadingIdAssigner`, so the fragment the validator accepts is the fragment the page carries.

`COMMUNITY_BASE["MARKDOWN_EXTENSIONS"]` is a list of dotted paths appended to the package extension
list. A site extends; it never replaces. An extension's output still passes the package sanitiser,
so an extension that needs a new attribute needs a package change to the allowlist.

Models store what they are given: `curriculum.Unit` and `knowledge_base.KnowledgeBasePage` both
carry `body_html_source`, and at `site` their `save()` sanitises the supplied HTML instead of
rendering markdown.

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
