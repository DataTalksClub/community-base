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

Repository: community-base. Depends on: C0.4.

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
   Add `apispec` as an explicit package dependency.
4. `errors.py`: one JSON error envelope `{"error": {"code", "message", "details"}}` (take DTC's
   codes), `safety.py` (AISL: body size, pagination bounds, delete policy).
5. Studio pages for API keys (create with one-time display, revoke), superuser only.
6. Tests: key create and revoke, scope denial, prefix lookup, OpenAPI check command, envelope.
   Register a package fixture endpoint that requires `fixtures.read`; C0.4 does not depend on
   config routes.

Verification
- `make check && make test` -> pass.
- `curl -H "Authorization: Bearer <key>" http://127.0.0.1:8000/api/v1/fixtures/ping` against
  `testproject` -> 200 JSON; without header -> 401 envelope; wrong scope -> 403 envelope.

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

Repository: AI-Shipping-Labs/website. Depends on: C2.4.

Goal: install the released `v0.3.0` dependency and safe local tooling without activating shared
runtime apps. The owner assigned this preparation before the adoption-ready release; donor and
service gates still apply to later adoption.

Read first
- `pyproject.toml`, `uv.lock`, `Makefile`, `.github/workflows/ci.yml`,
  `.github/workflows/deploy-dev.yml`, `scripts/affected_tests.py`.
- `_docs/audits/2026-09-06-community-base-migration-plan.md` and the site's process.

Steps
1. Verify the remote `v0.3.0` tag and release wheel. Add `community-base>=0.3.0,<0.4` and
   `[tool.uv.sources] community-base = { git = "https://github.com/DataTalksClub/community-base", tag = "v0.3.0" }`.
   Run `uv lock`; record the resolved tag commit. Never pin untagged package main.
2. Add `core-link` and `core-unlink` with a dependency-file cleanliness precondition and a
   recoverable snapshot below `.tmp/`. Refuse repeated link or unlink without a snapshot.
   Restore only the captured dependency state; never discard unrelated caller edits.
3. Add a parsed TOML/lock guard requiring the approved tagged git source and matching lock entry.
   Reject path, editable, branch, missing-tag and mismatched sources with nonzero exit status.
   Wire it before dependency installation into both PR CI and `deploy-dev.yml` (main's workflow).
4. Verify link/unlink in a disposable checkout with the sibling package path explicitly supplied;
   dependency manifests return byte-identical, the restored pin passes, a local link fails.
5. Keep runtime settings and app lists unchanged. A0.3 creates the real access-policy hook before
   installing the kernel; A0.2 installs config/API. Do not reference a class that does not exist.

Verification
- `uv sync --locked` and `uv run python manage.py check` -> clean.
- `uv run python -c "import community_base; print(community_base.__version__)"` -> `0.3.0`.
- Guard negative fixtures -> nonzero; restored tag -> exit 0.
- `uv run python scripts/affected_tests.py --json` and `make test-affected` -> selected checks pass.
- Independent tester and PM acceptance, local merge/push and on-call verification follow site rules.

Done when
- [ ] the tagged dependency imports and no shared runtime app has been activated
- [ ] reversible link targets and fail-closed main CI guard pass focused tests
- [ ] site review gates and applicable development CI pass

Docs
- `_docs/audits/2026-09-06-community-base-migration-plan.md`, developer workflow documentation.

## A0.2 Replace the settings framework with the package config app

Repository: AI-Shipping-Labs/website. Depends on: A0.1. Freeze required: no.

Read first
- `integrations/config.py`, `integrations/settings_registry.py`, `integrations/models/` (the `IntegrationSetting` model)
- `studio/views/settings.py`, `api/views/integration_settings.py`
- every `from integrations.config import` site: `grep -rn "from integrations.config import" --include=*.py . | grep -v tests | wc -l`

Steps
1. Add `community_base.kernel`, `community_base.config` and `community_base.api` to
   `INSTALLED_APPS`; migrate. Configure only hooks already implemented by the site.
2. Convert `INTEGRATION_GROUPS` to `declare(...)` calls in `integrations/settings_keys.py`,
   imported from `IntegrationsConfig.ready()`. One `declare` per key; keep `docs_url` values.
3. Data migration in `integrations` (playbook P6, first pull request): copy `IntegrationSetting`
   rows into `cb_config.Setting` with mapped `value_type` and `source="db"`. Encrypt secret
   values in the target format using a reviewed historical migration-safe implementation;
   direct plaintext copies cannot be decrypted by the package. Prove round trips with synthetic secrets.
4. Inventory and preserve the actual `get_config(..., use_settings=...)`, source-resolution and
   cache-reset contracts in a tested compatibility shim. The released package exports `get` and
   `is_enabled`, not `clear_config_cache`; do not import a nonexistent function. Any missing
   shared public contract must be implemented and tagged before cutover. Keep the shim for one release.
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
- [ ] Studio settings page renders the donor-inventoried groups with source badges on development
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
3. Install the kernel if A0.2 has not already done so. Configure the actual hook path
   `content.access_policy.TierAccessPolicy` with `SITE_KEY="aisl"`, `JOBS_BACKEND="django_q"`,
   `MAIL_BACKEND="ses_local"` and the site Studio title. Do not activate jobs/mail apps yet.
4. Do not change call sites yet; they change per app in later phases (playbook P3).

Verification
- `uv run python manage.py test content --parallel 4` -> pass.
- `uv run python manage.py shell -c "from community_base.kernel.access import can_access; from accounts.models import User; u=User.objects.filter(tier__level__gte=20).first(); print(can_access(u, 20))"` -> `True` on the development copy.

Done when
- [ ] policy has unit tests for override expiry and anonymous user

## D0.1 Add the package and replace the settings frameworks

Repository: DataTalksClub/website. Depends on: D0.1d.

Goal: close the settings adoption milestone after its separately reviewed parts below are deployed.
This parent owns no implementation; do not mark it done when only bootstrap is installed.

Verification
- D0.1a through D0.1d are done with linked review and development evidence.
- Development settings UI/API parity, counts and retained audit history are verified.

Done when
- [ ] the child tasks and deployed settings parity checks pass

Docs
- `_docs/architecture/app-boundaries.md`, `_docs/specs/06-studio-and-admin-api.md`.

## D0.1a Install the released kernel and local development tools

Repository: DataTalksClub/website. Depends on: C2.4.

Goal: install only the released kernel and dependency tools while retaining existing runtime owners.

Read first
- `pyproject.toml`, `uv.lock`, `Makefile`, `website/settings/base.py`, `.github/workflows/ci.yml`.
- `_docs/PROCESS.md`, `_docs/ci/change-selective-ci.md` and the site migration plan.

Steps
1. Verify remote `v0.3.0` and its release wheel; pin the bounded dependency and exact tagged
   source as in A0.1. Record the resolved commit. Run `uv lock` and `uv sync --frozen`.
2. Install only `community_base.kernel.apps.KernelConfig`. Configure `SITE_KEY="dtc"`,
   `ACCESS_POLICY="community_base.kernel.access.RegisteredOnlyPolicy"`, `JOBS_BACKEND="relay"`,
   `MAIL_BACKEND="relay"`, `STUDIO_TITLE="DataTalks.Club Studio"` in `COMMUNITY_BASE`.
   These declarations do not install jobs/mail, contact Relay or require credentials.
3. Implement reversible local-link targets and a parsed tag/lock guard per A0.1, wired into
   actual Make/CI checks. Fail closed on local paths, editable, branches and source mismatch.
4. Add a meaningful integration test: kernel loads without any other shared model app,
   anonymous level 5 is denied, authenticated level 5 allowed and paid levels denied.
   Keep `AUTH_USER_MODEL="accounts.CustomUser"`; no migration should be generated.

Verification
- `uv sync --frozen` and package version import -> `0.3.0`.
- `uv run python manage.py check --settings=website.settings.test` -> no issues.
- `uv run python manage.py makemigrations --check --dry-run --settings=website.settings.test` -> no changes.
- Disposable link/unlink restores byte-identical manifests; negative pin fixtures fail.
- `make verification-plan VERIFY_ISSUE=<site-issue>` followed by the exact generated
  verification-run/evidence/report gates -> pass. Honor dependency impact; no bare root pytest.

Done when
- [ ] kernel integration and safe dependency tools pass site engineer/tester/PM gates
- [ ] local merge/push and required development CI evidence are recorded

Docs
- Site migration plan and local development instructions.

## D0.1b Inventory settings contracts and prove package parity

Repository: DataTalksClub/website. Depends on: D0.1a.

Read first
- `core/operational_settings.py`, `core/operational_settings_service.py`, `core/site_settings.py`,
  `core/settings_batch.py`, `management_registry.py`, `management_api/urls.py`, Studio settings code.

Steps
1. Record every declaration, type, validator, fallback, source badge, permission and audit owner.
2. Compare grouped batch/revision, If-Match and idempotency behavior against released config/API.
3. Write a field/endpoint matrix with synthetic parity cases and explicit site adapter ownership.
4. File blocking package gaps; shared fixes must be tagged before D0.1c. Do not change writers.

Verification
- Every inventory row has a tested mapping or a linked blocking gap.
- Synthetic parity checks and site-selected verification pass without real secrets.

Done when
- [ ] the D0.1c implementation mapping and all prerequisite gaps are explicit and reviewed

Docs
- Site settings parity inventory and migration plan.

## D0.1c Copy settings and switch readers and writers

Repository: DataTalksClub/website. Depends on: D0.1b.

Prerequisite: every recorded shared parity gap is resolved in a published package tag.

Steps
1. Install config/API and declare mapped keys. Add reversible historical-model data copy with
   explicit type, secret-encryption and audit-history mappings.
2. Preserve DTC all-or-nothing batch, revision, If-Match, idempotency and capability protections
   through adapters. Mount routes without shadowing `/api/v1/admin` or `/api/v1/me`.
3. Rehearse on a permitted development copy. Compare exact counts and non-secret invariants;
   second copy adds zero rows, malformed input causes zero partial writes.
4. Switch readers and writers together under reviewed deployment sequencing. Retain old storage
   read-only for rollback. Verify no divergent writes before reverse copy.

Verification
- Development-copy migration, reverse/reapply and exact row comparisons pass.
- Settings permission, batch, revision, source badge and redaction regression scenarios pass.
- Site versioned verification plan, independent tester/PM and development deploy gates pass.

Done when
- [ ] the deployed cutover is reconciled and rollback instructions are verified

Docs
- Settings mapping, deployment evidence and rollback runbook.

## D0.1d Retire old settings storage after the rollback window

Repository: DataTalksClub/website. Depends on: D0.1c.

Prerequisite: development cutover is green and the rollback window has been explicitly closed.

Steps
1. Prove every consumer has moved and audit/history is retained. Unclassified readers block removal.
2. Remove only inventoried migrated declarations, models and shims, with a storage-drop migration.
   Retain unrelated core primitives and tests. Preserve all parity tests in their owning layer.
3. Update spec 06 and app boundaries to reflect actual deployed ownership.

Verification
- Retired-import inventory is empty except immutable migrations and intentional historical docs.
- Migration rehearsal, retained row/audit invariants and site-selected verification pass.

Done when
- [ ] old settings ownership is retired after verified parity and the rollback window

Docs
- `_docs/architecture/app-boundaries.md`, `_docs/specs/06-studio-and-admin-api.md`.

## D0.2 Site CI guard and pin bump workflow

Repository: DataTalksClub/website. Depends on: D0.1a.

Steps
1. Reuse the guard installed in D0.1a; verify it protects the main workflow.
2. Add weekly release inspection producing a deduplicated update issue or advisory for ordinary
   PM, engineer, tester, PM acceptance and local merge/push. Both sites prohibit PRs.
3. Do not auto-change pins or select an adoption-incompatible domain release. Failed release
   lookup is an actionable error. Implement the same advisory flow for AISL as a separate site issue.

Verification
- Manual workflow -> one deduplicated issue/advisory or `already latest`; lookup failure is nonzero.
- Main CI rejects a local-link fixture and accepts the approved tag.

Done when
- [ ] both sites have guards and reviewed update-advisory workflows

Docs
- Both site migration plans and dependency-update operator instructions.
