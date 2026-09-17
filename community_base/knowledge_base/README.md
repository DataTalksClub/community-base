# Knowledge base

Wiki pages and documentation pages for both sites. This app owns storage,
hierarchy resolution, rendering, the search corpus and the Studio screens.
Sites own the parsers that fill it and the public templates that render it
(decision D16); the public templates shipped here are overridable defaults
(decision D18).

## Model

`KnowledgeBasePage` (app label `cb_knowledge_base`) carries `section`
(`wiki` or `docs`), `slug`, `title`, `summary`, `body`, rendered
`body_html` with its `body_html_source`, `record`, `public_path`,
`parent` (documentation tree only), `nav_order`, `status`
(`draft`/`published`) and the shared `content_sync` provenance fields,
all-or-nothing through `cb_kb_page_source_complete`.

A wiki page is a flat, standalone page: `parent` must stay null. A
documentation page may point at another documentation page through
`parent`; the explicit parent link is the only ancestry input -- URL
segments and titles are never used to guess a parent.

## What the site owns

Four contract points let a site keep its own identity, routes, rendering
and record shape without a second set of models.

| Point | Field | Default when the site does not use it |
|---|---|---|
| Page key | `slug`, unique per `(section, parent)` | a section whose slugs happen to be unique behaves as before |
| Public path | `public_path`, nullable | null: `get_absolute_url` builds the path from the ancestor chain |
| Rendering | `body_html_source` plus supplied `body_html` | `markdown`: the app renders `body` and sanitizes the result |
| Record metadata | `record`, a JSON object | `{}` |

### Page key

`slug` is the page's key among its siblings, unique per
`(section, parent)`. A leaf segment may repeat under different parents:
the DataTalks.Club documentation tree carries `project` seven times. Two
conditional unique constraints enforce it, because a NULL parent does not
compare equal to itself in a unique index: `cb_kb_page_child_slug_unique`
covers the rows that have a parent and `cb_kb_page_root_slug_unique` the
root of each section.

A segment is letters, digits, dots, dashes or underscores. A slug may be
several segments joined by `/`, with no leading, trailing or doubled
slash, so a site whose page identity is the whole path (a source path
without its extension) can store the path instead of the leaf.

### Public path

`public_path` is the site's own root-relative URL for the page
(`/docs/course-a/module-1/project/`). `get_absolute_url` returns it
verbatim when set; left null it builds `/<section>/<ancestor slugs>/<slug>/`
from the tree, which is what a site that mounts the default routes wants.
Non-null paths are unique: two pages cannot answer at one URL. An empty
string is stored as null.

A site that derives its paths from source files and its tree from
front-matter parents (DataTalks.Club does both) stores both independently.

### Rendering

`body_html_source` says who rendered the page. At `markdown`, the default,
`save` renders `body` with `rendering.render_markdown`. At `site`, `save`
stops rendering and keeps the supplied HTML, which is what a site with its
own pipeline (mistune, liquid preprocessing, injected heading ids) needs.

Set it with `page.set_site_rendered_html(html)` or by passing `body_html`
to `sync.upsert_page`. Supplied HTML is not trusted: every save puts it
through `rendering.sanitize_rendered_html`. Sanitizing is idempotent, so a
re-save leaves stored HTML byte for byte alone.

### Record

`record` is one JSON object of site-owned, section-shaped metadata. The
package stores and returns it and never reads a key of it, ships no field
for one and adds no per-site column, so two sites with different record
shapes share one model. DataTalks.Club wiki pages put `blocks`, `tags`,
`fragment_ids`, `unresolved_fragment_ids` and `relations` there; its
documentation pages put `edit_url`, `has_toc`, `has_children`,
`permalink`, `grand_parent`, `body_sha256` and the declared `images`.

It must be a JSON object, so a site can always add a key to what is
already stored.

## Parser contract

Sites register their own `content_sync` parsers
(`community_base.content_sync.parsers.register_parser`) and call, per item:

- `sync.upsert_page(source, *, section, slug, title, body="", summary="",
  parent_slug=None, parent_path=None, nav_order=0, public_path=None,
  body_html=None, record=None, commit_sha, source_path, checksum)`
  creates, updates or leaves unchanged one page and returns
  `(page, action)`. `checksum` is the change signal: fold everything the
  record derives from (including the resolved parent) into it. The parent
  must already exist within the section, so `discover` returns parents
  before children. Unknown sections, wiki parents and cycles raise
  `KnowledgeBaseSyncError`. An empty `commit_sha` (a from-disk checkout
  with no git commit) is replaced by a stable value derived from the
  source path and checksum.
- Name the parent with `parent_slug` when the section's slugs are unique;
  a slug that names more than one page is refused rather than guessed.
  Name it with `parent_path` -- the slug chain from the section root,
  `"course-a/module-1"` -- when leaf slugs repeat. Passing both is an error.
- The row an item owns is `(section, parent, slug)`. A page whose parent
  changed is matched by its source file under the same source and updated
  in place, not duplicated.
- `public_path`, `body_html` and `record` are the site-owned inputs above.
  A parser that omits one leaves the page on the app's default for it, and
  a parser that stops passing one returns the page to that default: the
  parser owns the whole record.
- `sync.delete_missing(source, section, seen_slugs)` drafts this source's
  published pages of the section that the repository no longer lists.
  Rows from other sources, and Studio-authored rows (no provenance), are
  never touched. For a section whose leaf slugs repeat, where a slug
  identifies no single page, pass `seen_source_paths=` instead of
  `seen_slugs`; exactly one of the two.

A working example lives in `tests/knowledge_base/fixture_parser.py`.

## Rendering

`rendering.render_markdown` renders a page body on save and sanitizes the
result. The allowlist is lifted from DTC's
`content/services.py:sanitize_rendered_html` (tags, attribute rules, URL
protocols) onto `nh3`; one deliberate extension: an `img src` may also be
an absolute `http(s)` URL, so a site's CDN images render. `class`, `id`,
`lang` and `title` survive on any allowed tag, which is what carries a
site's heading anchors; `style`, `data-*`, event handlers, `javascript:`
links and unadmitted image sources do not.

A site that renders the page itself hands the result to the app
(`set_site_rendered_html`, or `body_html=` on `upsert_page`) rather than
sanitizing separately: every stored body passes the one code-owned
sanitizer on every save.

## Hierarchy and search

- `hierarchy`: `navigation_tree(section)` returns a validated tree with a
  deterministic depth-first preorder; siblings order by `nav_order`, then
  title, then slug. Index it by `by_pk`; `by_slug` is a convenience for a
  section whose slugs are unique and holds only one page of a repeated
  slug. Also `wiki_pages()` (flat, A-Z by title), `children_of`,
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
