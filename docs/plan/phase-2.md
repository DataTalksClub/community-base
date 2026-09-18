# Phase 2: Studio shell, users management, content sync engine

Goal: one Studio shell that both sites mount, with sections registered by apps; users management
pages that work with any user model; one GitHub content sync engine with per-site parsers. DTC's
decision #226 is implemented by installing the engine.

Freeze: none. Only additive tables (`cb_content_sync`) and data copies.

Exit criteria:

- Neither site has `templates/studio/base.html`: `ls ~/git/*/templates/studio/base.html` prints
  only errors.
- `manage.py studio_routes --check` passes on both sites.
- Both sites sync content through `community_base.content_sync`; AISL's
  `integrations/services/github_sync/` and DTC's `content_sync/` directories are gone.

## C2.1a Studio shell, registry and security

Repository: community-base. Depends on: C1.5.

Read first
- `~/git/ai-shipping-labs/templates/studio/base.html` (1,288 lines), `studio/sidebar.py`,
  `studio/templatetags/studio_filters.py`, `studio/views/global_search.py`,
  `studio/views/impersonate.py`, `studio/views/dashboard.py`, `_docs/studio-conventions.md`,
  `assets/css/tailwind.css`, `tailwind.config.js`, `package.json`.
- `~/git/ai-shipping-labs/studio/tests/test_sidebar_routes.py` (route partition test to generalise).

Steps
1. Tailwind: copy `assets/css/tailwind.css`, `tailwind.config.js`, `package.json` into the package
   under `community_base/studio/assets/`; `content` globs point at
   `community_base/**/templates/**/*.html` and `community_base/**/*.py`. Build to
   `community_base/studio/static/community_base/studio.css` and commit the built file.
   `make css-build` in the package. A site that adds Studio templates with new utility classes
   runs its own build with the package's config as a preset (documented in the README).
2. Base template at `community_base/studio/templates/community_base/studio/base.html` from AISL's,
   with the sidebar rendered from the registry instead of hardcoded sections, `STUDIO_TITLE`
   from `COMMUNITY_BASE`, and the same block names AISL uses (`title`, `content`, `extra_head`,
   `extra_js`, `header_actions`). Also ship `studio/base.html` containing only
   `{% extends "community_base/studio/base.html" %}` so existing AISL templates need no change.
3. `registry.py`: `Section(slug, title, order, icon)`, `Destination(key, title, url_name,
   route_names, order, superuser_only=False)`, `register(section)`, `sections()`,
   `active_state(request)` (port of `sidebar.py` logic), `section_only_routes`,
   `routes_without_home`.
4. Templatetags from `studio_filters.py` that are generic: `studio_list_filter`,
   `studio_empty_state`, `studio_status_badge`, `studio_list_action`, `studio_header_actions`,
   `studio_overflow_menu`, pager, `operator_date*`, `studio_list_class`, `studio_action_class`,
   `model_name`, `dict_get`. AISL-specific tags (tier pills, SES explain, UTM presets) stay in
   AISL.
5. Global search: registry of providers `register_search_provider(name, callable)`; the view
   merges results. Dashboard: registry of card providers.
6. Impersonation: port AISL `impersonate.py` (start, stop, banner) guarded by `superuser_required`
   and audited through a hook `STUDIO_AUDIT_WRITER`.
7. Tests: registry primitives, active state for a deep route, templatetags, impersonation guard,
   search and dashboard provider aggregation, and the base rendering in `testproject`.

Verification
- `make css-build && git status --porcelain community_base/studio/static` -> only intended changes.
- `make check && make test` -> pass.
- `testproject` `/studio/` with a staff session -> 200 and the registered shell renders.

Done when
- [ ] `community_base/studio/README.md` documents registration, blocks, templatetags, the CSS build

## C2.1b Integrate existing package Studio screens

Repository: community-base. Depends on: C2.1a.

Steps
1. Re-home the standalone Studio pages from Phase 0 and 1 (config, API keys, jobs, mail) onto the
   shell and register their destinations in the `Operations` section.
2. Add `studio_routes --check`: every URL name under the Studio mount must be in exactly one
   destination, in `section_only_routes`, or in `routes_without_home`; print offenders and exit 1.
3. Generalise AISL's route partition test and cover a deep active destination for each mounted
   package app.

Verification
- `make check && make test` -> pass.
- `uv run python testproject/manage.py studio_routes --check` -> `OK`.
- `testproject` `/studio/` with a staff session -> 200, sidebar shows `Operations` with Settings,
  API keys, Jobs and Mail.

Done when
- [ ] every Phase 0 and 1 Studio page extends the shared shell and owns one registered destination

## C2.2 Users management in Studio

Repository: community-base. Depends on: C2.1b.

Read first
- `~/git/ai-shipping-labs/studio/views/users.py`, `member_notes.py`, `tags.py`, `templates/studio/users/`,
  `_docs/studio-user-statuses.md`.

Steps
1. Views working on `get_user_model()`: list with search, status filter, tag filter, export CSV;
   detail with panels; tags add and remove (tags stored through hook `USER_TAGS_ACCESSOR`
   defaulting to a `tags` JSON attribute when present); notes (`cb_studio.MemberNote` model).
2. Registries: `register_user_column(key, label, renderer)`, `register_user_badge(renderer)`,
   `register_user_panel(title, template, context_provider)`; AISL registers tier pill, Slack
   status, subscription summary; DTC registers course enrollments.
3. Import, merge and create flows wait for Phase 3 (they need the shared services).
4. Tests with `testproject` user.

Verification
- `make test tests/studio` -> pass; list page renders 25 rows with pager on 60 fixture users.

## C2.3 Content sync engine

Repository: community-base. Depends on: C1.5, C2.1a.

Read first
- `~/git/ai-shipping-labs/integrations/services/github_sync/` (all modules), `integrations/models/`
  (`ContentSource`, `SyncLog`, `WebhookLog`), `integrations/services/github.py`,
  `integrations/services/content_sync_queue.py`, `integrations/services/sync_observability.py`,
  `integrations/views/` webhook, `studio/views/sync.py`, `studio/views/content_sources.py`,
  `_docs/content.md`.
- `~/git/dtc-website/_docs/specs/open-decisions.md` decision 1 (the required workflow).

Steps
1. Models (`label = "cb_content_sync"`): `ContentSource`, `SyncLog`, `WebhookLog` as in AISL.
2. `parsers.py`: `register_parser(content_type, parser)` where a parser exposes
   `discover(checkout, source) -> iterable[SourceItem]` and `upsert(item, source, media) -> obj`
   and `soft_delete_missing(seen_keys, source)`; `dispatchers/` from AISL become the reference
   implementation that AISL registers for its types.
3. `orchestration.py` from AISL: source lock, immutable checkout at a commit, dispatch by
   registered parser, media upload through `media.py` (S3 client from config keys), `SyncLog`
   with counts and warnings, lifecycle transitions.
4. GitHub App client, webhook ingress with signature and delivery id dedup, per-source job
   handler `cb_content_sync.sync_source` (chunked: one job per source).
5. Management commands: `sync_content [--from-disk PATH] [--source SLUG]`, `seed_content_sources`.
6. Studio: sources list and edit, sync now, history, worker status; API endpoints for sources and
   sync triggers (port `api/views/sync_sources.py`).
7. Tests moved from AISL `integrations/tests/` for the engine (not the parsers).

Verification
- `make test tests/content_sync` -> pass, at least the engine test count from AISL.
- `testproject` with a fixture repository on disk and a fixture parser: `sync_content --from-disk`
  creates rows, second run reports zero changes, deleting a file soft-deletes the row.

## C2.4 Release 0.3.0

Repository: community-base. Depends on: C2.1b, C2.2, C2.3. Playbook P15.

## A2.1 Adopt the Studio shell

Repository: AI-Shipping-Labs/website. Depends on: C2.4.

Steps
1. Install `community_base.studio`. Delete `templates/studio/base.html`, `studio/sidebar.py`,
   `studio/decorators.py` (import from the kernel), the generic templatetags moved in C2.1,
   `studio/views/global_search.py`, `impersonate.py`, `dashboard.py` (dashboard cards become
   registered providers).
2. In each AISL app's `AppConfig.ready()` register its Studio section and destinations, copying
   the tuples from the deleted `sidebar.py` (playbook P9). Register search providers and dashboard
   cards.
3. Replace the AISL `test_sidebar_routes.py` with `manage.py studio_routes --check` in CI.
4. `make css-build` in AISL now uses the package preset and scans both trees.

Verification
- `uv run python manage.py studio_routes --check` -> `OK`.
- `uv run python manage.py test studio --parallel 4` -> pass; Playwright core Studio tests pass.
- Visual check on development: sidebar has the same eight sections in the same order.

Done when
- [ ] `_docs/studio-conventions.md` points at the package README for shell and registry rules

## A2.2 Users pages from the package

Repository: AI-Shipping-Labs/website. Depends on: A2.1.

Steps
1. Register tier pill, Slack status, subscription summary, bounce state as columns, badges and
   panels. Delete `studio/views/users.py` list, detail, export, tags, notes; keep `users/new`,
   `import`, `merge` until Phase 3. Data-copy notes into `cb_studio.MemberNote` (P6).

Verification
- Studio users list, detail, export render identically in Playwright screenshots except for
  ordering of registered panels.

## A2.3 Content sync through the package engine

Repository: AI-Shipping-Labs/website. Depends on: C2.4.

Steps
1. Install `community_base.content_sync`; copy `ContentSource`, `SyncLog`, `WebhookLog` rows
   (P6).
2. Move `integrations/services/github_sync/dispatchers/` to `content/sync_parsers/` and register
   them; delete the engine modules from `integrations/services/github_sync/`.
3. Point the webhook URL, `sync_content` and `seed_content_sources` commands, Studio sync pages
   and API sync endpoints at the package.

Verification
- `uv run python manage.py sync_content --from-disk ~/git/ai-shipping-labs-content` on a fresh
  database -> same counts per content type as before the change (record both in the PR).
- `make test-affected` -> pass.

## D2.1a Bump the package pin to v0.5.1 and pay its two costs

Repository: DataTalksClub/website. Depends on: C7.21.

Part 1 of 4 of the split of the former single Studio issue, one landing per part.

Goal: the pin moves from v0.4.7 to v0.5.1 on its own, so that the two things a pin bump breaks are
fixed by a change that is about the pin and nothing else. Measured at DTC `eeea8747`: the bump
alone takes `test-django-full` from green on those labels to 19 errors, none of them Studio work.

Read first
- `scripts/prod/import_shared_course_platform.py`, the `_mapping()` function and
  `_refuse_mapping_drift()` around line 297.
- `core/tests/test_deployment_workflow.py` lines 87-88 and 898-899.

Steps
1. Name `cb_curriculum.Unit.body_html_source` in the import mapping. v0.5.0 adds the field and the
   mapping does not name it, so `_refuse_mapping_drift()` raises `MappingCoverageDrift`: 18 of the
   19 errors, one root cause. The drift guard is working as designed; the mapping is what is stale.
2. Regenerate `STUDIO_COURSES_PYPROJECT_SHA256` and `SECURITY_REMEDIATED_UV_LOCK_SHA256`. These
   freeze the sha256 of `pyproject.toml` and `uv.lock`, so every pin bump breaks them by
   construction. Regenerate them from the files rather than editing them to whatever makes the test
   pass, and say in the pull request which files produced which hash.

Verification
- `uv run python scripts/check_community_base_source.py` names the v0.5.1 tag.
- `uv run python scripts/ci.py test-django-full` is green, or its failures are attributed to a
  cause that is neither the pin nor this change, with the attribution run recorded.

Done when
- [ ] the pin is v0.5.1 and no test asserts a hash of a file this change did not regenerate

## D2.1b Install and mount the Studio shell behind DTC's own shell

Repository: DataTalksClub/website. Depends on: D2.1a.

Part 2 of 4 of the split of the former single Studio issue.

Goal: the package Studio app is installed, mounted and registered, and `studio_routes --check`
reports `OK`, while DTC keeps rendering its own shell. Separating the mount from the cutover means
a broken sidebar and a broken page template cannot arrive in the same landing.

Read first
- `studio/urls.py`, which sets `app_name = "studio"`. C7.19 is what makes a namespaced Studio
  URLconf work at all; without it every registered destination is silently dropped.
- `studio/views.py`, `studio_courses/`, `accounts/studio_authorization.py`,
  `accounts/studio_roles.py`.
- The route inventory on the abandoned attempt, preserved at `rescue/issue-377-20260918`. Its
  section and route breakdown is still correct and is the most reusable thing it produced; its
  code is built on v0.3.4 and is not.

Steps
1. Install `community_base.studio`. Keep `templates/studio/base.html` for now.
2. Implement `STUDIO_AUTHORIZER` so DTC's `authorize_studio_request` roles keep deciding access.
3. Register sections: Site (settings, navigation, sponsors), Access (API keys from the package,
   credentials until `management_api` migrates), Audit, Events (identities, historical totals,
   Q&A), Courses (all `studio_courses` pages).
4. Retire `studio:home` against the package landing route, or say why it stays.

Verification
- `uv run python manage.py studio_routes --check` -> `OK`, with neither a claimed-but-not-mounted
  nor a mounted-but-unclaimed line.
- `uv run pytest studio studio_courses -q` -> pass.

Done when
- [ ] every DTC Studio route is claimed by exactly one registered destination
- [ ] the sidebar renders non-empty hrefs for all of them

## D2.1c Cut over to the package shell

Repository: DataTalksClub/website. Depends on: D2.1b, C7.20.

Part 3 of 4 of the split of the former single Studio issue.

Goal: DTC Studio templates extend the package shell and DTC's own shell is deleted, without
forking the package base. C7.20 is what makes this possible: until the shell carries a body-start
block, an id on `main` and a self-hosted icon set, the only way to satisfy DTC's skip link, its
accessibility registry and its `script-src 'self'` policy is a verbatim fork, which is the
anti-pattern this issue exists to end. The abandoned attempt forked 152 lines and its own header
comment predicted this.

Read first
- `templates/studio/base.html` and the 1-line override at
  `templates/community_base/studio/base.html`, whose comment already says D2.1 deletes it.
- `core/middleware.py`, the Content-Security-Policy, and
  `core/tests/test_non_identity_security.py` which asserts it.
- `core/accessibility_registry.py`, the registered Studio states.
- `templates/core/_site_shell_head.html`, the skip link every DTC page ships.

Steps
1. Delete `templates/studio/base.html` and the `templates/community_base/` override; DTC Studio
   templates extend `community_base/studio/base.html`.
2. Move DTC's admin CSS behind `STUDIO_EXTRA_CSS` and the shell's head block rather than into a
   fork.
3. Supply the skip link through the shell's body-start block and point it at the shell's own
   `main` id.
4. Exempt Studio routes from the public-page inline-stylesheet test; keep the test for public
   pages.
5. Update the accessibility registry and the browser contracts for the new markup.

Verification
- `uv run pytest studio studio_courses -q` -> pass; the accessibility Playwright markers for
  Studio pass.
- No file under `templates/community_base/` overrides the package shell.
- Desktop and mobile screenshots recorded in the pull request.

Done when
- [ ] `_docs/design/design-system.md` states that Studio uses the package design (D12)
- [ ] no page loads a script from a third-party origin

## D2.1d Remove the Studio adapter half of management_registry

Repository: DataTalksClub/website. Depends on: D2.1c.

Part 4 of 4 of the split of the former single Studio issue.

Goal: the Studio half of the adapter registry goes, now that the package registry owns navigation.
Scoped separately because it is a wide mechanical change with its own validation surface: 24
`studio=AdapterMetadata` declarations across 14 files, 13 attribute reads, the `studio` field on
`Capability` and its validator, and the management-parity check.

Steps
1. Remove the Studio adapter declarations, the `studio` field and its validation.
2. `management_api` keeps its routes until its endpoints are re-declared through
   `community_base.api` in a later phase.

Verification
- `uv run python scripts/ci.py django-check` reports management capability parity current.
- `uv run pytest -q` -> pass.

## D2.2a Content sync adoption: articles and people through the package engine

Repository: DataTalksClub/website. Depends on: C2.4. Part 1 of 3 of the split, one landing
per part; product decision #226 (direct upsert, no staged release graph).

Read first
- `content_sync/` (adapters, webhook), `content/` (models, `services.py` release graph),
  `_docs/specs/03-github-content-and-people.md`, `_docs/specs/open-decisions.md` decision 1.

Steps
1. Install `community_base.content_sync` (v0.3.0 already pinned): app registration, webhook and
   staff URL mounts, migrations, `seed_content_sources`.
2. Write site parsers for articles and people per the package parser contract (`discover` /
   `upsert` / `soft_delete_missing`, source-scoped).
3. Keep the old pipeline running for all other types; no model deletions in this part.

Verification
- `uv run python manage.py sync_content --from-disk <checkout>` on a fresh database: articles and
  people row counts equal to the old pipeline's counts; record both.
- `uv run pytest content -q` -> pass; the public URL compatibility suite (`_docs/compatibility/`)
  passes.

## D2.2b Content sync adoption: podcast and books

Repository: DataTalksClub/website. Depends on: D2.2a. Part 2 of 3 of the split, one landing
per part.

Steps
1. Write site parsers for podcast and books and register them with the package engine. Events are
   excluded (Phase 4 makes them database authored).

Verification
- `uv run python manage.py sync_content --from-disk <checkout>` on a fresh database: counts per
  type equal to the old pipeline's counts recorded in D2.2a.
- `uv run pytest content -q` -> pass; the public URL compatibility suite (`_docs/compatibility/`)
  passes.

## D2.2c Content sync adoption: docs, FAQ and podwiki

Repository: DataTalksClub/website. Depends on: D2.2b. Part 3 of 3 of the split, one landing
per part.

Scope corrected on 2026-09-18. This issue is the parser and reader cutover only. The retirement
that used to be step 2 moved to D2.2d, because the step as written was wrong in a way that would
have destroyed live code: `content_sync/` is DTC's live course-repository app (webhook, ingest,
snapshot, drafts, registration), not the staged pipeline. Only its `dtc_content/` subpackage was
staged, and that is already deleted.

Steps
1. Write site parsers for docs, FAQ and podwiki and register them with the package engine.
2. Route resolution reads the synced rows directly with the existing draft filter.

Verification
- `uv run python manage.py sync_content --from-disk <checkout>` on a fresh database: counts per
  type equal to the old pipeline's counts recorded in D2.2a.
- `uv run pytest content -q` -> pass; the public URL compatibility suite (`_docs/compatibility/`)
  passes.

## D2.2d Retire the staged content pipeline

Repository: DataTalksClub/website. Depends on: D2.2c, D7.1.

Goal: the staged release graph is deleted, now that nothing reads it. Split out of D2.2c on
2026-09-18 because it is a deletion of roughly 7,680 lines with its own migration and its own
rehearsal, and because it cannot start until D7.1 lands.

Why it waits for D7.1: the docs asset records have to be built in `content/docs_reader.py`, which
D7.1 introduces, not in `content/docs_projection.py`, which D7.1 deletes.

Read first
- `content/models.py`, the `ContentSource.active_release -> ContentRelease` foreign key with
  `PROTECT`, which is what blocks the deletion. No migration anywhere contains a `DeleteModel` yet.
- `scripts/build_public_projection.py`. It is NOT part of the staged pipeline and must survive:
  eleven live sync parsers and `content/public_records.py` import it. It was listed once in a
  dead-mechanism cluster and is not dead.
- `_docs/specs/01-platform-architecture.md`, the "Content refresh" section.

Steps
1. Build the docs asset records in `content/docs_reader.py`, replacing the file-backed
   `DOCS_ASSET_ROOT` projection.
2. Delete the `ContentRelease`, `ActiveContentPath` and `FrozenReleaseChild` models, the
   `content/services.py` release graph, `content/queries.py` and `catalogue.manifest()`, none of
   which has a non-test caller.
3. Rehearse the storage drop on a development copy per playbook P14 and record the counts.
4. Rewrite the "Content refresh" section. It is not a pure deletion: steps 1 to 3 of that section
   still describe the live course-repository ingest and stay. Only steps 4 to 10 are staged.

Verification
- `uv run pytest content -q` -> pass; the public URL compatibility suite (`_docs/compatibility/`)
  passes.
- The P14 rehearsal counts are recorded in the pull request.

Done when
- [ ] `_docs/specs/01-platform-architecture.md` "Content refresh" section rewritten to the direct-upsert workflow
- [ ] `scripts/build_public_projection.py` still exists and its importers still pass
