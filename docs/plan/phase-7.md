# Phase 7: site convergence

Goal: integrate the two sites where integration is worth it. Phases 0 to 6 move capabilities that
both sites already had into the package. This phase decides the remaining cases, where one site has
a capability the other does not, or where the two solved the same problem differently, and either
brings both onto one implementation or records that the difference stays.

Source: `docs/plan/evidence/site-convergence-analysis-2026-09-16.md`. Decisions D16, D17 and D18.

Freeze: none expected. Every issue here adds a capability or removes an unused one; none moves a
production table between sites.

Depends on: 5 for the shared curriculum and coursework apps. The knowledge-base issues depend only
on the content sync engine and can start once `C7.1` fixes their shape.

Exit criteria:

- Both sites serve a wiki and a documentation section from the same package app, with site-owned
  parsers and site-owned public templates.
- The candidate table in `C7.1` has no row left in state `undecided`.
- No shared app carries a legacy path, alias or redirect model (decision D17).

## C7.1 Site convergence umbrella

Repository: community-base. Depends on: nothing.

Goal: one place that records, for every capability the two sites do not share today, whether it
converges, stays site-owned, or is still undecided. This issue owns the table, not the code. Each
accepted row becomes its own issue.

This is an index issue. It closes when every row is `accepted` with a sub-issue, or `site-owned`,
and none is `undecided`. A `deferred` row is decided, not open.

Read first
- `docs/plan/evidence/site-convergence-analysis-2026-09-16.md`, sections 4 and 5.
- `docs/01-decisions.md`, D16, D17 and D18.

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
- [ ] no row is in state `undecided`
- [ ] every `accepted` row names at least one issue that is `done`

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

Issue numbers C7.7 to C7.12 are reserved for the unified content format work proposed in
`docs/plan/evidence/unified-content-format-2026-09-17.md`. The two issues below take C7.13 and
C7.14 so that reservation stays intact.

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
