# Phase 0: package repository, kernel, config, API layer

Goal: the package exists, is installable from a git tag, has CI and a test project, and ships its
first shared behaviour: the runtime configuration registry with a Studio page and an admin API.
Both sites read every runtime setting through the package at the end of this phase.

No freeze. No production data moves; configuration rows are copied by a data migration and the
old tables are removed one release later.

Exit criteria:

- `uv add "community-base @ git+https://github.com/DataTalksClub/community-base@v0.1.0"` works in
  an empty project and `python -c "import community_base"` succeeds.
- In AISL and in DTC, `grep -rn "integrations.config\|core.operational_settings\|core.site_settings" --include=*.py . | grep -v tests | grep -v migrations`
  prints nothing except the shim modules named in A0.2 and D0.1.
- `GET /api/v1/settings` returns the same JSON shape on both sites' development environments.

## C0.1 Create the package repository skeleton

Repository: community-base. Depends on: nothing.

Goal: a runnable, testable, releasable empty package.

Read first
- `~/git/ai-shipping-labs/pyproject.toml` (ruff and pytest configuration to mirror)
- `~/git/ai-shipping-labs/asl_cli/pyproject.toml` (hatchling packaging precedent)
- `~/git/dtc-website/website/settings/test.py` (deterministic SQLite test settings precedent)

Steps
1. Create `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "community-base"
version = "0.0.1"
description = "Shared Django apps for DataTalks.Club community sites"
requires-python = ">=3.13"
dependencies = [
    "django>=6.0,<6.1",
    "django-allauth>=65.10,<66",
    "requests>=2.32,<3",
    "pyjwt>=2.10,<3",
    "cryptography>=46,<51",
    "markdown>=3.10,<4",
    "nh3>=0.3,<1",
    "pyyaml>=6,<7",
    "python-frontmatter>=1.1,<2",
]

[project.optional-dependencies]
django_q = ["django-q2>=1.9,<2", "croniter>=6,<7"]
ses_local = ["boto3>=1.42,<2"]
ai = ["anthropic>=0.105"]
zoom = []
s3 = ["boto3>=1.42,<2"]

[dependency-groups]
dev = ["pytest>=8.4,<10", "pytest-django>=4.11,<5", "ruff>=0.12,<1", "psycopg[binary]>=3.2,<4"]

[tool.hatch.build.targets.wheel]
packages = ["community_base"]

[tool.ruff]
target-version = "py313"
line-length = 100
exclude = ["*/migrations/*"]

[tool.ruff.lint]
select = ["B", "DJ", "E", "F", "I", "UP"]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "testproject.settings"
pythonpath = ["."]
python_files = ["test_*.py"]
```

2. Create `community_base/__init__.py` with `__version__ = "0.0.1"`.
3. Create `testproject/` with `manage.py`, `settings.py` (SQLite at `testproject/db.sqlite3`,
   `INSTALLED_APPS` with the Django contrib apps, `allauth`, and every `community_base.*` app
   that exists; `COMMUNITY_BASE = {"SITE_KEY": "test", "ACCESS_POLICY": "community_base.kernel.access.OpenPolicy", "JOBS_BACKEND": "sync", "MAIL_BACKEND": "memory"}`;
   `TEMPLATES` with `DIRS = [BASE_DIR / "testproject" / "templates"]`), `urls.py`, and
   `templates/base.html` that defines the contract blocks from `docs/02-architecture.md` section 5.
4. Create `tests/conftest.py` (pytest-django), `tests/test_smoke.py` asserting the version
   string, and `tests/test_boundaries.py` that walks `community_base/` and fails if any file
   imports `payments`, `plans`, `content`, `courses`, `website`, `crm`, `bookclub`, `analytics`,
   `triggers`, `integrations`, `management_api`, `management_auth`, `studio_courses`.
5. Create `Makefile` with targets `install` (`uv sync --all-extras`), `lint`, `format`, `check`
   (`ruff check`, `ruff format --check`, `testproject/manage.py check`, `makemigrations --check --dry-run`),
   `test` (`pytest`), `migrate-fresh` (delete `testproject/db.sqlite3`, `migrate`).
6. Create `.github/workflows/ci.yml`: on push and pull request, Python 3.13, `uv sync --all-extras`,
   `make check`, `make test`. Add `release.yml`: on tag `v*`, `uv build`, create a GitHub release
   with the wheel attached.
7. Create `CHANGELOG.md` with an `Unreleased` section.
8. Copy `_docs/PROCESS.md` from AISL to `docs/PROCESS.md`, replace repository names, remove
   AISL-only sections (production data access, Playwright shards). Keep the agent roles and the
   issue lifecycle.

Verification
- `make install && make check && make test` -> all pass, 2 tests.
- `uv build` -> `dist/community_base-0.0.1-py3-none-any.whl` exists.
- In a temporary directory: `uv init tmpproj && cd tmpproj && uv add ../community-base && uv run python -c "import community_base; print(community_base.__version__)"` -> `0.0.1`.
- Push a branch and confirm CI is green.

Done when
- [ ] all verification lines pass
- [ ] `v0.0.1` tag pushed and the release contains the wheel

Docs
- `README.md` status line changed from "planning" to "Phase 0 in progress".

## C0.2 Kernel: configuration dictionary, hooks, access policy, staff decorators

Repository: community-base. Depends on: C0.1.

Goal: the extension points every later app relies on.

Read first
- `~/git/ai-shipping-labs/content/access.py` (levels, labels)
- `~/git/ai-shipping-labs/studio/decorators.py`
- `~/git/dtc-website/core/services.py`, `core/context.py`, `core/redaction.py`, `core/idempotency.py`
- `~/git/dtc-website/_docs/architecture/shared-primitives.md`

Steps
1. `community_base/kernel/conf.py`: `DEFAULTS` dict with every documented key and a `get(name)`
   that merges `settings.COMMUNITY_BASE` over defaults and raises `ImproperlyConfigured` for an
   unknown key. Keys at this point: `SITE_KEY`, `ACCESS_POLICY`, `JOBS_BACKEND`, `MAIL_BACKEND`,
   `STUDIO_TITLE`.
2. `community_base/kernel/hooks.py`: `resolve(dotted_path)` with caching, and
   `Hook(name, default)` descriptor used by apps to expose site-overridable callables.
3. `community_base/kernel/access.py`: constants `LEVEL_OPEN=0`, `LEVEL_REGISTERED=5`,
   `LEVEL_BASIC=10`, `LEVEL_MAIN=20`, `LEVEL_PREMIUM=30`; `AccessPolicy` protocol with
   `user_level(user) -> int`, `can_access(user, required_level) -> bool`,
   `level_label(level) -> str`; `OpenPolicy` (every user level 0, anonymous 0, access when
   required level is 0 or user is authenticated and required is 5) and `RegisteredOnlyPolicy`
   (same); module functions `can_access(user, obj_or_level)` reading `obj.required_level` when
   given an object, resolving the policy from `ACCESS_POLICY`.
4. `community_base/kernel/decorators.py`: `staff_required`, `superuser_required` copied from
   AISL, redirect target read from `settings.LOGIN_URL`.
5. `community_base/kernel/redaction.py`, `context.py`, `services.py`, `idempotency.py` copied from
   DTC `core` with imports rewritten and DTC-specific canaries removed. Keep their tests.
6. `community_base/kernel/apps.py` with label `cb_kernel`; add to `testproject`.
7. `tests/kernel/`: policy tests (anonymous denied at 5, authenticated allowed at 5, level 10
   denied under `OpenPolicy`), decorator tests, redaction tests moved from DTC.

Verification
- `make check && make test` -> pass.
- `uv run python -c "from community_base.kernel.access import can_access; print(can_access(None, 0), can_access(None, 5))"` -> `True False`.

Done when
- [ ] every kernel module has at least one test
- [ ] `docs/02-architecture.md` section 2 keys match `conf.DEFAULTS` exactly

Docs
- `community_base/kernel/README.md` listing every `COMMUNITY_BASE` key with type and default.

## C0.3 Config app: registry, storage, cache, Studio page, import and export

Repository: community-base. Depends on: C0.2.

Goal: one runtime configuration framework that replaces both sites' implementations.

Read first
- `~/git/ai-shipping-labs/integrations/config.py` (resolution order, stamp-based cross-process cache)
- `~/git/ai-shipping-labs/integrations/settings_registry.py` (key metadata shape)
- `~/git/ai-shipping-labs/studio/views/settings.py` and `templates/studio/settings/`
- `~/git/dtc-website/core/operational_settings.py` (`_declare`, typed values, validation)
- `~/git/dtc-website/core/operational_settings_service.py` (audit on change, revision)

Steps
1. Models (`label = "cb_config"`): `Setting(key unique, value JSON, value_type, source, updated_at)`
   and `SettingChange(setting key, old value redacted flag, new value redacted flag, actor_ref,
   reason, created_at)`. Secrets are stored encrypted with `cryptography.Fernet` using
   `settings.SECRET_KEY`-derived key, exactly as AISL does for trigger secrets
   (`~/git/ai-shipping-labs/triggers/` for the helper).
2. `registry.py`: `declare(...)` per playbook P10, `groups()`, `definitions()`. Registration
   happens at import time from each app's `settings_keys.py`, imported in `AppConfig.ready()`.
3. `service.py`: `get(key, default=None)`, `is_enabled(key)`, `set(key, value, actor_ref, reason)`
   (writes `SettingChange`), `export()`, `import_(payload, actor_ref)`. Resolution order: DB
   override, environment variable, Django setting attribute when declared, default. Port the
   stamp cache from AISL unchanged, including the worker-process bypass.
4. Studio page at `community_base/config/templates/cb_config/studio_settings.html`, temporarily
   standalone (extends `base.html` through the contract) until Phase 2 adds the Studio shell.
   Views: list by group, save group, export JSON, import JSON. Source badge per key.
5. Admin API endpoints registered through `community_base.api` (C0.4): `GET /api/v1/settings`,
   `GET /api/v1/settings/{key}`, `PUT /api/v1/settings/{key}` with scope `settings.write`,
   `GET /api/v1/settings/export`, `POST /api/v1/settings/import`.
6. Tests: resolution order, secret masking in list and export, stamp invalidation across two
   processes simulated with two cache instances, change audit rows, API scope enforcement.

Verification
- `make check && make test` -> pass.
- `uv run python testproject/manage.py migrate` on a fresh database -> `cb_config` tables created.
- `uv run python testproject/manage.py runserver` and `GET /studio/settings/` with a staff session -> 200 with groups rendered.

Done when
- [ ] every AISL registry flag (`is_secret`, `multiline`, `optional`, `is_email`, `django_settings_fallback`, `docs_url`) has an equivalent in `declare`
- [ ] every DTC value type (`str`, `int`, `bool`, `json`, `list`) is supported

Docs
- `community_base/config/README.md`: how to declare keys, resolution order, Studio page, API.

## C0.4 API app: keys with scopes, bearer auth, OpenAPI, route registry

Repository: community-base. Depends on: C0.2.

Goal: one admin API foundation both sites build on (decision D9).

Read first
- `~/git/ai-shipping-labs/accounts/models/token.py`, `accounts/models/member_api_key.py`
- `~/git/ai-shipping-labs/api/safety.py`, `api/utils.py`, `api/openapi/builder.py`, `api/urls.py`
- `~/git/ai-shipping-labs/_docs/api.md`, `_docs/api-delete-policy.md`
- `~/git/dtc-website/management_auth/models.py`, `management_auth/policies.py`, `management_api/errors.py`

Steps
1. Model `APIKey` (`label = "cb_api"`): `id` (prefixed string like AISL `Token.id`), `user`
   FK to `AUTH_USER_MODEL`, `name`, `key_hash`, `lookup_prefix`, `scopes` JSON list,
   `created_at`, `last_used_at`, `revoked_at`, `last_used_ip_hash`, `kind` (`staff` or `member`).
2. `auth.py`: `bearer_required(scopes=...)` decorator resolving the key, checking revocation and
   scopes, binding `request.api_key` and `request.user`. Constant-time compare on the hash.
3. `registry.py`: `route(method, path, scope, summary, response, request=None)` collecting
   handlers; `urlpatterns()` building Django routes under a mount point; `openapi.py` building
   the document with apispec from the registry (port AISL's builder); management command
   `openapi --check` comparing with `api/openapi.json` committed in the site.
4. `errors.py`: one JSON error envelope `{"error": {"code", "message", "details"}}` (take DTC's
   codes), `safety.py` (AISL: body size, pagination bounds, delete policy).
5. Studio pages for API keys (create with one-time display, revoke), superuser only.
6. Tests: key create and revoke, scope denial, prefix lookup, OpenAPI check command, envelope.

Verification
- `make check && make test` -> pass.
- `curl -H "Authorization: Bearer <key>" http://127.0.0.1:8000/api/v1/settings` against
  `testproject` -> 200 JSON list; without header -> 401 envelope; wrong scope -> 403 envelope.

Done when
- [ ] `docs/api.md` in the package describes auth, scopes, envelope, pagination and the check command

Docs
- `community_base/api/README.md`

## C0.5 First release

Repository: community-base. Depends on: C0.2, C0.3, C0.4.

Steps
1. Playbook P15, package half, version `0.1.0`.

Verification
- `git ls-remote --tags origin v0.1.0` -> tag listed.

Done when
- [ ] release page shows the wheel and the changelog lines for C0.1 to C0.4

## A0.1 Add the package dependency and the local link targets

Repository: AI-Shipping-Labs/website. Depends on: C0.5.

Steps
1. `pyproject.toml`: add `community-base` dependency and `[tool.uv.sources]` git tag `v0.1.0`
   (`docs/02-architecture.md` section 4). Run `uv lock`.
2. `Makefile`: add `core-link` and `core-unlink` targets from section 4.
3. `.github/workflows/ci.yml`: add a step `grep -n 'path = "../community-base"' pyproject.toml && exit 1 || true`
   named "no local package link".
4. `INSTALLED_APPS`: add `community_base.kernel` after `django_q`.
5. `COMMUNITY_BASE` dictionary in `website/settings.py`: `SITE_KEY="aisl"`,
   `ACCESS_POLICY="content.access.TierAccessPolicy"` (created in A0.3), `JOBS_BACKEND="django_q"`,
   `MAIL_BACKEND="ses_local"`, `STUDIO_TITLE="AI Shipping Labs Studio"`.

Verification
- `uv sync && uv run python manage.py check` -> clean.
- `uv run python -c "import community_base; print(community_base.__version__)"` -> `0.1.0`.
- `make core-link && make core-unlink && git status --porcelain` -> empty.

Done when
- [ ] CI green with the new step

## A0.2 Replace the settings framework with the package config app

Repository: AI-Shipping-Labs/website. Depends on: A0.1. Freeze required: no.

Read first
- `integrations/config.py`, `integrations/settings_registry.py`, `integrations/models/` (the `IntegrationSetting` model)
- `studio/views/settings.py`, `api/views/integration_settings.py`
- every `from integrations.config import` site: `grep -rn "from integrations.config import" --include=*.py . | grep -v tests | wc -l`

Steps
1. Add `community_base.config` and `community_base.api` to `INSTALLED_APPS`; migrate.
2. Convert `INTEGRATION_GROUPS` to `declare(...)` calls in `integrations/settings_keys.py`,
   imported from `IntegrationsConfig.ready()`. One `declare` per key; keep `docs_url` values.
3. Data migration in `integrations` (playbook P6, first pull request): copy `IntegrationSetting`
   rows into `cb_config.Setting` with `value_type="str"` and `source="db"`.
4. Replace `integrations/config.py` body with a shim:
   `from community_base.config import get as get_config, is_enabled, clear_config_cache` plus a
   `DeprecationWarning` on import. Keep the module for one release.
5. Point the Studio settings URL at the package view; delete `studio/views/settings.py` and
   `templates/studio/settings/`. Point `/api/integration-settings` at the package endpoints and
   delete `api/views/integration_settings.py`. Update `asl_cli` commands that used the old path.
6. Second pull request after development deploy: delete `IntegrationSetting` model, migration
   removing the table, delete the shim, rewrite every import to `community_base.config`.

Verification
- After step 3 on the development database copy (P14): `Setting.objects.count()` equals the old
  `IntegrationSetting.objects.count()`; a secret key round-trips through `get`.
- `uv run python manage.py test integrations studio api --parallel 4` -> pass.
- `make test-affected` -> pass.
- After step 6: `grep -rn "integrations.config\|IntegrationSetting" --include=*.py . | grep -v migrations` -> nothing.

Done when
- [ ] Studio settings page renders all 17 groups with source badges on development
- [ ] `_docs/configuration.md` updated to name the package page and API

Docs
- `_docs/configuration.md`, `AGENTS.md` (the IntegrationSetting rule now names `community_base.config`)

## A0.3 Access policy hook

Repository: AI-Shipping-Labs/website. Depends on: A0.1.

Steps
1. Create `content/access_policy.py` with `TierAccessPolicy` implementing the kernel protocol using
   `user.tier.level` and active `TierOverride` (reuse the existing helper in `content/access.py`).
2. Make `content/access.py` constants import from `community_base.kernel.access` so there is one
   source for the level numbers.
3. Do not change call sites yet; they change per app in later phases (playbook P3).

Verification
- `uv run python manage.py test content --parallel 4` -> pass.
- `uv run python manage.py shell -c "from community_base.kernel.access import can_access; from accounts.models import User; u=User.objects.filter(tier__level__gte=20).first(); print(can_access(u, 20))"` -> `True` on the development copy.

Done when
- [ ] policy has unit tests for override expiry and anonymous user

## D0.1 Add the package and replace the settings frameworks

Repository: DataTalksClub/website. Depends on: C0.5.

Read first
- `core/operational_settings.py`, `core/operational_settings_service.py`, `core/site_settings.py`, `core/settings_batch.py`
- `studio/views.py` (settings view), `management_registry.py` (settings capabilities)

Steps
1. Same as A0.1 steps 1 to 4 with `SITE_KEY="dtc"`, `ACCESS_POLICY="community_base.kernel.access.RegisteredOnlyPolicy"`,
   `JOBS_BACKEND="relay"`, `MAIL_BACKEND="relay"`. Add the `COMMUNITY_BASE` dict to
   `website/settings/base.py`; the deployed settings modules add Relay keys in Phase 1.
2. Convert every `_declare(...)` in `core/operational_settings.py` and every site setting in
   `core/site_settings.py` to `community_base.config.registry.declare` in `core/settings_keys.py`.
3. Data migration copying `OperationalSetting` rows into `cb_config.Setting` keeping
   `value_type`; `SettingChange` rows from the existing history table if one exists.
4. Replace the Studio settings view with the package view; remove the settings capabilities from
   `management_registry.py`; mount `community_base.api` at `/api/v1/` in `website/urls.py`
   alongside `management_api` (which keeps its other routes for now).
5. Second pull request: delete `OperationalSetting`, `core/operational_settings*.py`,
   `core/site_settings.py`, `core/settings_batch.py`, and their tests that moved to the package.

Verification
- `uv run pytest core studio -q` -> pass.
- On the development database copy: counts match; `GET /api/v1/settings` with a `cb_api` key
  -> 200.
- `grep -rn "operational_settings\|site_settings" --include=*.py . | grep -v migrations` -> nothing after the second pull request.

Done when
- [ ] `_docs/specs/06-studio-and-admin-api.md` Studio "Site" section names the package settings page

Docs
- `_docs/architecture/app-boundaries.md` (core no longer owns settings), `_docs/specs/06-studio-and-admin-api.md`

## D0.2 Site CI guard and pin bump workflow

Repository: DataTalksClub/website. Depends on: D0.1.

Steps
1. Add the "no local package link" CI step (A0.1 step 3).
2. Add `.github/workflows/bump-community-base.yml`: weekly, opens a pull request that updates the
   tag to the latest release (uses `gh release view --repo DataTalksClub/community-base` and
   `uv lock --upgrade-package community-base`). Same workflow copied to AISL in A0.1's follow-up.

Verification
- Manually trigger the workflow -> a pull request opens or the run says "already latest".

Done when
- [ ] both sites have the guard and the bump workflow
