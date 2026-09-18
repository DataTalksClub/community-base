# Phase 7: site convergence

Goal: integrate the two sites where integration is worth it. Phases 0 to 6 move capabilities that
both sites already had into the package. This phase decides the remaining cases, where one site has
a capability the other does not, or where the two solved the same problem differently, and either
brings both onto one implementation or records that the difference stays.

The phase carries two bodies of work. The convergence issues (`C7.1` to `C7.6`, `C7.13`, `C7.14`,
`A7.1`, `D7.1`) settle one capability each. The content-format issues (`C7.7` to `C7.12`, then
`A7.2`, `D7.2`, `D7.3`, `A7.3`, `D7.4`) replace sixteen content repositories' file shapes, two
classifiers and five parsers with one declared format and one toolkit.

Source: `docs/plan/evidence/site-convergence-analysis-2026-09-16.md` for the convergence issues,
`docs/plan/evidence/unified-content-format-2026-09-17.md` for the content-format issues. Decisions
D16 to D31.

`docs/plan/evidence/unified-content-format-2026-09-17.md` is the normative document for `C7.7` to
`C7.12` and for the five site issues that adopt them. Its sections 3 and 4 are the format; section
5 is the per-repository conversion cost; section 6 is the findings that make the work urgent;
section 7 is the breakdown these issues expand. Where an issue below is shorter than the
specification, the specification governs the detail and the issue governs the scope of its pull
request. An issue never defers its own verification to the specification.

Freeze: no production freeze. No issue here moves a production table between sites. Two issues take
a content freeze instead: `A7.3` and `D7.4` freeze writes on the content repositories they convert,
one day per repository, because a conversion rewrites every file in the repository.

Depends on: 5 for the shared curriculum and coursework apps. The knowledge-base issues depend only
on the content sync engine and can start once `C7.1` fixes their shape. `C7.7` depends on nothing
and can start now.

Exit criteria:

- Both sites serve a wiki and a documentation section from the same package app, with site-owned
  parsers and site-owned public templates.
- The candidate table in `C7.1` has no row left in state `undecided`.
- No shared app carries a legacy path, alias or redirect model (decision D17).
- One content format is specified in the package, enforced by `check_content`, and read by one
  toolkit; `parsers_aisl.py` and `parsers_dtc.py` no longer exist.
- Every content repository of both sites syncs from its default branch with zero errors.

## C7.1 Site convergence umbrella

Repository: community-base. Depends on: nothing.

Goal: one place that records, for every capability the two sites do not share today, whether it
converges, stays site-owned, or is still undecided. This issue owns the table, not the code. Each
accepted row becomes its own issue.

This is an index issue. It closes when every row is `accepted` with a sub-issue, or `site-owned`,
and none is `undecided`. A `deferred` row is decided, not open.

Read first
- `docs/plan/evidence/site-convergence-analysis-2026-09-16.md`, sections 4 and 5.
- `docs/plan/evidence/unified-content-format-2026-09-17.md`, sections 2 and 6, for the content
  rows.
- `docs/01-decisions.md`, D16 to D31.

Candidate table

| Capability | Today | Proposal | State | Issue |
|---|---|---|---|---|
| Wiki | DTC only | shared package app, site parsers and templates | accepted, D16 | `C7.2`, `A7.1`, `D7.1` |
| Docs section | DTC only | shared package app, same as wiki | accepted, D16 | `C7.2`, `A7.1`, `D7.1` |
| Event aliases and legacy paths | package and DTC had them | remove, no legacy compatibility | accepted, D17 | `C4.1e` |
| Calendly Studio surfaces | package shows them when `CALENDLY` is false | gate Studio like the public views | accepted | `C7.3` |
| Public design systems | one per site | stays per site, never shared | site-owned, D18 | none |
| Capability declaration for Studio and admin API | DTC has 46, AISL has none | converge only the generic mechanism, after reconciling it with the two existing package registries | deferred, D22 | none |
| Optimistic concurrency and append-only model bases | DTC only | move `RevisionedModel` and `AppendOnlyManager` into the kernel | accepted, D19 | `C7.5` |
| Custom session model | AISL only | move `AccountSession` into package `accounts` | accepted, D20 | `C7.6` |
| Article storage shape | AISL concrete model, DTC synced document | each site keeps its own shape; the shared part, the sync engine, is already unified | site-owned, D21 | none |
| Content format and importer | DTC has nine parsers over Jekyll-shaped files, AISL has a 391-line classifier over its own shapes | one declared format, one repository manifest, one parser toolkit | accepted, D23 | `C7.7` to `C7.12` |
| Markdown dialect and sanitiser | DTC mistune with kramdown and Liquid preprocessing and bleach, AISL python-markdown with nh3 | one dialect, one sanitiser, rendered once at sync | accepted, D23 | `C7.8` |
| Course parser | the package carries two, and section 6 of the format document shows neither reads the live repositories | one parser over the declared layout, both donors deleted | accepted, D23 | `C7.10` |
| Parsers for the wiki, docs and person kinds | each site writes its own | the package owns them because the package owns their storage; amends the parser clause of D16 | accepted, D24 | `C7.9c` |
| Course entitlement keys | AISL has `access_mode`, `enroll_url`, `program_label`, `maven_course_key`; DTC has none | stay AISL-only `extra` keys until a second program needs them | site-owned, D29 | none |
| Podcast, FAQ, people, sponsors, event Q and A | DTC only | stays DTC-owned unless the owner asks | site-owned | none |
| Payments, sprint plans, CRM, book club, analytics, triggers | AISL only | stays AISL-owned | site-owned | none |

Steps
1. Keep the table current. A row moves to `accepted` only with an owner decision recorded in
   `docs/01-decisions.md`.
2. When a row is accepted, add its issues to this phase, run `python scripts/plan.py sync`, and put
   the issue ids in the row.
3. Mirror this issue in each site repository only when that site has an accepted row.

A row in state `deferred` is decided, not open: the owner has ruled that it does not converge now
and recorded why. It does not hold this issue open.

Done when
- [x] no row is in state `undecided` -- the last four were settled by D19 to D22 and D29 on
      2026-09-17, and D22 records `deferred` as a decided state rather than an open one
- [x] every `accepted` row names at least one issue that is `done` -- wiki and docs through C7.2,
      event aliases through C4.1e, Calendly through C7.3, the kernel model bases through C7.5, the
      session record through C7.6, the content format through C7.7, the dialect through C7.8, the
      course parser through C7.10, and the wiki, docs and person parsers through C7.9c

Docs
- `docs/plan/phase-7.md`, `docs/01-decisions.md`.

## C7.2 Shared knowledge base app: wiki and docs

Repository: community-base. Depends on: C2.4. Decision D16.

Goal: one package app that owns wiki pages and documentation pages: models, hierarchy, rendering,
search corpus and Studio screens. Sites own the parsers that fill it and the public templates that
render it.

Read first
- `~/git/dtc-website/content/wiki_content.py`, `docs_projection.py`, `docs_presentation.py`,
  `content/sync_parsers/podwiki.py`, `content/sync_parsers/docs.py`.
- `~/git/dtc-website/core/graph_layout.py` for the knowledge graph, which stays DTC-owned for now.
- `community_base/content_sync/parsers.py` for the parser contract the app builds on.

Steps
1. Add the app with a page model carrying slug, title, body, rendered HTML, a parent reference for
   the documentation tree, navigation order, and the `content_sync` provenance mixin already used
   by `curriculum`.
2. Lift DTC's hierarchy resolution (`parent`, `nav_order`, `has_children`) and its sanitizer use.
   Reuse `content/services.py:sanitize_rendered_html`'s allowlist, do not invent a second one.
3. Provide the search corpus as a service, not a view. DTC's feed, sitemap and robots output stay
   site-owned because they are site-shaped.
4. Ship Studio list and detail screens registered through the Studio registry.
5. Leave the knowledge-graph projection out. It is one site's feature and has no second consumer;
   revisit only if AISL asks for it.
6. Publish no public templates beyond overridable defaults, per D18.

Verification
- Fresh-database migrations and the new app's tests pass.
- `uv run python -m pytest tests/` passes, boundary test included.
- A fixture parser feeding the app produces a two-level documentation tree and a flat wiki set.

Done when
- [ ] the app renders a wiki page and a nested documentation page from synced rows
- [ ] no import from either site, enforced by `tests/test_boundaries.py`
- [ ] README documents the parser contract, the settings keys and the template override points

Docs
- new app README, `docs/02-architecture.md`, `CHANGELOG.md`.

## D7.1 DTC wiki and docs onto the shared app

Repository: DataTalksClub/website. Depends on: C7.2, C7.4. Decision D16.

Goal: DTC keeps its wiki and documentation exactly as they are for readers, served by the package
app instead of `content`'s own projections.

Blocked until C7.4 ships: the released `knowledge_base` app cannot store DTC's documentation tree
or wiki bodies. Evidence, with file-level citations:
`docs/plan/evidence/d71-knowledge-base-gap-2026-09-17.md`.

Read first
- DTC `AGENTS.md` and `_docs/PROCESS.md` first; they govern the work.
- `content/sync_parsers/docs.py` and `podwiki.py`, the two parsers that move.
- `content/catalogue.py` (the wiki read model) and `content/docs_projection.py` (the docs read
   model). These are the projections that move.
- `content/route_contracts.py` and `content/sitemap_contract.py`, the pinned inventories.

Steps
1. Point `content/sync_parsers/podwiki.py` and `docs.py` at the package app's models.
2. Keep the public routes, templates and the knowledge graph in `content`. Only the storage and
   hierarchy resolution move.
3. Verify the pinned route inventories in `content/route_contracts.py` and `sitemap_contract.py`
   are unchanged. A moved page is a regression, not an improvement.
4. Remove `content/docs_projection.py` and the wiki read path in `content/catalogue.py` once the
   routes are green. `content/wiki_content.py` and `content/docs_presentation.py` STAY: the first
   is the knowledge graph (`episode_graph`, `graph_groups`, `graph_totals`), which step 2 keeps
   DTC-owned; the second is presentation (rails, hub, curriculum split, search snippets), which
   step 2 also keeps in `content`. An earlier revision of this issue listed both for removal; that
   was wrong.

Verification
- The route contract and sitemap contract tests pass unchanged.
- A development deploy serves `/docs/` and the wiki with the same paths as before.

Done when
- [ ] wiki and docs read from the package app
- [ ] no public path changed
- [ ] the superseded projection modules are gone

## A7.1 AISL gains wiki and docs

Repository: AI-Shipping-Labs/website. Depends on: C7.2. Decision D16.

Goal: AISL serves a wiki and a documentation section from the shared app, in AISL's own design.

Read first
- AISL `AGENTS.md` and `_docs/PROCESS.md` first; they govern the work.
- `content/sync_parsers/base.py` and `content/sync_parsers/families/` for how AISL registers a
  parser family.
- `templates/content/` for the reader layout the new pages should reuse.

Steps
1. Choose the content source. A section of an existing AISL content repository is enough; a new
   repository is not required by this issue.
2. Add two parser families, one for wiki pages and one for documentation pages, registered the way
   every other AISL family is.
3. Add public routes and templates in AISL's Tailwind design. Do not adopt DTC's markup.
4. Add the pages to the sitemap and to navigation availability.

Verification
- `make test-affected` passes; `scripts/affected_tests.py` selects the touched apps.
- A development deploy serves a wiki page and a nested documentation page.

Done when
- [ ] both sections render on a development deploy
- [ ] the pages are in the sitemap
- [ ] storage and hierarchy come from the package app, not from new AISL models

## C7.3 Gate Calendly Studio surfaces behind the Calendly flag

Repository: community-base. Depends on: nothing.

Goal: a site with `COMMUNITY_BASE["CALENDLY"]` false sees no Calendly surface anywhere, as the
public views already guarantee.

Read first
- `community_base/community/views.py` lines 52 and 68, the two working `Http404` guards.
- `community_base/community/studio_views.py`, which has no guard.
- `community_base/community/studio_registration.py` and `apps.py:ready`.

Steps
1. Guard `call_host_list`, `call_host_create`, `call_host_edit`, `booked_call_list` and
   `unmatched_call_list` the same way the public views are guarded.
2. Register the `community-call-hosts` and `community-booked-calls` destinations only when the flag
   is on. Leave the Slack access and audit destinations registered unconditionally.
3. Leave the models and migrations alone. Three unused tables on a site that does not use Calendly
   are the accepted cost of a shared app.

Verification
- With `CALENDLY` false, the Studio sidebar shows no Calendly destination and each of the five
  Studio routes returns 404.
- With `CALENDLY` true, both destinations appear and all five routes work.
- `uv run python -m pytest tests/community tests/studio` passes.

Done when
- [ ] no Calendly Studio surface appears when the flag is off
- [ ] a test covers both flag states

Docs
- `community_base/community/README.md`.

## C7.4 Knowledge base: site-owned page identity, rendering and record metadata

Repository: community-base. Depends on: C7.2. Freeze required: no. Decision D16.

Goal: the `knowledge_base` app can store DTC's documentation tree and wiki pages without DTC
inventing a second set of models. C7.2 built the app against AISL's needs (A7.1, done); the DTC
adoption issue D7.1 stopped on four capabilities the released app does not have. Evidence and
file-level citations: `docs/plan/evidence/d71-knowledge-base-gap-2026-09-17.md`.

Read first
- `community_base/knowledge_base/models.py`, `sync.py`, `rendering.py`, `README.md`.
- `community_base/content_sync/provenance.py` (`SourceProvenanceMixin`).
- `~/git/dtc-website/content/sync_parsers/docs.py` and `podwiki.py`, the two donor parsers.
- `~/git/dtc-website/content/docs_projection.py` and `content/catalogue.py`, the donor read models.
- `~/git/dtc-website/templates/public/wiki_detail.html`, which renders the wiki record fields.

The four gaps

| Gap | Today | Why it blocks DTC |
|---|---|---|
| Page key cannot hold a path | `SLUG_PATTERN = r"^[-a-zA-Z0-9_.]+$"` rejects `/`; `UniqueConstraint(("section", "slug"))` is per section, not per parent | DTC's docs identity is a slash path. Its pinned baseline has 167 multi-segment `/docs/...` paths with 15 repeated leaf segments (`project` seven times, `curriculum` six, `prerequisites` six), so neither the full path nor the leaf segment can be the slug |
| No stored public path | `get_absolute_url` derives the URL from the ancestor chain | DTC derives the path from the source file and resolves `parent` independently, by front-matter title. The app collapses two inputs into one |
| Rendering cannot be site-owned | `save()` unconditionally recomputes `body_html` with python-markdown; the field is `editable=False` | DTC renders with mistune plus kramdown and liquid preprocessing and heading-id injection, and returns heading metadata for the table of contents. There is no way to store site-rendered HTML |
| No record metadata field | only `body`, `body_html`, and the provenance columns | DTC wiki pages are not markdown: they carry `blocks`, `tags`, `fragment_ids`, `unresolved_fragment_ids` and `relations`, and the sync fails when a heading fragment does not resolve uniquely. Docs records carry `edit_url`, `has_toc`, `has_children`, `permalink`, `grand_parent`, `body_sha256` and declared `images` |

Steps
1. Give the page a parent-scoped or path-shaped key. Prefer widening the slug alphabet to accept
   `/` and moving the unique constraint to `("section", "parent", "slug")`, so a leaf segment stays
   the slug and the tree carries the path. Record which shape you chose and why.
2. Add a nullable site-owned public path, used by `get_absolute_url` when set and falling back to
   the ancestor chain when null, so AISL's existing behaviour (A7.1) is unchanged.
3. Make rendering site-ownable: keep `render_markdown` as the default, and let a caller supply
   already-rendered HTML that `save()` preserves instead of overwriting. Run supplied HTML through
   `rendering.sanitize_rendered_html`; do not trust it.
4. Add one JSON record field for section-shaped metadata, and document that the package does not
   interpret it. Do not add per-site columns.
5. Extend `sync.upsert_page` to carry the new inputs.

Verification
- `uv run pytest tests/knowledge_base` passes, boundary test included.
- A fixture parser stores a three-level documentation tree whose leaf slugs repeat across
   different parents, and reads each back at its own path.
- A fixture parser stores site-rendered HTML and it survives a `save()` untouched.
- Migrations apply from empty and each reverses.
- A7.1's behaviour is unchanged: existing pages with no public path and no supplied HTML render
   exactly as before.

Done when
- [ ] repeated leaf segments under different parents coexist
- [ ] a site can store its own rendered HTML and its own public path
- [ ] the record field round-trips the donor wiki and docs metadata
- [ ] no site import, enforced by `tests/test_boundaries.py`
- [ ] the app README documents all four new contract points

Docs
- `community_base/knowledge_base/README.md`, `docs/02-architecture.md`, `CHANGELOG.md`.

## C7.5 Kernel model bases: optimistic concurrency and append-only

Repository: community-base. Depends on: nothing. Freeze required: no. Decision D19.

Goal: the kernel offers the two model base classes DTC already relies on, so a shared app can use
optimistic concurrency without each site inventing it.

Read first
- `~/git/dtc-website/core/models.py` lines 16 to 114, the donor `RevisionedModel` and
  `AppendOnlyManager`.
- The eleven DTC models that inherit them, to see which behaviours are actually exercised.
- `community_base/kernel/`, which has no model base classes today, for where these belong.

Steps
1. Move the two bases into the kernel with their tests. The kernel is import-light: these must not
   drag in anything from another package app.
2. Keep the donor semantics exactly. A revision conflict must raise the same way it does today;
   do not redesign the exception or the retry contract while moving it.
3. Do not migrate DTC's eleven models here. They stay DTC-owned and adopt the kernel bases in
   their own site issue, so this issue ships no site change and no migration.
4. Document both in the kernel README, including the conflict exception a caller must handle.

Verification
- `uv run pytest tests/kernel` passes, boundary test included.
- A test proves a concurrent write raises the conflict rather than silently overwriting.
- `uv run pytest -q` does not regress.

Done when
- [ ] both bases live in the kernel with their donor semantics unchanged
- [ ] a concurrency test covers the conflict path
- [ ] the kernel README documents the conflict exception

Docs
- `community_base/kernel/README.md`, `docs/02-architecture.md`, `CHANGELOG.md`.

## C7.6 Accounts: queryable session record

Repository: community-base. Depends on: C3.1e. Freeze required: no. Decision D20.

Goal: the package accounts app owns a queryable session record, so a site can answer "which
sessions does this member have" without reading Django's opaque session table, and can erase them
on request.

Read first
- `~/git/ai-shipping-labs/accounts/models/session.py` and `accounts/session_backend.py`, the
  donor, about fifty lines together.
- Its two real call sites: GDPR erasure and expired-session cleanup.
- `community_base/accounts/`, for where this belongs and what it may import.

Steps
1. Move the model and the session backend into the package accounts app. The backend is selected
   through `SESSION_ENGINE`, so a site opts in by setting it; installing the app must not change
   session behaviour on a site that does not.
2. Provide the two operations the donor call sites need as services: erase a member's sessions,
   and purge expired ones. Do not ship a management command that assumes a site's scheduler.
3. This is additive for both sites: AISL already has the donor table, DTC gains one. Record in the
   issue which of the two owns the kept-label migration question, and leave the migration
   provisional until the donor inventory is checked.

Verification
- `uv run pytest tests/accounts` passes, boundary test included.
- With `SESSION_ENGINE` unset, session behaviour is unchanged; a test covers both states.
- Migrations apply from empty and reverse.

Done when
- [ ] the model and backend live in the package accounts app
- [ ] opting out leaves Django's default session behaviour untouched, proven by a test
- [ ] erase and purge are services, not commands

Docs
- `community_base/accounts/README.md`, `docs/02-architecture.md`, `CHANGELOG.md`.

## C7.7 Content format: specification, kind registry and validator

Repository: community-base. Depends on: nothing. Freeze required: no. Decision D23.

Goal: the package states the content format normatively, registers the kinds that enforce it, and
can check a content repository against it without a database and without a site.

Filing this issue closes GitHub issue `DataTalksClub/community-base#253`. Issue 253 asked for one
content format and one importer across both sites; section 8 of the specification maps its five
stages onto this issue list and answers the three questions it put to the owner. Close 253 with a
link to the specification and to this issue; its remaining work is `C7.7` to `C7.12`.

Read first
- `docs/plan/evidence/unified-content-format-2026-09-17.md`, sections 3 and 4 in full. This issue
  implements them.
- `docs/01-decisions.md`, D23, D26, D27, D29 and D30, which settle the questions the specification
  left open.
- `community_base/content_sync/parsers.py`, for `register_parser`, the registry pattern the kind
  registry copies.
- `community_base/content_sync/provenance.py`, whose `SourceProvenanceMixin` docstring does not say
  what `source_content_id` holds.

Steps
1. Add `community_base/content_sync/FORMAT.md` carrying sections 3 and 4 of the specification as
   normative package text. That file is the contract a content repository is checked against.
2. Add `community_base/content_sync/kinds/` with `register_kind(name, spec)` and `get_kind(name)`,
   the core key schema of section 3.3, and the six package kinds `course`, `article`, `person`,
   `wiki`, `docs` and `data`.
3. A kind declares its file shape, its kind keys with type, required flag and default, which keys
   are asset references, which are typed references, and a route resolver. A kind never removes,
   renames or retypes a core key; `extra` is the only site escape hatch.
4. A site registers its own kinds from `AppConfig.ready()`, the same way it registers a parser.
5. Add `content_sync/check.py` and the `check_content` management command. It validates
   `content.yaml`, collection paths, file shapes, naming and ordering prefixes, identity
   uniqueness, asset resolution, in-repository references and the dialect rules of section 4.1.
6. `check_content` runs against a directory, needs no database, and exits non-zero on any
   violation. Every diagnostic carries the repository-relative path and a YAML pointer, never
   prose alone.
7. Fix the meaning of `source_content_id`. State in `FORMAT.md` section 3.4 and in the
   `SourceProvenanceMixin` docstring that it holds the item's own `content_id`.
   `community_base/curriculum/importing.py:265` already does that.
   `community_base/knowledge_base/sync.py:152` stores the `ContentSource` primary key instead, and
   `sync.py:120` scopes `delete_missing` by it. Both fields are `UUIDField`s, so the two meanings
   collide silently rather than failing. Record the contradiction in the docstring and in the pull
   request; the model repair is `C7.9c` step 2, because it needs a migration this issue does not
   carry.
8. Add fixture repositories under `tests/content_sync/fixtures/`: a single-course repository, a
   multi-collection repository, and a docs tree with leaf slugs repeated under different parents.

Verification
- `uv run pytest tests/content_sync` passes, with one failing fixture per rule in sections 3.1 to
  3.7.
- `uv run python -m community_base.content_sync.check tests/content_sync/fixtures/<name>` exits 0
  for each valid fixture, and non-zero with a path and a pointer for each invalid one.
- `uv run python manage.py check_content <path>` in the test project gives the same result as the
  module entry point for the same fixture.
- `uv run pytest tests/test_boundaries.py` passes; the kind registry imports no site code.
- `uv run pytest -q` does not regress.

Done when
- [ ] `FORMAT.md` carries sections 3 and 4 as normative package text
- [ ] the six package kinds are registered and documented
- [ ] a site can register a kind from `AppConfig.ready()` without touching the package
- [ ] `check_content` reports every violation of sections 3.1 to 3.7 with a path and a pointer
- [ ] the `source_content_id` contract is written down, and the knowledge base contradiction is
      recorded with `C7.9c` named as its repair
- [ ] issue 253 is closed with a link to the specification

Docs
- `community_base/content_sync/FORMAT.md` (new), `community_base/content_sync/README.md`,
  `docs/02-architecture.md`, `CHANGELOG.md`.

## C7.8 Shared rendering: one dialect, one sanitiser, rendered at sync

Repository: community-base. Depends on: C7.7, C7.4. Freeze required: no. Decision D23.

Goal: `content_sync.rendering` is the only renderer and the only sanitiser for synced content, and
no model renders markdown in `save()`.

Read first
- the specification, section 4 in full: the dialect, the ownership split, and the break list.
- `community_base/knowledge_base/rendering.py`, the donor: python-markdown plus the allowlist
  lifted from DTC.
- `community_base/curriculum/rendering.py`, the narrower second sanitiser that goes away.
- `~/git/dtc-website/content/docs_projection.py` lines 111 to 139, the heading-id algorithm the
  package adopts.
- `~/git/dtc-website/_docs/compatibility/faq-fragment-contracts.jsonl` and
  `podwiki-graph-fragment-contracts.jsonl`, the pinned fragments that algorithm keeps meaningful.

Steps
1. Move `knowledge_base/rendering.py` to `content_sync/rendering.py`, exposing `render_document`,
   `inject_heading_ids`, `sanitize_rendered_html` and `plain_text`.
2. Keep the lifted DTC allowlist and add the attributes the shared extensions emit: `class` on
   `div`, `pre`, `code`, `span` and `img`; `data-embed-type` and `data-embed-id` on `div`;
   `data-theme-figure` on `img`.
3. Inject heading ids after rendering with DTC's algorithm: NFKD, ASCII, lowercase,
   non-alphanumerics to `-`, duplicates suffixed `-1` and `-2`. Return and store the heading list
   of `{level, id, title}`.
4. Add the `mermaid` fence: the source is escaped into `<pre class="mermaid">` and the site's
   JavaScript draws it.
5. Add the `embed` fence: the body is a YAML mapping `{type, id}` with `type` in `youtube` or
   `loom`, rendering to a `div` with the data attributes and a plain link inside. No iframe is ever
   stored.
6. Add `COMMUNITY_BASE["MARKDOWN_EXTENSIONS"]`, a list of dotted paths appended to the package
   extension list. A site extends; it never replaces. Extension output still passes the package
   sanitiser.
7. `curriculum.Unit` and `KnowledgeBasePage` stop rendering in `save()`; the importer supplies
   `body_html`. `C7.4` step 3 already lets the page accept supplied HTML; make the same change for
   the unit.
8. `curriculum/rendering.py` and `knowledge_base/rendering.py` become re-exports of the shared
   module, so existing imports keep working.

Verification
- `uv run pytest tests/content_sync tests/curriculum tests/knowledge_base` passes.
- A fixture body containing a Liquid tag, a kramdown attribute list and a `<script>` renders with
  the first two rejected by `check_content` and the third removed by the sanitiser.
- Heading ids for a fixture body equal DTC's `_heading_ids` output for the same input, asserted
  against expected values copied into the test rather than against a DTC import.
- A `mermaid` fence and an `embed` fence render to the documented markup and survive the sanitiser.
- A unit and a page saved with supplied `body_html` keep it unchanged through `save()`.
- `uv run pytest -q` does not regress.

Done when
- [ ] one renderer and one sanitiser serve every synced content path in the package
- [ ] no model renders markdown in `save()`
- [ ] the heading-id algorithm is DTC's and a test pins it
- [ ] `MARKDOWN_EXTENSIONS` is documented in the kernel README settings list

Docs
- `community_base/content_sync/README.md`, `community_base/kernel/README.md`,
  `docs/02-architecture.md`, `CHANGELOG.md`.

## C7.9a Document toolkit: collections, front matter, identity and checksums

Repository: community-base. Depends on: C7.7. Freeze required: no. Decision D23.

Goal: `content_sync.documents` turns a checkout plus its `content.yaml` into validated
`ParsedDocument` values, so no parser walks files, parses YAML or validates keys again.

Scope: this issue is the toolkit's reading half. Assets and references are `C7.9b`. The parsers
that consume the toolkit are `C7.9c` for the knowledge base kinds and `C7.10` for courses.

Read first
- the specification, sections 3.1 to 3.5: the manifest, the two file shapes, the core keys, naming
  and nesting.
- `community_base/content_sync/checkout.py`, the interface the toolkit reads a repository through.
- `community_base/content_sync/parsers.py`, for `SourceItem` and the `discover` and `upsert`
  contract a toolkit-based parser still fulfils.
- `~/git/ai-shipping-labs/content/sync_parsers/families/classify.py`, the 391 lines of directory
  and front-matter heuristics the repository manifest replaces.

Steps
1. Read and validate `content.yaml`: `schema_version`, `collections`, `ignore`,
   `strict_references` and `theme_pairs`. A repository without it is not synced: record one error
   and stop for that source.
2. Walk each collection path, apply the `ignore` globs, skip names starting with `_` or `.`, and
   classify each file as a document or a manifest by the rules of section 3.2. A `.md` file inside
   a collection with no front matter is an error.
3. Validate the core keys of section 3.3 and the kind keys the `C7.7` registry declares. An unknown
   top-level key is an error.
4. Derive `slug` from the file or directory name with the ordering prefix stripped, `sort_order`
   from that prefix unless front matter overrides it, and `path` from the chain of ancestor slugs.
5. Enforce identity: `content_id` is required, is a UUID, and is unique across the whole repository
   regardless of kind. Two siblings whose names strip to the same slug are an error.
6. Enforce the nesting rules of section 3.5 per kind: a docs directory carries `index.md` and
   nests at most four deep, a wiki collection is flat, a course allows at most two module levels.
7. Emit one `ParsedDocument` per item carrying the core keys, the kind keys, the raw body, the
   repository path, the sort key, and a checksum over the whole derived record rather than over the
   file bytes alone.
8. Report errors bounded and named: the toolkit lists every violation it finds in a collection
   rather than raising on the first.

Verification
- `uv run pytest tests/content_sync` passes.
- A fixture repository yields one `ParsedDocument` per item, and the checksum changes when a
  derived field changes while the file bytes stay equal.
- Fixtures covering a missing `content_id`, a duplicate `content_id`, an unknown top-level key, a
  `.md` file with no front matter, two siblings stripping to one slug, a nested wiki directory and
  a five-level docs tree each produce a bounded error naming the file.
- A test runs `check_content` and the toolkit over the same fixtures and asserts they agree on
  every rejection.
- `uv run pytest tests/test_boundaries.py` passes.
- `uv run pytest -q` does not regress.

Done when
- [ ] a fixture repository yields one `ParsedDocument` per item with the checksum covering the
      whole derived record
- [ ] unknown keys, a missing or duplicate `content_id`, and colliding slugs are bounded errors
      naming the file
- [ ] reading a repository needs no site code
- [ ] the README documents `ParsedDocument` and every `content.yaml` key

Docs
- `community_base/content_sync/README.md`, `CHANGELOG.md`.

## C7.9b Document toolkit: assets and references

Repository: community-base. Depends on: C7.9a, C7.8. Freeze required: no. Decision D23.

Goal: the toolkit resolves every relative asset and every cross-reference, uploads the assets it
finds, rewrites both in the rendered HTML, and stores the resolved reference list on the record.

Scope: this issue is the toolkit's resolving half. It renders through `C7.8` and reads through
`C7.9a`. It registers no parser of its own.

Read first
- the specification, sections 3.6 and 3.7: assets and cross-references.
- `community_base/content_sync/media.py`, the upload boundary the toolkit uses.
- `~/git/dtc-website/content/sync_parsers/media.py` lines 53 to 73, the signature and unsafe-SVG
  checks that become the package's.
- `~/git/dtc-website/content/sync_parsers/podwiki.py` lines 265 to 299 and 363 to 374, the
  hand-written source ordering and the fail-on-unresolved behaviour the format generalises.

Steps
1. Collect asset references from document bodies, from manifest keys the kind declares as asset
   type, and from HTML `<img src>`. Resolve each from the referencing file's directory.
2. Reject an escape from the repository, an absolute `/path`, a Liquid expression, an
   `{IMAGE:id}` token, an `http://` URL and a `data:` URL. Leave `https://` references alone.
3. Enforce the allowed asset types `png`, `jpg`, `jpeg`, `gif`, `webp`, `svg` and `pdf`, a 16 MiB
   maximum, and the signature and unsafe-SVG checks.
4. An asset may live outside every collection as long as a document references it. An unreferenced
   file is not an asset and is not uploaded.
5. Upload each referenced asset through `content_sync.media` keyed by its repository path, and
   rewrite the reference in the rendered HTML and in the stored asset keys.
6. Resolve the three destination forms of section 3.7: a relative file link to another document in
   the same collection, a typed `kind:slug` or `kind:path` reference through the kind's route
   resolver, and an external URL left alone. A fragment on a same-source relative link must name a
   heading of the target.
7. Resolve front-matter references in the same typed form, including the keys whose kind is fixed:
   `authors`, `instructors` and `guests` are person references written without a prefix.
8. Apply `strict_references`: `true` fails the sync on an unresolved reference; `false` drops the
   link, keeps its label and records a warning.
9. Order sources by the kind dependencies their collections declare, so a reference to a kind from
   another source resolves against rows already synced.
10. Store the resolved references as a list of `{kind, target, label, href}` on the record.
11. Implement the `theme_pairs` opt-in: a `name.dark.ext` sibling of a referenced image becomes a
    paired asset emitted with the class hook a site styles.

Verification
- `uv run pytest tests/content_sync` passes.
- A fixture with a sibling relative link, a `wiki:` reference and a `person:` reference into a
  second source resolves all three, and the stored reference list carries the four documented keys.
- The same fixture with the target removed from the second source fails the sync under
  `strict_references: true`, and under `false` keeps the label, drops the link and records one
  warning.
- A fixture asset that is an unsafe SVG, one over 16 MiB, one behind an absolute path and one
  behind an `{IMAGE:id}` token each produce an error naming the file.
- A fixture repository whose two sources declare a kind dependency syncs in dependency order
  without a hand-written ordering.
- A fixture with `theme_pairs: true` emits the paired image markup, and the sanitiser keeps its
  attributes.
- `uv run pytest -q` does not regress.

Done when
- [ ] relative assets are uploaded once, keyed by repository path, and rewritten everywhere
- [ ] the three reference forms resolve, and the unresolved case follows `strict_references`
- [ ] source ordering comes from declared kind dependencies, not from hand-written lists
- [ ] `theme_pairs` emits the paired image markup
- [ ] the README documents the stored reference record shape

Docs
- `community_base/content_sync/README.md`, `CHANGELOG.md`.

## C7.9c Package parsers for the wiki, docs and person kinds

Repository: community-base. Depends on: C7.9b, C7.4. Freeze required: no. Decisions D24 and D31.

Goal: the knowledge base is filled by package parsers for the `wiki` and `docs` kinds, a package
person record is filled by a `person` parser, and neither site writes a parser for these three.

Scope: this is the toolkit's consuming half for the kinds whose storage the package owns. D24
amends the parser clause of D16 for exactly those three. The article parser stays per site, because
article storage is site-owned (D21). Routes and public templates stay site-owned (D16, D18).

Read first
- the specification, section 3.8 (`wiki`, `docs`, `person`) and section 6, the `source_content_id`
  finding.
- `docs/01-decisions.md`, D24 and D31.
- `community_base/knowledge_base/models.py`, `sync.py` and `README.md`, as `C7.4` leaves them.
- `~/git/ai-shipping-labs/content/sync_parsers/families/knowledge_base.py`, which after this issue
  has nothing left to do.
- `~/git/dtc-website/content/sync_parsers/podwiki.py` and `docs.py`, the DTC donors that `D7.1` and
  `D7.2` retire.

Steps
1. Register `wiki` and `docs` parsers in `knowledge_base.apps`. Each stores the HTML rendered by
   `C7.8`, the heading list, and the resolved reference list, using the record field `C7.4` added.
2. Fix `source_content_id` in the knowledge base to hold the item's own `content_id`, as `C7.7`
   wrote into `FORMAT.md` and as `curriculum/importing.py:265` already does. Add a separate source
   foreign key for the ownership scope `knowledge_base/sync.py:120` currently takes from
   `source_content_id`, and migrate existing rows. Both fields are `UUIDField`s today, so the
   migration must treat the stored value as a source primary key, not as corrupt data.
3. Add a package person model and a `person` parser: `title` is the display name, `summary` the
   short bio, `image` the picture, the body the long bio, and `links` a list of `{label, url}`.
4. Make the person record the resolution target for the `authors`, `instructors` and `guests`
   reference keys, so `C7.9b`'s fixed-kind front-matter references have somewhere to land.
5. The person kind is an optional instructor source (D31). The package defines the shape; a site
   decides whether to use it, and `A7.2` records AISL's choice.
6. Remove the fixture parser's dependence on site code in `tests/knowledge_base`.
7. Add no public routes and no public templates for any of the three kinds.

Verification
- `uv run pytest tests/knowledge_base tests/content_sync` passes, boundary test included.
- A three-level docs fixture whose leaf slugs repeat under different parents syncs and reads back
  at its own path.
- A wiki fixture stores the rendered HTML, the heading list and the resolved references, and a page
  removed from the source is soft deleted through the source foreign key rather than through
  `source_content_id`.
- A person fixture resolves an `authors:` reference made from a document in a second source.
- Migrations apply from empty and each reverses.
- `uv run pytest -q` does not regress.

Done when
- [ ] `wiki`, `docs` and `person` are parsed by the package, not by either site
- [ ] `source_content_id` holds the item `content_id` everywhere in the package
- [ ] `delete_missing` scopes by an explicit source foreign key
- [ ] a three-level docs fixture with repeated leaf slugs round-trips
- [ ] AISL's `families/knowledge_base.py` has nothing left to do, recorded in the pull request

Docs
- `community_base/knowledge_base/README.md`, `community_base/content_sync/README.md`,
  `docs/02-architecture.md`, `CHANGELOG.md`.

## C7.10 One course parser

Repository: community-base. Depends on: C7.9b. Freeze required: no. Decision D23.

Goal: one course parser reads the layout of specification section 3.8, and `parsers_aisl.py` and
`parsers_dtc.py` are both deleted.

The defect this fixes: neither package course parser works against the real course repositories
today, so neither is a baseline worth keeping. Retiring both is not a clean-up; this is the first
course parser that would read what the repositories actually contain.

| Defect | Where | Effect |
|---|---|---|
| Demands schema 1 | `curriculum/parsers_dtc.py:551-554`, with `SCHEMA_VERSION = 1` at line 46 | five of the six DTC course repositories are schema 2 (`llm-zoomcamp`, `data-engineering-zoomcamp`, `machine-learning-zoomcamp`, `mlops-zoomcamp`, `ai-dev-tools-zoomcamp`); only `stock-markets-analytics-zoomcamp` is schema 1, and it holds no module |
| Lesson front matter allows only `video_url` and `code` | `curriculum/parsers_dtc.py:356` | 71 of 72 `llm-zoomcamp` lessons carry `prev_url` and `next_url`, so the file is rejected |
| A root-level `course.yaml` is skipped | `curriculum/content_sync_parsers.py:120-125`, the `len(path.parts) > 1` guard | `ai-buildcamp-course` and `python-course` both keep `course.yaml` at the root and have no `schema_version`, so the AISL parser ignores them and the DTC parser rejects them; only `content/courses/aihero` is parsed |

Consequence: `D5.1` stops on its first repository and `A5.1` imports one course of three. Both are
blocked on this issue.

Read first
- the specification, section 3.8 (`course`) and section 6, the two findings tabulated above.
- `community_base/curriculum/parsers_dtc.py` and `parsers_aisl.py`, both of which are deleted.
- `community_base/curriculum/content_sync_parsers.py`, whose layout sniffing is deleted.
- `community_base/curriculum/source.py` for `ParsedCurriculum` and `validate_module_tree`, which
  stay.
- `community_base/curriculum/models.py` around `CohortGraph`, for the placement contract shipped in
  `C5.1e` and not reopened here.

Steps
1. Add `community_base/curriculum/parsers.py` reading the section 3.8 layout over
   `content_sync.documents`: `course.yaml`, module directories, optional submodule directories,
   unit documents, and `cohorts/<identifier>/cohort.yaml`, producing `ParsedCurriculum`.
2. Map a cohort's `modules` list to `CohortGraph.module_refs` and `CohortModule` placements. An
   absent `modules` means the full course tree in module order.
3. Map `archive: true` to an empty placement: the cohort places nothing, and its `README.md` is the
   notice for GitHub readers.
4. Map a cohort's `homework` bindings to a new `CohortGraph.homework_bindings` tuple of
   `{module, source, unit}`, which `C7.11` consumes. This issue does not read `homework.yaml`.
5. Read the unit keys of section 3.8 only: `kind`, `video_url`, `timestamps`, `session_position`,
   `is_bonus` and `code`. `prev_url`, `next_url`, `is_homework`, `is_preview` and `access` are not
   in the format, so the parser names them in its error rather than failing for an unrelated
   reason.
6. Delete `parsers_dtc.py`, `parsers_aisl.py`, their tests, and the layout sniffing in
   `content_sync_parsers.py`. Register exactly one course parser.
7. Rewrite `community_base/curriculum/README.md` around the one layout.

Verification
- `uv run pytest tests/curriculum` passes.
- Four fixture repositories, two in the converted DTC shape and two in the converted AISL shape,
  parse to hand-written expected `ParsedCurriculum` graphs.
- A fixture repository with a root-level `course.yaml` and no `schema_version` parses. That is the
  case `content_sync_parsers.py:120-125` skips today.
- A fixture course tree of two module levels with a cohort placing a subset parses to the expected
  placements.
- A fixture lesson carrying `prev_url` is rejected with the file and the key named.
- `grep -R "parsers_dtc\|parsers_aisl" community_base tests` returns nothing.
- `uv run pytest -q` does not regress.

Done when
- [ ] exactly one course parser is registered
- [ ] `parsers_aisl.py` and `parsers_dtc.py` are gone, with their tests
- [ ] a root-level `course.yaml` with no `schema_version` parses
- [ ] a lesson carrying a retired key is rejected with that key named
- [ ] `curriculum/README.md` documents one layout

Docs
- `community_base/curriculum/README.md`, `docs/02-architecture.md`, `CHANGELOG.md`.

## C7.11 Coursework: homework manifests from cohort bindings

Repository: community-base. Depends on: C7.10, C5.2h. Freeze required: no. Decision D23.

Goal: the coursework app imports the `homework.yaml` manifests a cohort binds into homework and
question rows with encrypted answers, and links a binding's `unit` to the page that shows the
submission form.

Why this is its own issue: the package coursework app has the answer envelope
(`community_base/coursework/answer_crypto.py`) but no manifest reader. DTC's
`courses/services/curriculum_source.py` lines 114 to 160 is the only implementation of the manifest
shape the format keeps, and it is site code that `D7.3` retires.

Read first
- the specification, section 3.8, the `cohort.yaml` and `homework/<module-slug>/homework.yaml`
  tables.
- the specification, section 2.2, the row that separates a `kind: homework` unit from a
  `homework.yaml`.
- `community_base/coursework/answer_crypto.py` lines 40 to 43, the answer envelope.
- `community_base/coursework/models.py`, the homework and question models.
- `~/git/dtc-website/courses/services/curriculum_source.py` lines 114 to 160, the donor reader.

Steps
1. Read each manifest named by a `CohortGraph.homework_bindings` entry, resolved relative to the
   cohort directory.
2. Validate the manifest keys: core keys plus `instructions_path` (default `homework.md`), `due_at`
   as an ISO datetime with an offset, `initial_state` in `closed`, `open` or `scored`, `form`, and
   `questions`.
3. Create homework and question rows keyed by `content_id`, with each question's answer stored as
   the existing encrypted envelope.
4. A plaintext `correct:` answer is an error. AISL's plaintext `questions:` shape in unit front
   matter is not read anywhere.
5. Bind the homework to the cohort module that the entry's `module` slug names.
6. When a binding carries `unit`, link that `kind: homework` unit so its page renders the
   submission form. The unit stays a page in the reading order; the assignment stays cohort-owned.
7. Make re-import idempotent: a second run of the same manifest updates rows rather than
   duplicating them.

Verification
- `uv run pytest tests/coursework tests/curriculum` passes.
- A fixture cohort binding one manifest creates the homework, its questions and their encrypted
  answers, and a second import leaves every row count unchanged.
- A fixture binding carrying `unit` renders the submission form on that unit's page.
- A fixture manifest carrying a plaintext `correct:` key is rejected with the file and key named.
- A fixture binding naming a module the cohort does not place is rejected.
- `uv run pytest -q` does not regress.

Done when
- [ ] a bound manifest creates the homework, its questions and their encrypted answers
- [ ] a binding with `unit` renders the submission form on that unit's page
- [ ] re-import is idempotent
- [ ] no plaintext answer shape is read anywhere in the package

Docs
- `community_base/coursework/README.md`, `CHANGELOG.md`.

## C7.12 Conversion scripts and the unified format release

Repository: community-base. Depends on: C7.9c, C7.10, C7.11. Freeze required: no. Decision D23.

Goal: `content_sync/convert/` holds the two conversion scripts of specification section 5, each
exercised against a scratch copy of every real content repository, and the package is tagged so the
five site issues can pin it.

Read first
- the specification, section 5 in full: the per-repository conversion table and the three places
  where human review concentrates.
- `docs/03-playbooks.md`, playbook P15, the tag-before-a-site-issue rule.
- `docs/04-quality-gates.md`, for what a release pull request must show.
- `docs/01-decisions.md`, D25, D26, D27 and D28, which fix what each repository converts to.

Steps
1. Add `content_sync/convert/courses.py`: manifest to front matter, the `units:` list pushed into
   unit files, the cohort rewrite, `ignore` moved into `content.yaml`, retired keys dropped, and
   `content_id` carried where it exists or minted where it does not.
2. Add `content_sync/convert/documents.py`: file rename and directory reshape, key mapping, link
   and image rewrite, Liquid and kramdown handling, and `content.yaml` generation.
3. Make each script idempotent, and have it write a report naming every file it changed and every
   construct it could not convert. That report is the input to the human review step.
4. Run both scripts against a scratch copy of each of the sixteen repositories in section 5, and
   record the result per repository in the pull request.
5. Record the three human-review concentrations as open items against the site issues that own
   them, rather than resolving them here: the rendering diff of the 55 DTC articles, the 25
   re-parented DTC documentation pages (D28), and the podwiki tokens whose title resolves to
   nothing.
6. State in each module docstring that both scripts are deleted after the last conversion merges,
   which is `D7.4`.
7. Tag a release and write the format into `CHANGELOG.md`.

Verification
- `uv run pytest tests/content_sync` passes.
- Each of the sixteen repositories converts on a scratch copy, and the converted copy passes
  `check_content` with zero errors. The pull request carries the sixteen result lines.
- Running a script twice over the same copy produces no second diff.
- The cross-repository check is green against both sites' default branches.
- The release tag exists and `CHANGELOG.md` names the format version.
- Not run here, needs: `A7.3` and `D7.4`. A conversion merged into a content repository, and a
  production sync of it, belong to those issues.

Done when
- [ ] both conversion scripts exist, are idempotent, and report what they could not convert
- [ ] all sixteen repositories convert on a scratch copy and pass `check_content`
- [ ] the three human-review items are recorded against the site issues that own them
- [ ] the release tag exists and both sites' cross-repository check is green

Docs
- `community_base/content_sync/README.md`, `CHANGELOG.md`, `docs/plan/STATUS.md`.

## A7.2 AISL: adopt the toolkit and the one course parser

Repository: AI-Shipping-Labs/website. Depends on: C7.12. Freeze required: no. Decision D23.

Goal: AISL's `content/sync_parsers/` reads the unified format and nothing else: the classifier is
gone, tier B kinds are registered kinds, and synced content is rendered and sanitised once by the
package.

Read first
- AISL `AGENTS.md` and `_docs/PROCESS.md` first; they govern the work.
- AISL `_docs/testing-guidelines.md` and `scripts/affected_tests.py`, for the test selection.
- the specification, section 3.8 and the AISL rows of section 5.
- `docs/01-decisions.md`, D29, D30 and D31.
- `content/sync_parsers/classify.py` and `parsing.py`, which are deleted.
- `content/utils/markdown.py`, whose `sanitize_html`, `normalize_inline_bullets` and
  `linkify_urls` stop running on synced content.

Steps
1. Replace `classify.py` and `parsing.py` with the package toolkit. Each source declares its kinds
   in its own `content.yaml`; the site classifies nothing.
2. Register the tier B kinds AISL owns: `workshop`, `project`, `curated_link`,
   `interview_question` and the member wiki topic, each with the kind schema of section 3.8.
3. Delete the tier A family bodies for `course`, `wiki` and `docs`; those parsers are the
   package's now.
4. Keep the article parser as a thin adapter that fills `content.Article` from a `ParsedDocument`.
   D21 keeps that model site-owned.
5. Stop running `sanitize_html`, `normalize_inline_bullets` and `linkify_urls` on synced content.
   They stay where they are for Studio-authored event and email text.
6. Register `codehilite`, `MermaidExtension`, `ExternalLinksExtension` and `EventWidgetExtension`
   through `COMMUNITY_BASE["MARKDOWN_EXTENSIONS"]`. An extension needing a new attribute needs a
   package change to the allowlist; report that rather than adding a second sanitiser.
7. Decide the question D31 leaves to this issue: keep instructors database-authored, or adopt the
   `person` kind. Record the choice and its reason in the pull request.
8. Leave `events/*.yaml` alone. D30 makes retiring that family a separate AISL issue, and this one
   carries no events decision.
9. Keep AISL's entitlement keys under `extra` (D29).

Verification
- `make test-affected` passes; `scripts/affected_tests.py` selects the touched apps.
- Every AISL source, converted on a branch by the `C7.12` scripts, syncs on a development deploy
  with zero errors.
- All three AISL courses import, not one. That is the `content_sync_parsers.py:120-125` defect
  `C7.10` fixes and `A5.1` needs.
- The package is pinned by tag in `uv.lock`, and AISL's local-source check passes, so no local or
  branch package source is committed.

Done when
- [ ] `classify.py` and `parsing.py` are gone
- [ ] tier B kinds are registered kinds rather than classifier branches
- [ ] `sanitize_html` no longer runs on synced content
- [ ] a development deploy syncs every converted AISL source with zero errors
- [ ] all three AISL courses import
- [ ] the person-kind decision is recorded in the pull request

Docs
- AISL `_docs/` as that repository's process requires; `docs/plan/STATUS.md` here.

## D7.2 DTC: editorial, people and data kinds on the toolkit

Repository: DataTalksClub/website. Depends on: C7.12, D7.1. Freeze required: no. Decision D23.

Goal: DTC's article, book, podcast, person and data parsers are rewritten over the toolkit,
`SyncedDocument` stays, and the media parser stops uploading every file under `images/`.

Read first
- DTC `AGENTS.md` and `_docs/PROCESS.md` first; they govern the work.
- DTC `_docs/specs/03-github-content-and-people.md`, the product authority here, whose adapter
  sections this issue amends to cite the format.
- DTC `_docs/architecture/app-boundaries.md`.
- the specification, section 3.8 (`article`, `person`, `data`) and the tier B rows for `podcast`,
  `book` and `faq`.
- `docs/01-decisions.md`, D25, D26 and D27.
- `content/sync_parsers/media.py` lines 22 to 27 and 131 to 140, which upload every file under
  `images/` whether a document references it or not.

Steps
1. Rewrite the article, book and podcast parsers as thin adapters over the toolkit. They validate
   nothing; the toolkit does. The `person` parser is NOT rewritten here: D24 moved it into the
   package and C7.9c shipped it, so DTC stops having a person parser at all and configures the
   package one. An earlier revision of this step listed `person` among the site adapters, which
   contradicted D24; D24 is the later owner decision and wins.
2. Keep `SyncedDocument` (D21). The format is upstream of storage.
3. Replace the media parser with the referenced-asset upload of `C7.9b`. An unreferenced file is no
   longer a media row.
4. Stop applying the bleach cleaner in `content/services.py` to synced content. `D7.1` moved wiki
   and docs rendering; this issue finishes the editorial kinds.
5. Register `faq` as a site kind with its current file shape (D26). Do not convert the questions.
6. Register `graph/graph.json` and `search/search-corpus.json` as `data` files (D27). The podwiki's
   own scripts keep producing them; rebuilding the graph from synced references is a later
   DTC-owned issue.
7. Register `podcast-platforms.yaml` and `slack.yaml` as `data` files, and delete the two parsers
   that publish nothing today.
8. Point the `person` kind at `DataTalksClub/content` rather than `datatalksclub.github.io`, and
   delete DTC's own person parser rather than adapting it. The file move itself is `D7.4` (D25).

Verification
- The route contract and sitemap contract tests pass unchanged for articles, books, podcasts and
  people.
- A development deploy serves the `/images/` route from the referenced assets of a converted
  repository, and an unreferenced file in that repository is not served.
- The rendered output of the 55 converted articles matches the human-reviewed rendering diff that
  `C7.12` produced.
- The package is pinned by tag in `uv.lock`, and `scripts/check_community_base_source.py` passes.

Done when
- [ ] article, book, podcast, person and data kinds read through the toolkit
- [ ] route and sitemap contract tests pass unchanged
- [ ] only referenced assets are uploaded
- [ ] the bleach cleaner no longer runs on synced content
- [ ] `_docs/specs/03-github-content-and-people.md` cites the format

Docs
- DTC `_docs/specs/03-github-content-and-people.md`; `docs/plan/STATUS.md` here.

## D7.3 DTC: course repositories on the package course parser

Repository: DataTalksClub/website. Depends on: D5.1, C7.12. Freeze required: no. Decision D23.

Goal: DTC imports its six course repositories through `community_base.curriculum` and
`community_base.coursework`, and no DTC code parses `course.yaml`.

Read first
- DTC `AGENTS.md` and `_docs/PROCESS.md` first; they govern the work.
- DTC `_docs/specs/` for the course platform specs that name the schema branches being retired.
- the specification, section 3.8 (`course`) and section 6, the defect `C7.10` fixes.
- every DTC module that reads `course.yaml`, not only the two this issue first named. Measured
  2026-09-17, nine non-test modules do, and the goal above is not met while any of them remains:

| Module | Lines |
|---|---|
| `scripts/build_public_projection.py` | 3377 |
| `content_sync/course_repository.py` | 1608 |
| `courses/services/curriculum_import.py` | 1497 |
| `content_sync/course_repository_v2.py` | 795 |
| `courses/services/local_course_seed.py` | 415 |
| `courses/services/curriculum_source.py` | 229 |
| `content_sync/course_repository_layout.py` | 193 |
| `content_sync/course_repository_registration.py` | 158 |
| `courses/services/course_family_identity.py` | 53 |

  An earlier revision of this issue named only `curriculum_source.py` and
  `curriculum_import.py`, which would have left seven modules parsing the format the issue
  claims to retire. Note the `_v2` module in particular: the schema-2 handling this issue
  retires lives in its own file, so deleting schema branches from the other two would not
  reach it.
- the `zoomcamp-ops` `check_zoomcamp.py` checker, which `check_content` replaces.

Steps
1. Point the course import at `community_base.curriculum` and the homework import at
   `community_base.coursework`.
2. Delete every reader in the table above, not two of them. One format means one branch, and
   one parser. The `content_sync/course_repository*` family is four modules and about 2750 lines
   that `community_base.curriculum.parsers` replaces wholesale.
2a. Two of the nine are not course-repository parsers and need their own answer rather than
   deletion: `scripts/build_public_projection.py` is a projection build and
   `courses/services/local_course_seed.py` seeds a local dataset. Decide per module whether it
   reads through the package toolkit or stops reading `course.yaml` at all, and say which in the
   pull request.
3. Replace the `zoomcamp-ops` layout checks with `check_content` in each course repository's CI.
   The file conversions themselves are `D7.4`.
4. Keep cohort placement as shipped in `C5.1e`. This issue changes the reader, not the ownership.

Verification
- The shared-curriculum route contract passes on a development deploy against a course repository
  converted on a branch by the `C7.12` scripts.
- All six course repositories import, including the five that are schema 2 today and the one that
  is schema 1 with no modules. That is the `parsers_dtc.py:551-554` defect `C7.10` fixes and `D5.1`
  needs.
- No DTC module parses `course.yaml`, proven by a grep recorded in the pull request.
- The package is pinned by tag in `uv.lock`, and `scripts/check_community_base_source.py` passes.

Done when
- [ ] the six course repositories import through the package
- [ ] no DTC code parses `course.yaml`
- [ ] the `zoomcamp-ops` layout checker is replaced by `check_content`
- [ ] the shared-curriculum route contract passes on a development deploy

Docs
- DTC `_docs/specs/` as that repository's process requires; `docs/plan/STATUS.md` here.

## A7.3 AISL: convert and cut over the content repositories

Repository: AI-Shipping-Labs/website. Depends on: A7.2. Freeze required: yes. Decision D23.

Goal: every AISL content repository is converted by the `C7.12` scripts, validated by
`check_content` in its own CI, merged, and synced from `main` with zero errors.

Freeze: one day of no content writes per repository, taken one repository at a time, on
`AI-Shipping-Labs/wiki`, `AI-Shipping-Labs/content`, `AI-Shipping-Labs/python-course`,
`AI-Shipping-Labs/workshops-content` and `AI-Shipping-Labs/ai-buildcamp-course`. This is a content
freeze, not a site production freeze: no database table moves and the site keeps serving. The
freeze exists because a conversion rewrites every file in the repository, so any content pull
request opened during the window conflicts with all of them.

Order: `wiki`, `content`, `python-course`, `workshops-content`, then `ai-buildcamp-course` last,
because a paid cohort is running against it and it converts from the `restructure-1675-maven-tree`
branch rather than from `main`.

Read first
- AISL `AGENTS.md` and `_docs/PROCESS.md` first; they govern the work, including who may merge in
  the content repositories.
- the specification, section 5, the five AISL rows.
- the `C7.12` conversion reports for those five repositories.

Steps
1. Announce the freeze window for the repository being converted, record the pages it serves today,
   and stop merging content pull requests in it for the day.
2. Run the `C7.12` conversion script on a branch of that repository.
3. Add `check_content` to that repository's CI and make it a required check.
4. Review the conversion report's unconvertible items. Section 5 records none for AISL; anything
   the report lists is resolved before the merge, not after.
5. Merge the conversion in the same hour the `A7.2` deploy reaches production, then sync.
6. Delete `scripts/check_workshops.py`, `scripts/check_content_ids.py` and their siblings from the
   content repositories; `check_content` replaces them.
7. Lift the freeze once that repository syncs with zero errors, then take the next one.

Verification
- Every AISL source syncs from `main` with zero errors and zero warnings.
- `check_content` is a required check in each of the five repositories.
- The pages recorded in step 1 are served after the cutover, spot-checked per repository.
- No script named in step 6 remains in any of the five repositories.

Done when
- [ ] all five repositories are converted and merged
- [ ] every AISL source syncs from `main` with zero errors and zero warnings
- [ ] `check_content` is required in each repository's CI
- [ ] the replaced repository scripts are deleted
- [ ] each freeze window was announced and lifted, recorded in the pull request

Docs
- AISL `_docs/` as that repository's process requires; `docs/plan/STATUS.md` here.

## D7.4 DTC: convert and cut over the content repositories

Repository: DataTalksClub/website. Depends on: D7.2, D7.3. Freeze required: yes. Decision D23.

Goal: every DTC content repository is converted by the `C7.12` scripts, validated by
`check_content` in its own CI, merged, and synced from `main` with zero errors, and
`datatalksclub.github.io` stops being a sync source.

Freeze: one day of no content writes per repository, taken one repository at a time, on
`DataTalksClub/docs`, `DataTalksClub/podwiki`, `DataTalksClub/content`,
`DataTalksClub/ai-dev-tools-zoomcamp`, `DataTalksClub/data-engineering-zoomcamp`,
`DataTalksClub/llm-zoomcamp`, `DataTalksClub/machine-learning-zoomcamp`,
`DataTalksClub/mlops-zoomcamp`, `DataTalksClub/stock-markets-analytics-zoomcamp` and
`DataTalksClub/faq`. `DataTalksClub/datatalksclub.github.io` freezes for the day its `_people`
directory moves. This is a content freeze, not a site production freeze: no database table moves
and the site keeps serving.

Order: `docs`, `podwiki`, `content` with `people/` moved in from `datatalksclub.github.io` (D25),
then the six course repositories, then `faq` last with its `content.yaml`-only change (D26).

Read first
- DTC `AGENTS.md` and `_docs/PROCESS.md` first; they govern the work, including who may merge in
  the content repositories.
- the specification, section 5, the ten DTC rows.
- `docs/01-decisions.md`, D25, D26 and D28.
- the `C7.12` conversion reports for those repositories.
- `content/route_contracts.py` and `content/sitemap_contract.py`, the pinned inventories the
  documentation path change edits.

Steps
1. Announce the freeze window for the repository being converted, record the pages it serves today,
   and stop merging content pull requests in it for the day.
2. Run the `C7.12` conversion script on a branch of that repository.
3. Add `check_content` to that repository's CI and make it a required check.
4. Resolve the repository's human-review items before the merge: the rendering diff of the 55
   articles for `content`, the tokens that resolve to nothing for `podwiki`, and the 25 re-parented
   pages for `docs`.
5. For `docs`, take the nested paths the section parents imply (D28). Update
   `content/route_contracts.py` and `content/sitemap_contract.py` for exactly those 25 paths and no
   others, in the same pull request, so the contract stays a contract.
6. Move `_people` and `images/authors/` from `datatalksclub.github.io` into `DataTalksClub/content`
   as a `people/` collection (D25), then remove `datatalksclub.github.io` from `CONTENT_SOURCES`.
7. Convert `faq` last, with `content.yaml` and the `_questions` to `faq` rename only (D26). Leave
   the question files and `faq_automation/` alone.
8. Lift the freeze once that repository syncs with zero errors, then take the next one.
9. After the last conversion merges, delete `content_sync/convert/` in a package pull request, as
   `C7.12` step 6 states.

Verification
- Every DTC source syncs from `main` with zero errors and zero warnings.
- The route and sitemap contract tests pass with exactly the 25 documentation paths changed and no
  other path changed.
- `datatalksclub.github.io` is absent from `CONTENT_SOURCES`, and the people pages still serve.
- `check_content` is a required check in each of the ten repositories.
- `content_sync/convert/` is gone from the package.

Done when
- [ ] all ten repositories are converted and merged
- [ ] every DTC source syncs from `main` with zero errors and zero warnings
- [ ] the 25 documentation paths changed and the contracts were updated in the same pull request
- [ ] `datatalksclub.github.io` is removed from `CONTENT_SOURCES`
- [ ] the conversion scripts are deleted from the package
- [ ] each freeze window was announced and lifted, recorded in the pull request

Docs
- DTC `_docs/specs/03-github-content-and-people.md` and `_docs/specs/` as that repository's process
  requires; `docs/plan/STATUS.md` here.

Issue numbers `C7.7` to `C7.12` were reserved for the unified content format while its
specification was under review; they are the issues above. The two issues below took `C7.13` and
`C7.14` while that reservation stood.

## C7.13 Studio registration follows the mounted routes

Repository: community-base. Depends on: C2.1a. Freeze required: no.

Goal: a site that installs a package app but does not mount its Studio URLs can still pass
`studio_routes --check`. Today it cannot, and that blocks A2.1 (AI-Shipping-Labs/website#1615).

The defect: `community_base/mail/apps.py` lines 15 to 17 and
`community_base/knowledge_base/apps.py` lines 10 to 13 call `register_studio()` unconditionally.
The destinations claim the route names in `mail/studio_urls.py` and `knowledge_base/studio_urls.py`.
AISL installs both apps and mounts neither module, so six routes are permanently `claimed but not
mounted` and the check fails with no site-side remedy: `studio_routes.py` has no ignore flag and
`kernel/conf.py` has no opt-out.

The six: `community_base_mail_deliveries`, `community_base_mail_delivery`,
`community_base_mail_template`, `community_base_mail_templates`,
`knowledge_base_studio_page_detail`, `knowledge_base_studio_page_list`.

Why the alternative is wrong: AISL could mount both modules, but that adds a package Mail surface
next to AISL's own Email log and Email templates pages, and a Knowledge base section it has not
asked for. That is a product decision, not shell adoption, and it makes installing an app imply
shipping its Studio pages.

Steps
1. Register a Studio destination only when its routes are actually mounted, or give the site an
   explicit opt-out. Prefer the first: a claim that does not match the URLconf is the bug.
2. Apply the same rule to every package app that registers Studio destinations, not just the two
   that surfaced. Find them with a grep for `register_studio`.
3. Leave the destinations registered where the routes are mounted, so no adopting site loses a
   page it has today.

Verification
- A synthetic site config that installs `mail` and `knowledge_base` without mounting their Studio
  URLs passes `studio_routes --check` with zero errors.
- The same config with the URLs mounted registers all six destinations.
- `uv run pytest tests/studio` passes.

Done when
- [ ] installing an app no longer claims Studio routes the site has not mounted
- [ ] a test covers both the mounted and unmounted configurations
- [ ] the studio README states the rule

Docs
- `community_base/studio/README.md`, `CHANGELOG.md`.

## C7.14 Studio sidebar collapse and navigation density

Repository: community-base. Depends on: C2.1a. Freeze required: no.

Goal: the shared Studio shell stays navigable when a site registers a realistic number of
destinations. Today it does not, and that blocks the destructive half of A2.1
(AI-Shipping-Labs/website#1615): deleting the donor shell would ship a regression.

The defect: `templates/community_base/studio/base.html` lines 52 to 100 render every section
always-expanded, and `static/community_base/studio.js` has no collapse. With AISL's registry that
is 47 flat destinations plus 4 grouped across 11 sections, so roughly 51 permanently visible links,
on a 390 pixel viewport as well. The donor shell collapses to 8 headers and remembers the state per
viewer in localStorage (AI-Shipping-Labs/website#1287).

Also missing, found in the same pass and small enough to ride along:

| Gap | Donor behaviour | Where |
|---|---|---|
| External link destination | staff "API docs" opens `/api/docs` in a new tab | `studio/registry.py` lines 11 to 18, no field for it |
| Per-destination icon | one lucide icon per link | registry has no icon field |
| Sidebar footer hook | version line, back to website, theme toggle | shell has no footer block |
| Grouped search results | results grouped with headers and summaries | `studio.js` lines 37 to 50 render flat labels only |

Steps
1. Add section collapse with per-viewer persistence. The active section, and any section owning the
   active deep route, must be open on load regardless of stored state.
2. Add the external-link and icon fields to `Destination`, both optional, defaulting to today's
   behaviour.
3. Add a sidebar footer block a site can fill.
4. Group the search results the way the sidebar groups destinations.

Verification
- A synthetic registry of 50 destinations across 11 sections renders collapsed, with the active
  section open, and the state survives a reload.
- Every existing Studio test passes unchanged: a site that registers few destinations sees no
  behaviour change.
- `uv run pytest tests/studio` passes.

Done when
- [ ] sections collapse and remember their state per viewer
- [ ] the active section and active deep route are always visible
- [ ] destinations can be external links and can carry an icon
- [ ] search results are grouped

Docs
- `community_base/studio/README.md`, `CHANGELOG.md`.

## C7.15 Studio shell: messages, banner, focus ring and per-destination test hooks

Repository: community-base. Depends on: C7.14. Freeze required: no.

Goal: a site can delete its own Studio shell without losing behaviour. C7.13 and C7.14 removed two
blockers from A2.1 (AI-Shipping-Labs/website#1615) and both are verified working, but the cutover
then found five more. Four are small; the first is a hard blocker.

Evidence, all from rendering real AISL Studio pages through the package shell rather than from
reading it: `studio_routes --check` now reports 353 mounted Studio routes, 353 claimed, 0 errors,
and collapse behaves correctly at 51 destinations, so C7.13 and C7.14 did their jobs.

Read first
- `community_base/studio/templates/community_base/studio/base.html`, lines 99 to 105.
- `community_base/studio/templates/community_base/studio/includes/nav_link.html`.
- `~/git/ai-shipping-labs/templates/_partials/messages.html`, the site region the package hides.

The five gaps

| Gap | Where | Why it blocks a cutover |
|---|---|---|
| Messages region is unconditional | `base.html` lines 101 to 105 | No surrounding block, no `data-testid`, no per-message `message.tags`. A site cannot suppress it to render its own, so its own region is unreachable. Ten Playwright spec files plus one Django test select it, and two more assert success against error by tag |
| No banner hook above the content region | `base.html` line 99 | The site's environment-mismatch banner has nowhere full-bleed to go. Overriding the content block works but moves it inside the padded column |
| No focus-visible ring on a nav link | `nav_link.html` line 3 | The adopting site has an explicit accessibility standard and a test asserting every nav anchor carries the ring. Every donor nav anchor has one |
| No `data-testid` per destination | `nav_link.html` | About 60 Playwright tests across four spec files select destinations by test id |
| Quick jump and mobile scroll affordance | donor shell only | The package ships a simpler search box under different hooks, so the command palette is lost |

Steps
1. Wrap the messages region in a block a site can override, and carry each message's tags and a
   test id in the default markup. Both, not either: a site that keeps the default still needs the
   tags to distinguish success from error.
2. Add a block above the content region for a full-bleed site banner.
3. Add the focus-visible ring to the nav link. Keyboard accessibility is not a site preference.
4. Add a per-destination test id derived from the destination key.
5. Decide whether the quick-jump palette belongs in the package. If it does, say so and scope it;
   if it does not, say that the adopting site keeps its own and how it coexists with the package
   search box. Either answer closes the row; silence does not.

Verification
- A site template overriding the messages block renders its own region and none of the package's.
- A site that overrides nothing still sees each message's tags and test id.
- Every nav anchor carries the focus ring, asserted by a test.
- `uv run pytest tests/studio` passes and no existing test needed changing.

Done when
- [ ] a site can replace the messages region without losing tags or a test hook
- [ ] a banner can render full-bleed above the content region
- [ ] every nav anchor carries a focus-visible ring
- [ ] every destination carries a stable test id
- [ ] the quick-jump question is answered either way

Docs
- `community_base/studio/README.md`, `CHANGELOG.md`.

## C7.16 Studio quick jump and the sidebar scroll affordance

Repository: community-base. Depends on: C7.15. Freeze required: no.

Goal: the shared shell owns the keyboard command palette and the mobile sidebar scroll
affordance that today exist only in the donor shell, so an adopting site deletes them along with
the rest of its shell.

Why the package and not the site, the row `C7.15` left open: the palette is the package's own
search capability under a second trigger. It queries `studio_global_search`, the endpoint the
package already ships, and renders the same grouped results the sidebar box renders. The package
also already claims the keybinding: `static/community_base/studio.js` binds Ctrl/Cmd-K and calls
`preventDefault()` to focus the sidebar search box, so a site palette on the same chord is
double-handled and fights the package for focus. Two implementations of one capability, over one
endpoint, on one keybinding, is the duplication this plan exists to remove. Until this issue
lands the adopting site keeps its own palette and accepts that conflict; nothing else in the
shell depends on it.

Read first
- `community_base/studio/static/community_base/studio.js`, the `[data-studio-search]` block and
  its Ctrl/Cmd-K handler.
- `community_base/studio/templates/community_base/studio/base.html`, the sidebar search box.
- `~/git/ai-shipping-labs/templates/studio/base.html`, `data-studio-quick-jump` and
  `studio-sidebar-scroll-affordance`.

Steps
1. Render a quick-jump overlay in the shell, hidden by default, opened by Ctrl/Cmd-K and closed by
   Escape, reusing the existing fetch and result rendering instead of a second copy of them.
2. Keep the sidebar search box working unchanged, including when the overlay is absent because a
   site overrode it away.
3. Add the mobile scroll affordance at the foot of the sidebar nav, visible only while the nav can
   scroll further.
4. Rebuild `static/community_base/studio.css` from `assets/tailwind.css` with `npm run css:build`
   in `community_base/studio/assets`. Both surfaces need utilities the shipped build does not
   contain, the affordance gradient among them; C7.15 deliberately stopped at the classes the
   shipped build already carries.
5. Name the hooks so the donor selectors survive the cutover: `data-studio-quick-jump` on the
   overlay, plus test ids on its input and its result list.

Verification
- `uv run pytest tests/studio` passes and no existing test needed changing.
- The shell renders the overlay hidden, and the sidebar search box keeps its own markup.
- The rebuilt stylesheet contains the new utilities and still contains every class the shell used
  before the rebuild.

Done when
- [ ] Ctrl/Cmd-K opens one palette that the package owns
- [ ] the sidebar search box is unchanged for a site that ignores the palette
- [ ] the sidebar shows a scroll affordance on a narrow viewport
- [ ] the stylesheet is rebuilt from the package's own Tailwind source

Docs
- `community_base/studio/README.md`, `CHANGELOG.md`.

## C7.17 Studio: a landing page that does not open fully collapsed

Repository: community-base. Depends on: C7.14. Freeze required: no.

Goal: a site with enough destinations to trigger collapse still opens its Studio landing page on
something. Found by the A2.1 cutover (AI-Shipping-Labs/website#1615), which is otherwise complete.

The defect: `registry._apply_collapse_state` expands a section when it is the active one, and
`active_state` takes the active section from the destination matching the current route. On
`/studio/` that destination is the built-in Dashboard, which lives in the headerless `home`
section. So above `STUDIO_NAV_COLLAPSE_THRESHOLD` every titled section renders collapsed on the
landing page, and the viewer arrives at a sidebar of closed headers. AISL has 52 destinations
against a default threshold of 24. The donor shell opened Events there and a browser test pinned
it.

There is no site-side fix, which is what makes it a package issue rather than an adoption note.
`claim_section_only('studio_dashboard', ...)` is overwritten by the built-in's own match, and
raising the threshold disables collapse everywhere rather than on one page.

Read first
- `community_base/studio/registry.py`, `_apply_collapse_state` and `active_state`.
- `community_base/studio/builtin.py`, which registers the headerless `home` section.
- C7.14's rule that the active section is expanded server-side, which this must not break.

Steps
1. Choose one shape and say why. Either a `STUDIO_NAV_DEFAULT_SECTION` setting naming the section
   to open when the active one is headerless, or letting a headerless active section fall through
   to the first titled section. The second needs no site configuration and is the smaller contract;
   the first is explicit. Prefer the smaller contract unless a site needs to differ.
2. Keep C7.14's guarantee intact: the section owning the active route is still expanded
   server-side, and a stored collapse still cannot hide the current page.
3. Leave behaviour unchanged below the threshold, where every section is expanded anyway.

Verification
- A synthetic registry above the threshold, rendered at the landing route, opens exactly one
  titled section.
- The same registry at a deep route still opens that route's section and no other.
- Below the threshold nothing changes.
- `uv run pytest tests/studio` passes and no existing test needed changing.

Done when
- [ ] a landing page above the threshold opens one section rather than none
- [ ] C7.14's active-route guarantee is unchanged, proven by its existing tests passing untouched
- [ ] the chosen shape is documented in the studio README

Docs
- `community_base/studio/README.md`, `CHANGELOG.md`.

## C7.18 Make the code match decisions D38 and D39

Repository: community-base. Depends on: C7.9b, C7.10. Freeze required: no.

Goal: the kind registry and the reference resolver implement what D38 and D39 ruled. `FORMAT.md`
was synced to those decisions on 2026-09-18; the code was not, and a normative document the code
contradicts is worse than either alone.

How the gap happened, recorded because the process failure is the reusable part: D34, D38 and D39
were taken as delegated decisions and written into `docs/01-decisions.md`, and nobody carried them
into `FORMAT.md` or the registry. A decision recorded in one place and implemented in none looks
settled in review and is not. Deciding and landing should be one unit of work, or the decision
should say explicitly which issue lands it.

Read first
- `docs/01-decisions.md`, D38 and D39.
- `community_base/content_sync/FORMAT.md` section 3.7's destination table and the cohort table in
  section 3.8, both already stating the ruled behaviour.
- `community_base/content_sync/kinds/course.py`, the `archive` key.
- `community_base/content_sync/resolution.py`, which resolves the three destination forms.

Steps
1. D38: `archive` becomes a mapping with one optional `notice_path`, defaulting to the cohort's
   `README.md`. Absent means not archived. The parser reads the notice from the declared path.
   Two of the seventeen real archived cohorts point at `leaderboard.md`, so a boolean silently
   discards which file the notice is.
2. D39: add the repository-file destination. A link to a file or directory that exists in the
   repository but is not content resolves to the repository's hosting URL. It is never uploaded
   and never validated as content, and it must not be reported as an unresolved reference.
3. Decide where the hosting URL comes from and say so. A `ContentSource` already knows its
   repository; prefer that over a new setting.
4. C7.10 does not call `resolve_repository` for courses precisely because these links fail today.
   Once this lands, say whether that can be switched on, and if not, why.

Verification
- A cohort with `archive: {notice_path: cohorts/2025/leaderboard.md}` reads its notice from that
  file, and one with `archive: {}` reads `README.md`.
- A lesson body linking to `code/rag_helper.py` and to `../cohorts/2025/` resolves both to hosting
  URLs and reports no unresolved reference under the default `strict_references`.
- `check_content` accepts a real course repository's links that fail today.
- `uv run pytest tests/content_sync tests/curriculum` passes.

Done when
- [ ] `archive` is a mapping and a non-default notice path is honoured
- [ ] a repository-file link resolves rather than failing the sync
- [ ] FORMAT.md, the registry and the resolver agree, verified by a test that reads the format's
      own fixtures rather than by inspection

Docs
- `community_base/content_sync/README.md`, `CHANGELOG.md`.

## C7.19 Studio registration works on a namespaced URLconf

Repository: community-base. Depends on: C7.13. Freeze required: no.

Goal: a site whose Studio URLconf declares `app_name` can register destinations that are both live
and linkable. Today it cannot, and this is a v0.5.0 regression I introduced in C7.13.

The defect, measured against DataTalksClub/website's real URLconf: `route_names.py` walks the
resolver tree and records the bare `entry.name`, discarding the namespace, so the mounted set holds
`audit-detail` and never `studio:audit-detail`. `registry._is_live` then tests
`destination.url_name in mounted`, while `registry._destination_url` calls
`reverse(destination.url_name)`, which needs the namespace. Those two cannot both be satisfied:
registering `studio:settings` makes `mounted_sections()` return an empty tuple, and registering
`settings` makes `reverse()` raise `NoReverseMatch` so the link renders with an empty href. DTC has
62 bare names under `studio/` and 26 namespaced routes, and none of the 26 is found in the mounted
set. `route_name_for` has the same defect, reading `resolver_match.url_name` rather than
`view_name`.

Why it was not caught: there is no namespaced-URLconf test anywhere in `tests/studio/`, and
AI-Shipping-Labs mounts Studio without a namespace, so the only consumer that would have shown it
had not adopted yet. Before C7.13 there was no mounted-route filter, so a namespaced `url_name`
worked; the filter is what made the two halves disagree.

Read first
- `community_base/studio/route_names.py`, the `walk()` function.
- `community_base/studio/registry.py`: `_is_live`, `_destination_url`, `route_name_for`.
- `docs/03-playbooks.md` P7's both-directions rule. This is the same shape: a guard that reads one
  spelling of a name while the resolver writes another.

Steps
1. Record the namespaced name in `route_names.py` when a resolver declares a namespace.
2. Make `route_name_for` prefer `resolver_match.view_name`.
3. Decide what `route_names` tuples must contain once `route_name_for` returns a namespaced value,
   and say whether that is breaking for an existing site. Prefer accepting both spellings over
   forcing every registration to be rewritten.
4. Decide whether a namespace nested more than one level deep needs handling.

Verification
- A namespaced Studio URLconf: destinations live, hrefs non-empty and correct, active link detected.
- The same with no namespace, unchanged.
- An `external_url` destination stays live under both, per C7.14.
- The AI-Shipping-Labs suite is unaffected, measured rather than asserted.

Done when
- [ ] a namespaced site can register a destination that is both live and linkable
- [ ] a test would fail if either half regressed on its own

## C7.20 Studio shell: extension points instead of a fork

Repository: community-base. Depends on: C7.15. Freeze required: no.

Goal: a site can adopt the shell without copying it. Two missing extension points currently force a
verbatim fork, which is exactly what community-base#279 exists to prevent: the abandoned DTC
attempt forked 152 lines, and its own header comment predicted this issue.

Read first
- `community_base/studio/templates/community_base/studio/base.html`.
- `community_base/studio/checks.py`, `check_studio_content_block_contract` and error code
  `community_base.studio.E001`, which exists because a site fork of this shell once dropped the
  `content` block and served 38 empty pages.

Steps
1. The head hardcodes `https://unpkg.com/lucide@latest/...` outside any block. Two problems, each
   sufficient on its own: an unpinned third-party script executes with staff privileges in every
   consuming site, and a site with `script-src 'self'` blocks it outright, losing every icon with
   no remedy short of a fork. Vendor lucide as a package static file at a pinned version, next to
   `studio.css` and `studio.js`, and record the version and upstream URL.
2. Add a block at the top of `body` and an id on `main`. A skip link must be the first element of
   the body and needs a target; a site running accessibility checks over its Studio states cannot
   supply either through a child template today.
3. Decide whether the new blocks belong in the E001 contract. If a site can now override a block in
   a way that breaks the page, the check is where that is caught.

Verification
- A site overriding nothing renders exactly as before, measured rather than asserted.
- `grep -rn "unpkg\|@latest" community_base/` finds nothing.
- The AI-Shipping-Labs suite is unaffected.

Done when
- [ ] no page loads a script from a third-party origin
- [ ] a site can supply a skip link and a main target without copying the shell

## C7.21 Release 0.5.1

Repository: community-base. Depends on: C7.19, C7.20. Freeze required: no.

Goal: the fixes DTC needs are consumable. `scripts/check_community_base_source.py` in both sites
accepts only a `vX.Y.Z` tag, so anything on package `main` is unreachable to a site by design
(D0.2). Three things are currently stranded there: the #279 content-block fix and its E001 check,
C7.17's headerless-landing fallthrough, and C7.19 and C7.20.

C7.17 matters more than it looks for DTC specifically: its roughly 35 destinations sit above the
default `STUDIO_NAV_COLLAPSE_THRESHOLD` of 24, so without the fallthrough its Studio landing page
opens on an entirely closed sidebar.

Steps
1. Follow playbook P15. A published tag is immutable: never move one, never delete and recreate one.
2. `uv run python scripts/check_release_tag.py` before `uv build`, so the tag cannot disagree with
   `pyproject.toml` and `community_base/__init__.py`.
3. Note in the CHANGELOG that v0.5.0 carried the C7.19 regression, so a site reading only the
   changelog learns it without finding this file.

Done when
- [ ] the tag exists, the cross-repository check is green against it, and D2.1a can pin it

## C7.22 Audit the package for assumptions only AI-Shipping-Labs satisfies

Repository: community-base. Depends on: nothing. Freeze required: no.

Goal: find the rest of the class of defect C7.19 belongs to, before a second site pays for each one
separately.

The package has had exactly one adopting site, so every behaviour that happens to match how
AI-Shipping-Labs is configured is untested against any other shape, and the package's own suite
cannot see the gap because its test settings were written alongside that site. C7.19 is the
archetype: DataTalksClub declares `app_name` on its Studio URLconf, AI-Shipping-Labs does not, and
the two halves of the package disagreed with each other for every namespaced route without raising
anything. C7.20 is two more of the same shape.

Steps
1. Enumerate from the package: every place it reads something about the site and would behave
   differently, or silently do nothing, depending on the answer. URL and route-name handling,
   template block and override contracts, static asset assumptions, settings read through
   `conf` and what a missing or differently-shaped value does, the access policy and authorizer
   hooks, app-label and table assumptions, anything enumerating `_meta.get_fields()`,
   `INSTALLED_APPS` or the URLconf, anything comparing a name or key by string equality.
2. Enumerate from the other site: where DataTalksClub's real configuration differs in a way the
   package touches.
3. Classify every candidate by evidence. Reproduced, or clearly dependent but not reproduced, or
   checked and fine. The cleared list is what makes the audit worth trusting.

This issue fixes nothing except by adding tests. Each finding that needs a fix gets its own issue;
a branch that fixes everything at once is unreviewable.

Done when
- [ ] the audit is in `docs/plan/evidence/`, ranked with silent wrong behaviour above loud errors
- [ ] every shape confirmed handled is pinned by a test that would fail if it regressed
- [ ] the audit says where it stopped

## C7.23 D37: the null media backend returns a site-absolute URL

Repository: community-base. Depends on: nothing. Freeze required: no. Decision D37.

Goal: the default media backend produces a URL the renderer keeps.

`NullMediaStore` returned the repository path as the URL, while the sanitiser admits an `img src`
only when it is site-absolute or an absolute `http(s)` URL. Every site on the default backend
therefore stored synced images with a source the renderer then dropped, and nothing said so until
someone looked at a page. Filed after the fact so the decision has a landing issue: D37 was ruled
and implemented in the same session, which is the opposite failure from D34, D38 and D39, and it
left the decision with nowhere to point.

Steps
1. Return the repository path under `CONTENT_SYNC_NULL_MEDIA_URL_PREFIX`, percent-quoted.
2. Refuse a path that escapes the checkout rather than producing a URL for it.

Done when
- [ ] a behaviour change to a default ships with its own test and a CHANGELOG line

## C7.24 Wire up the config override reset and the restart warning

Repository: community-base. Depends on: nothing. Freeze required: no.

Goal: two config capabilities that exist in the code and reach no operator start working, or stop
pretending to exist.

Found by the 2026-09-18 survey of leftover branches. `config/service.py` declares
`unset(key, actor_ref, reason)`, and `config/registry.py` carries `requires_restart` through
`declare()` onto the schema. Neither reaches a view, a template or a test: `unset` has no caller
and no test at all, and `requires_restart` is written and never read. So an operator who sets an
override in Studio has no way to clear it back to the fallback, and a setting whose change needs a
restart warns nobody. A declared field that nothing reads is worse than a missing one, because it
reads as a working feature in review.

A stale branch, `a02-config-maintenance`, implements both against the 0.3.0-era package. It is not
merged and should not be: its only change to shared state regresses the `MAIL_PREFERENCE_RESOLVER`
default from `community_base.accounts.preferences.resolve_mail_preference` back to the pre-accounts
`community_base.mail.preferences.allow_all`, and being forked at the 0.3.0 release point it also
collides on the changelog, the version, the lockfile and the version-count assertions in
`tests/test_smoke.py` and `tests/config/test_registry.py`. Read it for the shape of the UI and
write the code against current main.

Steps
1. Decide first whether both are wanted. Removing `unset` and `requires_restart` is a legitimate
   outcome and is better than leaving them declared and unreachable. Say which and why.
2. If kept: a Studio control that clears an override back to its fallback, through `unset`, with
   the same audit trail a set gets.
3. If kept: surface `requires_restart` where the operator changes such a setting, at the moment of
   the change rather than in a page they may not read.

Verification
- `unset` has a test that proves the value falls back and the change is audited.
- A setting declared `requires_restart=True` shows the warning; one declared without it does not.

Done when
- [ ] no field in the config schema is written by `declare()` and read by nothing

## C7.25 A site's base template must honour the block contract, and something must check it

Repository: community-base. Depends on: C7.22. Freeze required: no.

Goal: a package page mounted by a site renders its content, or the site is told at check time that
it will not.

`docs/02-architecture.md` section 5 has named this contract since the architecture was written and
nothing has ever enforced it. Django drops content for an undefined block silently: no exception,
no warning, nothing in the logs. So a site whose `base.html` omits a block the package fills serves
the site chrome with the package's content missing, and the page looks fine.

Both sites are affected today, in opposite directions. AI-Shipping-Labs defines `body` rather than
`content` and defines no `extra_js`, so the mounted public unsubscribe page returns 200 with 21kB
of chrome and no form. DataTalksClub defines `content` but neither `meta_description` nor
`page_head_metadata`, so the `noindex, nofollow` on those pages silently disappears. 41 package
templates extend `base.html` across five contracted blocks, so this is a class rather than two
pages.

Severity note for the unsubscribe page specifically: it is public rather than superuser-only, so
leaving it blank until a fix lands is a weaker option than it would be for a Studio page.
AI-Shipping-Labs confirmed its outbound mail carries its own unsubscribe route rather than the
package one, so no member is stuck, but a public route serving an empty body is still a defect.

Steps
1. Enumerate the blocks the package's templates fill and write the contract down as data rather
   than prose, so a check can read it.
2. Add a Django system check that fails when an installed package app's templates fill a block the
   site's base does not define. Decide whether it is an error or a warning and say why; an error a
   site cannot start with may be right here, given the failure is otherwise invisible.
3. Decide whether the package should shrink its block surface instead. Five contracted blocks
   across 41 templates is a wide contract to impose on an adopting site, and a narrower one may be
   the better fix than a check that enforces a wide one.

Verification
- A test site whose base omits `content` fails the check, naming the block and a template.
- A test site whose base defines every contracted block passes.

Done when
- [ ] no package template can fill a block a site does not define without something saying so

## C7.26 Studio impersonation assumes ModelBackend and literal paths

Repository: community-base. Depends on: C7.22. Freeze required: no.

Goal: impersonation works on a site with its own authentication backend, and its safety guard
stops depending on where Studio is mounted.

`community_base/studio/impersonation.py` line 13 hardcodes `AUTH_BACKEND` to
`django.contrib.auth.backends.ModelBackend`. DataTalksClub's `AUTHENTICATION_BACKENDS` is
`["accounts.backends.DurableAccountBackend"]` and nothing else. The POST returns 302 and the
session records the target, and then the next request cannot load the backend, so the operator
becomes anonymous and is bounced to login, and `stop` cannot restore them.

Lines 14 to 20 hold `SENSITIVE_RETURN_PREFIXES` as literal paths. A site that mounts Studio at
`manage/` or `backoffice/` gets `/manage/users/` and `/backoffice/users/` past the guard that
exists to block `/studio/users/`. The guard is doing nothing on such a site while appearing to.

Steps
1. Resolve the backend from the site's configured `AUTHENTICATION_BACKENDS` rather than naming one.
2. Derive the sensitive prefixes from the mounted Studio URLconf rather than from literals.

Done when
- [ ] impersonation works on a site with exactly one non-default authentication backend
- [ ] the return guard refuses the same pages regardless of where Studio is mounted

## C7.27 Three settings-shape defects the package handles inconsistently

Repository: community-base. Depends on: C7.22. Freeze required: no.

Goal: the package treats a missing or differently-shaped setting the same way everywhere, and
loudly.

Three instances found by C7.22, grouped because the fix is one decision applied three times.

1. `community_base/accounts/mail_context.py` line 10 and `community_base/events/mail_context.py`
   line 15 read `SITE_URL`, which defaults to the empty string and which AI-Shipping-Labs never
   sets. Verify, reset, change and manage links in outbound mail become relative paths and are
   useless in an email client. `calendar.py` and `jobs/relay.py` raise on the same empty value, so
   the package already disagrees with itself about whether an empty `SITE_URL` is acceptable.
2. `community_base/studio/studio_filters.py` line 199 iterates `STUDIO_EXTRA_CSS`. Set to a single
   path string rather than a list, it iterates as characters and emits 15 stylesheet links. Silent
   on AI-Shipping-Labs, a `ValueError` under DataTalksClub's manifest storage.
3. `community_base/curriculum/apps.py` line 16 tests `"community_base.events" in set(INSTALLED_APPS)`.
   That is False for the AppConfig-path spelling Django accepts everywhere, so the curriculum
   Studio section and its API views silently never register. Nine sibling gates use
   `apps.is_installed()` and are correct; this is the one raw membership test.

Steps
1. Decide the rule: a setting whose absence breaks a feature raises at startup rather than
   degrading. Apply it to `SITE_URL` and say what a site that legitimately has no site URL does.
2. Accept a string where a sequence is expected, or refuse it. Do not iterate it.
3. Replace the raw membership test with `apps.is_installed()`.

Done when
- [ ] no package module reads a setting whose empty value silently changes behaviour
- [ ] no package module tests `INSTALLED_APPS` membership by string

