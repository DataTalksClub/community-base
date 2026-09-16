# Knowledge base

Wiki pages and documentation pages for both sites. This app owns storage,
hierarchy resolution, rendering, the search corpus and the Studio screens.
Sites own the parsers that fill it and the public templates that render it
(decision D16); the public templates shipped here are overridable defaults
(decision D18).

## Model

`KnowledgeBasePage` (app label `cb_knowledge_base`) carries `section`
(`wiki` or `docs`), `slug` (unique per section, dots allowed), `title`,
`summary`, `body`, rendered `body_html`, `parent` (documentation tree only),
`nav_order`, `status` (`draft`/`published`) and the shared `content_sync`
provenance fields, all-or-nothing through `cb_kb_page_source_complete`.

A wiki page is a flat, standalone page: `parent` must stay null. A
documentation page may point at another documentation page through
`parent`; the explicit parent link is the only ancestry input -- URL
segments and titles are never used to guess a parent.

## Parser contract

Sites register their own `content_sync` parsers
(`community_base.content_sync.parsers.register_parser`) and call, per item:

- `sync.upsert_page(source, *, section, slug, title, body="", summary="",
  parent_slug=None, nav_order=0, commit_sha, source_path, checksum)`
  creates, updates or leaves unchanged one page and returns
  `(page, action)`. `checksum` is the change signal: fold everything the
  record derives from (including the resolved parent) into it. The parent
  must already exist within the section, so `discover` returns parents
  before children. Unknown sections, wiki parents and cycles raise
  `KnowledgeBaseSyncError`. An empty `commit_sha` (a from-disk checkout
  with no git commit) is replaced by a stable value derived from the
  source path and checksum.
- `sync.delete_missing(source, section, seen_slugs)` drafts this source's
  published pages of the section that the repository no longer lists.
  Rows from other sources, and Studio-authored rows (no provenance), are
  never touched.

A working example lives in `tests/knowledge_base/fixture_parser.py`.

## Rendering

`rendering.render_markdown` renders a page body on save and sanitizes the
result. The allowlist is lifted from DTC's
`content/services.py:sanitize_rendered_html` (tags, attribute rules, URL
protocols) onto `nh3`; one deliberate extension: an `img src` may also be
an absolute `http(s)` URL, so a site's CDN images render. A site whose
parser renders blocks itself runs the produced HTML through
`rendering.sanitize_rendered_html` so every stored body passes one
code-owned sanitizer.

## Hierarchy and search

- `hierarchy`: `navigation_tree(section)` returns a validated tree with a
  deterministic depth-first preorder; siblings order by `nav_order`, then
  title, then slug. Also `wiki_pages()` (flat, A-Z by title), `children_of`,
  `breadcrumbs`, `sequential_navigation`, `sibling_navigation`,
  `published_pages`. A published page under a draft parent renders as a
  top-level page; a parent cycle raises `ImproperlyConfigured`.
- `search`: `search_pages(query, section=None, limit=100)` (terms ANDed,
  case-insensitive, over title, summary and plain-text body),
  `search_corpus(section=None)`, `corpus_stamp()` for cache keys. Search is
  a service; the package ships no search view, feed, sitemap or robots
  output -- those stay site-shaped.

## Studio

Read-only inspection screens under Studio, section "Knowledge base"
(`/studio/knowledge-base/`): a list with section and query filters, and a
detail page showing tree position, provenance and rendered body.

## Public routes and template overrides

Default routes a site may mount (the test project mounts them at `/`):

| Route | Name | Template |
|---|---|---|
| `/wiki/` | `knowledge_base:wiki_home` | `knowledge_base/wiki_home.html` |
| `/wiki/<slug>/` | `knowledge_base:wiki_page` | `knowledge_base/page_detail.html` |
| `/docs/` | `knowledge_base:docs_home` | `knowledge_base/docs_home.html` |
| `/docs/<path:page_path>/` | `knowledge_base:docs_page` | `knowledge_base/page_detail.html` |

A site overrides a template by placing a file at the same path under its
own `templates/` directory (Django `DIRS` before `APP_DIRS`). The shipped
templates extend the site's `base.html` and use only the shared `cb-` class
hooks. A site may also skip these routes entirely and serve the rows from
its own views and templates.

## Settings keys

None. The app reads no `COMMUNITY_BASE` keys and declares none.

## Tests

`uv run pytest tests/knowledge_base`
