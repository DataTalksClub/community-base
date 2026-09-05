# Playbooks

Procedures that many issues reuse. An issue says "follow playbook P4"; the executor follows the
numbered steps here and runs every check. Placeholders are in angle brackets.

Repository names used below:

| Name | Path on the owner's machine | GitHub |
|---|---|---|
| package | `~/git/community-base` | `DataTalksClub/community-base` |
| AISL | `~/git/ai-shipping-labs` | `AI-Shipping-Labs/website` |
| DTC | `~/git/dtc-website` | `DataTalksClub/website` |
| Relay | `~/git/relay` | `DataTalksClub/relay` |

## P1. Develop a site against a local package checkout

1. In the site: `make core-link`. This runs `uv add --editable ../community-base`.
2. Verify: `uv run python -c "import community_base, pathlib; print(pathlib.Path(community_base.__file__).resolve())"`
   prints a path under `~/git/community-base/`.
3. Work. Package changes are visible without reinstall.
4. Before committing in the site: `make core-unlink`, which runs
   `git checkout -- pyproject.toml uv.lock && uv sync`.
5. Verify: `grep -n 'path = "../community-base"' pyproject.toml` prints nothing, and
   `git diff --stat pyproject.toml uv.lock` prints nothing unless the issue bumps the pin.

## P2. Add a shared app to a site

1. Bump the pin if needed (P15, site half).
2. Add `"community_base.<app>"` to `INSTALLED_APPS` after `community_base.kernel`.
3. Add the app's URL include where the issue says, for example
   `path("events/", include("community_base.events.urls"))`.
4. Add any `COMMUNITY_BASE` keys the app documents in `community_base/<app>/README.md`.
5. Run `uv run python manage.py migrate` on a fresh SQLite database and on the development
   database copy (P14).
6. Verify: `uv run python manage.py check` clean; `uv run python manage.py makemigrations --check --dry-run`
   reports no changes; the app's smoke URL from its README returns 200 in `manage.py runserver`.

## P3. Cut a seam inside a site app before extraction

A seam replaces an import of a site-specific app with a package extension point.

1. List the imports: `grep -rn "^from <site_app>" <app>/ --include=*.py | grep -v tests`.
2. For each import decide the replacement from this table:

| Import today | Replacement |
|---|---|
| `from integrations.config import get_config, is_enabled` | `from community_base.config import get, is_enabled` |
| `from payments.models import Tier`, `user.tier.level`, `LEVEL_*` comparisons | `from community_base.kernel.access import can_access, level_label, LEVEL_*`; call `can_access(user, obj)` |
| `from email_app.services.email_service import EmailService` | `from community_base.mail import send` |
| `from jobs.tasks import ...`, `async_task(...)` | `from community_base.jobs import dispatch_after_commit`, `register_handler` |
| `from content.models import Workshop` in `events` | a domain signal or hook: `events.hooks.related_writeup(event)` resolved from `COMMUNITY_BASE["EVENT_WRITEUP_RESOLVER"]` |
| `from plans...`, `from bookclub...`, `from crm...` | signal consumer moved into the site app; the shared app emits the signal |
| template `{% include "content/_workshop_card.html" %}` | block with default content; site overrides the template |

3. Make the change in the smallest reviewable unit: one import target per pull request.
4. Verify after each pull request:
   - `grep -rn "^from <site_app>" <app>/ --include=*.py | grep -v tests` no longer lists the
     replaced import;
   - `uv run python manage.py test <app> --parallel 4` passes;
   - `make test-affected` passes (AISL).
5. Record the remaining imports in the extraction issue's checklist. Extraction (P4) starts only
   when the list is empty.

## P4. Lift an app from AISL keeping its label

Used for `accounts`, `events`, `notifications`, `comments`, `voting`, `questionnaires`,
`community`. Requires the P3 checklist to be empty and a freeze (P13).

1. In AISL, record the migration names:
   `ls <app>/migrations/ | grep -E '^[0-9]{4}_' | sed 's/\.py$//' | sort > /tmp/<app>_migrations.txt`.
2. Copy the app into the package: `cp -r ~/git/ai-shipping-labs/<app> ~/git/community-base/community_base/<app>`;
   remove `__pycache__`; remove `migrations/*` except `__init__.py`.
3. Rewrite imports inside the copied app: `from <app>.` becomes `from community_base.<app>.`;
   `'<app>.` string references in `ForeignKey("<app>.Model")` stay as they are because the label
   is unchanged. Set `name = "community_base.<app>"` and `label = "<app>"` in `apps.py`.
4. Move templates from `~/git/ai-shipping-labs/templates/<app>/` to
   `community_base/<app>/templates/<app>/`. Rewrite them to the template contract
   (`docs/02-architecture.md`, section 5) if they are public templates; Studio templates extend
   `community_base/studio/base.html`.
5. Move tests to `tests/<app>/`. Replace AISL fixtures that create tiers, payments or plans with
   the package's factories in `tests/factories.py`. Tests that assert AISL-only behaviour are
   listed in the issue and stay in AISL.
6. Generate the squashed migration: in the package, with `testproject` settings,
   `uv run python testproject/manage.py makemigrations <app> --name squashed`. Rename the file to
   `0001_squashed.py`. Add at the top of the `Migration` class:
   `replaces = [("<app>", "<name>") for <name> in /tmp/<app>_migrations.txt]` written out as a
   literal list.
7. Verify squash equivalence against AISL's current state:
   - in AISL, link the package (P1), remove the local `<app>` directory, keep `INSTALLED_APPS`
     entry pointing to `community_base.<app>`;
   - `uv run python manage.py migrate --plan` must print no operations for `<app>`;
   - `uv run python manage.py makemigrations --check --dry-run` must print "No changes detected".
     If it prints changes, the copied models differ from AISL's state; fix the models, not the
     migration.
8. Rehearse on the development database copy (P14): `migrate` must be a no-op for `<app>` and
   `django_migrations` must gain one row `<app>.0001_squashed`.
9. Tag the package (P15). Open the AISL pull request that deletes `<app>/`, `templates/<app>/`,
   and the app's tests, and bumps the pin. Merge during the freeze.
10. After AISL production has run one deploy with the squashed migration, open a package pull
    request that removes the `replaces` list. Never remove it earlier.

Checks that must be in the AISL pull request description: the migration count in
`/tmp/<app>_migrations.txt`, the `migrate --plan` output, and the test count before and after
(quality gate section 3).

## P5. Replace a DTC app that has the same label as a package app

Used for `events` in DTC (Phase 4). DTC's tables have a different schema; they are rebuilt.

1. Export the data the issue says to keep: `uv run python manage.py dumpdata <app> --indent 2 > .tmp/<app>_export.json`
   plus any extension data the issue names. Row counts recorded.
2. Add to DTC a one-off management command `rebuild_<app>_tables` that, inside one transaction:
   - drops every table whose name starts with `<app>_` (list them first with
     `SELECT tablename FROM pg_tables WHERE tablename LIKE '<app>_%'`, SQLite equivalent in tests);
   - deletes `django_migrations` rows where `app = '<app>'`;
   - deletes `django_content_type` rows where `app_label = '<app>'` after deleting dependent
     `auth_permission` rows.
3. Remove the DTC `<app>` directory; install `community_base.<app>` (P2).
4. Run the command, then `migrate`. Verify: `migrate --plan` shows the package migrations for
   `<app>` and nothing else; `makemigrations --check` clean.
5. Import the exported data with the issue's import command (a mapping from old fields to shared
   fields; unknown fields go to the DTC extension model).
6. Verify row counts against step 1 and run the app's Playwright core tests.
7. Rehearse the whole sequence on the development database copy (P14) before the freeze.

## P6. Move models to a new label with data copy

Used when a package app gets a `cb_` label and the site had the same models under another label
(for example `integrations.IntegrationSetting` to `cb_config.Setting`).

1. Install the package app (P2). Its migrations create the new tables.
2. In the site, add a data migration in the site app that owned the old models:
   `RunPython(copy_forward, copy_backward)` copying every row with an explicit field mapping.
   Use `apps.get_model` for both sides. Batch in chunks of 1,000.
3. Do not delete the old models in the same pull request. Ship, deploy to development, verify
   counts with `manage.py shell -c` queries printed in the pull request.
4. Second pull request: delete the old models and their usages; a migration removes the tables.
5. Verify both pull requests with the migration gates (quality gates section 2).

## P7. Swap a site to the shared user model

Used once per site in Phase 3. The shared model is `community_base.accounts.models.User`, label
`accounts`, table `accounts_user`.

AISL (label and table already match):

1. Move site-specific fields off `User` first, one pull request per group, expand then contract:
   - `tier`, `pending_tier`, `billing_period_end`, `stripe_customer_id`, `subscription_id` to
     `payments.Membership(user OneToOne)`;
   - `import_source`, `imported_at`, `import_metadata`, `signup_source`, `account_activated`,
     `tags` stay on the shared model only if the shared model declares them (they do; see the
     field table in `docs/plan/phase-3.md`). Anything not in that table moves to
     `accounts_ext.MemberExtra` in AISL.
   - Each pull request: add the new model and copy data, switch readers, drop the field.
2. When `User` in AISL equals the shared field table exactly, follow P4 for `accounts`.
3. `AUTH_USER_MODEL` stays `"accounts.User"`.

DTC (`accounts.CustomUser`, table `accounts_customuser`):

1. Move course-platform fields (`role`, `certificate_name`, `country`, `region`,
   `registration_role`, `github_url`, `linkedin_url`, `personal_website_url`, `about_me`,
   `dark_mode`) to `courses.LearnerProfile(user OneToOne)`; identity reconciliation fields to
   `accounts_ext.IdentityState`. Expand then contract as above.
2. Rename the model: a DTC migration with `migrations.RenameModel("CustomUser", "User")` and
   `AlterModelTable` to `accounts_user`. Deploy to development. Verify logins still work.
3. Reconcile fields until `makemigrations --check` with the package model in state is clean.
4. Follow P5 for the `accounts` label: DTC has its own `accounts` migrations. Because the user
   table must keep its rows, do not drop the table; instead delete only the `django_migrations`
   rows for `accounts` and then `migrate accounts 0001_squashed --fake`. Verify with
   `migrate --plan` (no operations) and `makemigrations --check`.
5. Set `AUTH_USER_MODEL = "accounts.User"` (unchanged label, new model name); update every
   `from accounts.models import CustomUser` to `get_user_model()`.

Both sites: after the swap, `uv run python manage.py shell -c "from django.contrib.auth import get_user_model as g; print(g()._meta.app_label, g()._meta.db_table, g().objects.count())"`
prints `accounts accounts_user <same count as before>`.

## P8. Use and override a shared template

1. Shared public templates live at `community_base/<app>/templates/<app>/<name>.html` and follow
   the contract in `docs/02-architecture.md`, section 5.
2. To override in a site, copy the file to `templates/<app>/<name>.html` in the site and edit.
   Django finds the site copy first because `DIRS` precedes `APP_DIRS`.
3. Verify: `uv run python manage.py shell -c "from django.template.loader import get_template as g; print(g('<app>/<name>.html').origin.name)"`
   prints the site path.
4. Package check: `uv run pytest tests/test_template_contract.py` passes after any change to a
   shared template.

## P9. Register a Studio section

In the app's `apps.py`:

```python
from django.apps import AppConfig

class EventsConfig(AppConfig):
    name = "community_base.events"
    label = "events"

    def ready(self):
        from community_base.studio.registry import Section, Destination, register
        register(Section(
            slug="events", title="Events", order=10,
            destinations=[
                Destination(key="events", title="Events", url_name="studio_event_list",
                            route_names=["studio_event_list", "studio_event_edit", ...]),
            ],
        ))
```

Verify: `uv run python manage.py studio_routes --check` (added in Phase 2) reports every Studio
route as owned by exactly one destination, section-only, or explicitly unlisted.

## P10. Register a configuration key

```python
from community_base.config.registry import declare

declare(
    key="ZOOM_CLIENT_ID", group="zoom", label="Zoom client id",
    description="OAuth client id from the Zoom marketplace app. Without it, event creation cannot create meetings.",
    value_type="str", default="", secret=False, env_var="ZOOM_CLIENT_ID",
    docs_url="docs/integrations/zoom.md#zoom_client_id",
)
```

Read with `community_base.config.get("ZOOM_CLIENT_ID")`. Verify: the key appears on the Studio
settings page with a source badge and in `GET /api/v1/settings`.

## P11. Register an API endpoint

```python
from community_base.api.registry import route

@route("GET", "/events", scope="events.read", summary="List events", response="EventList")
def list_events(request):
    ...
```

Verify: `uv run python manage.py openapi --check` reproduces the committed schema; a request with
a key lacking the scope returns 403 with the standard error body.

## P12. Register a job handler and a schedule

```python
from community_base.jobs import register_handler, schedule

@register_handler("events.send_reminders")
def send_reminders(context, payload):
    ...

schedule("events.send_reminders", cron="*/15 * * * *", payload={})
```

Dispatch from a service inside a transaction:
`dispatch_after_commit("events.send_reminders", key=f"reminders:{event_id}", payload={"event_id": event_id})`.

Verify: with `JOBS_BACKEND="django_q"` the handler runs under `qcluster` (or synchronously in
tests with `JOBS_SYNC=True`); with `JOBS_BACKEND="relay"`,
`manage.py sync_relay_schedules --dry-run` lists the schedule and
`manage.py jobs_ingress_selftest` round-trips a signed request.

## P13. Freeze weekend runbook

Before the weekend:

1. The extraction pull requests exist, are green, and their package tag is published.
2. The rehearsal on the development database copy (P14) was done in the last 7 days.
3. The site's issue tracker has a `freeze` label on every open issue touching the app; the
   pipeline does not pick them.
4. Announce the freeze in the site's operator channel with the start and end time.

During the weekend:

1. Merge the site pull request; CI deploys to development.
2. Run the site's deployed smoke (`make smoke-dev` or the site's documented equivalent).
3. Run the app's core Playwright tests against development.
4. Deploy to production using the site's normal deploy workflow. Watch the readiness poll.
5. Run the production read-only checks the issue lists (login, one list page, one detail page).
6. If any check fails: roll back with the site's rollback workflow, restore the pin to the
   previous tag, and stop. Report.

After the weekend:

1. Remove the `freeze` label. Close the extraction issue with the checks pasted in.
2. Open the follow-up that removes `replaces` (P4 step 10) with a "not before" date one deploy
   later.

## P14. Rehearse migrations on a development database copy

Never on production. Uses the site's development environment database.

1. Dump: `pg_dump "$DEV_DATABASE_URL" --no-owner --format=custom --file .tmp/dev.dump`.
2. Restore locally: `createdb cb_rehearsal && pg_restore --no-owner --dbname cb_rehearsal .tmp/dev.dump`.
3. Record counts: `psql cb_rehearsal -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname" > .tmp/counts_before.txt`.
4. `DATABASE_URL=postgres:///cb_rehearsal uv run python manage.py migrate --plan` then `migrate`.
5. Record counts again to `.tmp/counts_after.txt`; `diff` the two files; every difference must
   be explained by the issue.
6. `DATABASE_URL=postgres:///cb_rehearsal uv run python manage.py check` and the site's smoke
   management command if one exists.
7. Drop the database: `dropdb cb_rehearsal`. Delete `.tmp/dev.dump`.

## P15. Release a package version and bump a site pin

Package half:

1. `uv run pytest` green, `uv run ruff check .` clean, `makemigrations --check` clean.
2. Update `community_base/__init__.py` `__version__` and `CHANGELOG.md` (one line per merged
   issue, with the issue id).
3. `git tag v<version> && git push origin v<version>`. CI builds the wheel and attaches it to a
   GitHub release.
4. Verify: `git ls-remote --tags origin v<version>` lists the tag; the release page shows the
   wheel.

Site half:

1. Edit `pyproject.toml` `[tool.uv.sources]` tag to `v<version>`; `uv lock --upgrade-package community-base`.
2. `uv run python manage.py migrate` on a fresh SQLite database; `makemigrations --check` clean.
3. Run the site suite for every app that imports the changed package apps (AISL:
   `make test-affected`).
4. Open the pull request titled `Bump community-base to v<version>` with the changelog lines.
