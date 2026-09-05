# Architecture

## 1. Shape

```
                 +-------------------------------------+
                 |  community-base (pip package)       |
                 |  kernel, config, api, jobs, mail,   |
                 |  accounts, onboarding, questionnaires|
                 |  community, content_sync, studio,   |
                 |  events, notifications, comments,   |
                 |  voting, curriculum, coursework     |
                 +---------+-----------------+---------+
         installs         |                 |         installs
   +----------------------v--+         +----v-----------------------+
   | AISL site               |         | DTC site                   |
   | payments, plans, crm,   |         | content (articles, podcast,|
   | bookclub, workshops,    |         | people, wiki), sponsors,   |
   | downloads, analytics,   |         | navigation, audit,         |
   | triggers, own base.html |         | own base.html              |
   +-----------+-------------+         +-------------+--------------+
               | HTTPS, tenant credentials, signed webhooks         |
               +--------------------------+-------------------------+
                                          v
                                +-------------------+
                                | Relay (service)   |
                                | mail, contacts,   |
                                | campaigns, tasks, |
                                | schedules, SES    |
                                +-------------------+
```

One package, two independent installations, one shared transport service. The package never
knows which site it runs in beyond what the site's settings and hook implementations tell it.

## 2. Rules

These rules are checked by tests inside the package (`tests/test_boundaries.py`, created in Phase
0) and by review.

1. Users. The package ships the concrete user model `community_base.accounts.models.User`
   (label `accounts`, table `accounts_user`) and both sites set
   `AUTH_USER_MODEL = "accounts.User"`. Shared code still references it only through
   `settings.AUTH_USER_MODEL` and `get_user_model()`. Site-specific member data (tier, Stripe,
   learner fields) lives in site extension models with a `OneToOneField` to the user; the shared
   model never grows site-specific columns.
2. No site imports. No module under `community_base/` imports `payments`, `plans`, `content`,
   `courses`, `website`, or any other site app. The boundary test greps for it.
3. Extension points, and only these:
   - access policy: `community_base.kernel.access.can_access(user, obj)` and
     `level_label(level)`, resolved from `COMMUNITY_BASE["ACCESS_POLICY"]`;
   - configuration: `community_base.config.get(key)` and `is_enabled(key)`;
   - mail: `community_base.mail.send(purpose, to, context, idempotency_key)`;
   - jobs: `community_base.jobs.dispatch_after_commit(handler, key, payload)` and
     `@community_base.jobs.register_handler(name)`;
   - domain signals in `community_base.<app>.signals`;
   - Studio sections registered in `AppConfig.ready()` through `community_base.studio.registry`;
   - API routes registered through `community_base.api.registry`;
   - template override by path (Django `DIRS` before `APP_DIRS`);
   - extension models: a site adds a `OneToOneField` model in its own app when it needs extra
     fields on a shared model. Shared models are never forked.
4. Templates. Shared public templates extend `"base.html"` (the site's) and use only the blocks
   and class hooks listed in section 5. Shared Studio templates extend
   `"community_base/studio/base.html"` (the package's, decision D12).
5. Migrations in the package are append-only after a tag. Never edit a migration that shipped in
   a tag; add a new one. A kept-label initial migration is provisional and must remain untagged
   until its compatibility issue verifies the exact donor migration inventory and state. Once
   tagged, its `replaces` marker remains permanently.
6. Settings. Package configuration reads one dictionary, `settings.COMMUNITY_BASE`, with
   documented keys and defaults (`community_base/kernel/conf.py`). Shared code may also use the
   narrow Django framework settings that define integration contracts: `AUTH_USER_MODEL`,
   `LOGIN_URL`, `SECRET_KEY`, and a Django setting explicitly named as a declared config fallback.
   It never reads other arbitrary `settings.X`. The Phase 0 kernel keys are exactly `SITE_KEY`,
   `ACCESS_POLICY`, `JOBS_BACKEND`, `MAIL_BACKEND` and `STUDIO_TITLE`.
7. Every network side effect (Relay call, GitHub call, Zoom call, S3 upload) happens in a job
   handler or in an explicit service method called after commit, never inside a model `save()`,
   a signal handler, or a request transaction.
8. Redaction. Anything logged, audited or returned in an error passes through
   `community_base.kernel.redaction.redact`. Recipient tokens, secrets and email addresses never
   appear in logs.

## 3. Package layout and app labels

| Module | App label | Models | Origin | Phase |
|---|---|---|---|---|
| `community_base.kernel` | `cb_kernel` | none | DTC `core` (redaction, context, services, idempotency), AISL `studio/decorators.py` | 0 |
| `community_base.config` | `cb_config` | `Setting`, `SettingChange` | AISL `integrations` (registry, cache, Studio UI), DTC `core` (typing, audit) | 0 |
| `community_base.api` | `cb_api` | `APIKey` | AISL `accounts.Token`, `accounts.MemberAPIKey`, `api/openapi/`, `api/safety.py`; DTC `management_auth` scopes | 0 |
| `community_base.jobs` | `cb_jobs` | `JobIntent`, `JobLease` | DTC `jobs` (dispatch, leases), AISL `jobs` (Studio page, schedules command), Relay tasks API. Backends: `relay`, `django_q` | 1 |
| `community_base.mail` | `cb_mail` | `EmailDelivery`, `PendingUnsubscribe`, `EmailLog` (ses_local backend only) | DTC spec 05 and `email_app` (link bridge), AISL `email_app` (preferences, bounce semantics, markdown renderer and SES client as the `ses_local` backend) | 1 |
| `community_base.accounts` | `accounts` | `User`, `EmailAlias`, `EmailChangeRequest`, `PrivacyRequestLog`, `ImportBatch`, `MemberProfile` | AISL `accounts` (model, services, auth views, allauth glue), DTC spec 01 (`MemberProfile` fields) | 3 |
| `community_base.questionnaires` | `questionnaires` | as in AISL | AISL `questionnaires` | 3 |
| `community_base.onboarding` | `cb_onboarding` | `OnboardingFlow`, `OnboardingStep`, `FlowAssignment` | AISL `accounts/views/onboarding*.py`, new flow models | 3 |
| `community_base.community` | `community` | as in AISL | AISL `community` | 3 |
| `community_base.notifications` | `notifications` | as in AISL | AISL | 3 |
| `community_base.comments` | `comments` | as in AISL | AISL | 3 |
| `community_base.voting` | `voting` | as in AISL | AISL | 3 |
| `community_base.content_sync` | `cb_content_sync` | `ContentSource`, `SyncLog`, `WebhookLog` | AISL `integrations/services/github_sync/`, `integrations.models` | 2 |
| `community_base.studio` | `cb_studio` | none | AISL `studio` shell, sidebar, templatetags, users pages | 2 |
| `community_base.events` | `events` | as in AISL | AISL `events` | 4 |
| `community_base.curriculum` | `cb_curriculum` | `Course`, `Cohort`, `Module`, `Unit`, `Enrollment`, `UnitProgress`, `Certificate` | AISL `content` course models, DTC `courses` provenance and cohort split | 5 |
| `community_base.coursework` | `cb_coursework` | `Homework`, `Question`, `Submission`, `Answer`, `Project`, `ProjectSubmission`, `ReviewCriteria`, `PeerReview`, `Leaderboard*` | DTC `courses` | 5 |

Label rules:

- A label kept from AISL (`accounts`, `events`, `notifications`, `comments`, `voting`,
  `questionnaires`, `community`) means AISL's existing tables and `django_migrations` rows are reused. The package
  ships `0001_squashed.py` with `replaces` listing AISL's migration names (playbook P4). During
  package-first implementation this migration remains provisional and untagged until donor
  compatibility is proven.
- A `cb_` label means new tables. Data is copied from the old site tables by a site-side data
  migration written in the same pull request that installs the app (playbook P6).
- A label that exists in DTC with different tables (`events`) is replaced during DTC's freeze by
  dropping DTC's tables and `django_migrations` rows for that label, then migrating fresh
  (playbook P5).

Repository layout:

```
community-base/
  pyproject.toml            name = "community-base", packages = ["community_base"]
  community_base/
    __init__.py             __version__
    kernel/  config/  api/  jobs/  mail/  accounts/  questionnaires/  onboarding/
    community/  content_sync/  studio/  events/  notifications/  comments/  voting/
    curriculum/  coursework/
    templates/community_base/...      shared templates, namespaced
    static/community_base/...         Studio Tailwind bundle and JS
  testproject/
    settings.py  urls.py  manage.py   (AUTH_USER_MODEL = "accounts.User")
  tests/                    package tests, one directory per app, plus test_boundaries.py
  docs/                     this documentation
  Makefile                  test, lint, check, release
  .github/workflows/ci.yml  ruff, makemigrations --check, pytest
```

## 4. Consumption by a site

`pyproject.toml` in a site:

```toml
[project]
dependencies = [
    "community-base",
]

[tool.uv.sources]
community-base = { git = "https://github.com/DataTalksClub/community-base", tag = "v0.3.0" }
```

Local development against a checkout in a sibling directory:

```make
core-link:    ## use ../community-base (editable) instead of the pinned tag
	uv add --editable ../community-base
core-unlink:  ## restore the pinned tag from git
	git checkout -- pyproject.toml uv.lock && uv sync
```

`make core-link` must never be committed: CI in each site fails if `pyproject.toml` contains
`path = "../community-base"` (check added in Phase 0).

Site settings:

```python
INSTALLED_APPS = [
    ...
    "community_base.kernel",
    "community_base.config",
    "community_base.api",
    "community_base.accounts",
    ...
]
AUTH_USER_MODEL = "accounts.User"

COMMUNITY_BASE = {
    "SITE_KEY": "aisl",                       # or "dtc"; used for Relay tenant and idempotency prefixes
    "ACCESS_POLICY": "payments.access.TierAccessPolicy",   # DTC: "community_base.kernel.access.RegisteredOnlyPolicy"
    "JOBS_BACKEND": "relay",                  # AISL: "django_q" until decision D13 is satisfied
    "MAIL_BACKEND": "relay",                  # AISL: "ses_local" until decision D13 is satisfied
    "MAIL_TEMPLATE_DIR": None,                # ses_local only: directory of markdown templates
    "RELAY_BASE_URL": env("RELAY_BASE_URL"),
    "RELAY_API_KEY": env("RELAY_API_KEY"),
    "RELAY_WEBHOOK_SECRET": env("RELAY_WEBHOOK_SECRET"),
    "STUDIO_TITLE": "AI Shipping Labs Studio",
}
```

## 5. Template contract for shared public pages

Shared public templates (events list and detail, onboarding steps, account pages, notifications
page, course and unit pages) use:

- `{% extends "base.html" %}`;
- blocks `title`, `meta_description`, `page_head_metadata`, `content`, `extra_js`; nothing else;
- structural class hooks, one per element role, prefixed `cb-`: `cb-page`, `cb-page-header`,
  `cb-page-title`, `cb-list`, `cb-card`, `cb-card-title`, `cb-card-meta`, `cb-badge`,
  `cb-button`, `cb-button-primary`, `cb-form`, `cb-field`, `cb-alert`, `cb-empty`, `cb-pager`;
- no colour, spacing or typography utility classes. A site styles the `cb-` hooks in its own
  stylesheet (AISL adds `@apply` rules in `assets/css/tailwind.css`; DTC adds rules to
  `templates/core/_design_system.html`).

A site may override any shared template by placing a file at the same path under its own
`templates/` directory. The package's `tests/test_template_contract.py` asserts that every shared
public template uses only the blocks and hook classes above.

## 6. Data flows that cross the package boundary

Sending an email (`relay` backend):

```
domain service (in a transaction)
  -> community_base.mail.send(purpose, to, context, idempotency_key)
       creates EmailDelivery(pending) + JobIntent (same transaction)
  -> on commit: community_base.jobs submits a Relay task (idempotency_key)
  -> Relay renders template <purpose> version N, sends, posts callbacks
  -> community_base.mail.callbacks updates EmailDelivery projection (monotonic)
```

Sending an email (`ses_local` backend, AISL until D13):

```
domain service -> community_base.mail.send(...) -> EmailDelivery(pending) + JobIntent
  -> on commit: django_q task renders markdown template from MAIL_TEMPLATE_DIR,
     applies DB template override, sends through SES v2, writes EmailLog, marks
     EmailDelivery provider_accepted
```

Running a scheduled job:

```
community_base.jobs.schedules registry (code)
  -> `manage.py sync_relay_schedules` at deploy registers cron + webhook URL in Relay
  -> Relay calls POST /internal/jobs/<handler> with HMAC headers at the cron time
  -> ingress verifies signature, timestamp window and task id, runs handler (bounded),
     returns 200, or 202 with a lease for chunked handlers that re-dispatch themselves
```

Content sync:

```
GitHub push webhook -> content_sync ingress (signature) -> JobIntent per source
  -> handler: source lock, immutable checkout, parser registry by content type,
     upsert, soft-delete missing, SyncLog
```
