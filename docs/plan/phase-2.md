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

## C2.1 Studio shell

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
4. Management command `studio_routes --check`: every URL name under the Studio mount must be in
   exactly one destination, in `section_only_routes`, or in `routes_without_home`; prints the
   offenders and exits 1.
5. Templatetags from `studio_filters.py` that are generic: `studio_list_filter`,
   `studio_empty_state`, `studio_status_badge`, `studio_list_action`, `studio_header_actions`,
   `studio_overflow_menu`, pager, `operator_date*`, `studio_list_class`, `studio_action_class`,
   `model_name`, `dict_get`. AISL-specific tags (tier pills, SES explain, UTM presets) stay in
   AISL.
6. Global search: registry of providers `register_search_provider(name, callable)`; the view
   merges results. Dashboard: registry of card providers.
7. Impersonation: port AISL `impersonate.py` (start, stop, banner) guarded by `superuser_required`
   and audited through a hook `STUDIO_AUDIT_WRITER`.
8. Re-home the standalone Studio pages from Phase 0 and 1 (config, API keys, jobs, mail) onto
   the shell and register their sections (`Operations`).
9. Tests: registry partition check, active state for a deep route, templatetags, impersonation
   guard, base renders in `testproject`.

Verification
- `make css-build && git status --porcelain community_base/studio/static` -> only intended changes.
- `make check && make test` -> pass.
- `uv run python testproject/manage.py studio_routes --check` -> `OK`.
- `testproject` `/studio/` with a staff session -> 200, sidebar shows `Operations` with Settings,
  API keys, Jobs, Mail.

Done when
- [ ] `community_base/studio/README.md` documents registration, blocks, templatetags, the CSS build

## C2.2 Users management in Studio

Repository: community-base. Depends on: C2.1.

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

Repository: community-base. Depends on: C1.5, C2.1.

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

Repository: community-base. Depends on: C2.1, C2.2, C2.3. Playbook P15.

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

## D2.1 Mount the Studio shell and re-home DTC Studio pages

Repository: DataTalksClub/website. Depends on: C2.4.

Read first
- `templates/studio/base.html`, `studio/views.py`, `studio/urls.py`, `studio_courses/`,
  `management_registry.py`, `accounts/studio_authorization.py`, `accounts/studio_roles.py`.

Steps
1. Install `community_base.studio`. Delete `templates/studio/base.html`; DTC Studio templates
   extend `community_base/studio/base.html`. Keep DTC's `authorize_studio_request` roles by
   implementing the kernel hook `STUDIO_AUTHORIZER` (default: `is_staff`).
2. Register sections: Site (settings, navigation, sponsors), Access (API keys from the package,
   credentials until `management_api` migrates), Audit, Events (identities, historical totals,
   Q&A), Courses (all `studio_courses` pages).
3. Remove the Studio adapter half of `management_registry.py`; `management_api` keeps its routes
   until its endpoints are re-declared through `community_base.api` in later phases.
4. Exempt Studio routes from the public-page inline-stylesheet test; keep the test for public
   pages.

Verification
- `uv run python manage.py studio_routes --check` -> `OK`.
- `uv run pytest studio studio_courses -q` -> pass; accessibility Playwright markers for Studio
  pass.

Done when
- [ ] `_docs/design/design-system.md` states that Studio uses the package design (D12)

## D2.2 Content sync per decision #226

Repository: DataTalksClub/website. Depends on: C2.4. Split into three pull requests.

Read first
- `content_sync/` (adapters, webhook), `content/` (models, `services.py` release graph),
  `_docs/specs/03-github-content-and-people.md`, `_docs/specs/open-decisions.md` decision 1.

Steps
1. D2.2a: install `community_base.content_sync`; write parsers for articles and people; keep the
   old pipeline running for the other types; compare row counts per type.
2. D2.2b: parsers for podcast and books; events are excluded (Phase 4 makes them database
   authored).
3. D2.2c: parsers for docs, FAQ and podwiki; delete `content_sync/`, the `ContentRelease`,
   `ActiveContentPath`, `FrozenReleaseChild` models and `content/services.py` release graph;
   route resolution reads the synced rows directly with the existing draft filter.

Verification per pull request
- `sync_content --from-disk <checkout>` on a fresh database -> counts per type equal to the old
  pipeline's counts recorded in D2.2a.
- `uv run pytest content -q` -> pass; the public URL compatibility test suite
  (`_docs/compatibility/`) passes.

Done when
- [ ] `_docs/specs/01-platform-architecture.md` "Content refresh" section rewritten to the direct-upsert workflow
