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
and none is `undecided`.

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
| Capability declaration for Studio and admin API | DTC has 61, AISL has none | absorb DTC's pattern into `api` and `studio` | undecided | |
| Optimistic concurrency and append-only model bases | DTC only | move `RevisionedModel` and `AppendOnlyManager` into the kernel | undecided | |
| Custom session model | AISL only | move `AccountSession` into package `accounts` | undecided | |
| Article storage shape | AISL concrete model, DTC synced document | pick one shape for a shared article model | undecided | |
| Podcast, FAQ, people, sponsors, event Q and A | DTC only | stays DTC-owned unless the owner asks | site-owned | none |
| Payments, sprint plans, CRM, book club, analytics, triggers | AISL only | stays AISL-owned | site-owned | none |

Steps
1. Keep the table current. A row moves to `accepted` only with an owner decision recorded in
   `docs/01-decisions.md`.
2. When a row is accepted, add its issues to this phase, run `python scripts/plan.py sync`, and put
   the issue ids in the row.
3. Mirror this issue in each site repository only when that site has an accepted row.

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

Repository: DataTalksClub/website. Depends on: C7.2. Decision D16.

Goal: DTC keeps its wiki and documentation exactly as they are for readers, served by the package
app instead of `content`'s own projections.

Read first
- DTC `AGENTS.md` and `_docs/PROCESS.md` first; they govern the work.
- `content/wiki_content.py`, `docs_projection.py`, `docs_presentation.py`, `content/route_contracts.py`.

Steps
1. Point `content/sync_parsers/podwiki.py` and `docs.py` at the package app's models.
2. Keep the public routes, templates and the knowledge graph in `content`. Only the storage and
   hierarchy resolution move.
3. Verify the pinned route inventories in `content/route_contracts.py` and `sitemap_contract.py`
   are unchanged. A moved page is a regression, not an improvement.
4. Remove the superseded projection modules once the routes are green.

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
