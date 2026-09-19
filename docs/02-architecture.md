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
   - content kinds registered in `AppConfig.ready()` through
     `community_base.content_sync.kinds.register_kind`, which may add keys to the content format
     but never remove, rename or retype a core key (D23);
   - markdown extensions appended through `COMMUNITY_BASE["MARKDOWN_EXTENSIONS"]`: synced content
     has one dialect and one sanitiser, `community_base.content_sync.rendering` (D23), and a site
     adds an extension to that list rather than forking the dialect or adding a second sanitiser;
     an extension's output still passes the package sanitiser;
   - API routes registered through `community_base.api.registry`; administrative integrations use
     scoped bearer authentication, while member-owned browser routes explicitly select session
     authentication and retain CSRF protection;
   - template override by path (Django `DIRS` before `APP_DIRS`);
   - extension models: a site adds a `OneToOneField` model in its own app when it needs extra
     fields on a shared model. Shared models are never forked.
   - site-owned fields on a synced content model: one opaque JSON `record` the package stores
     and never interprets (`KnowledgeBasePage.record`), plus a nullable site-owned public path
     and site-supplied rendered HTML where the app has a default for both. Two sites with
     different record shapes then share one model, and the package grows no per-site column.
     A package parser writes into that record too; the package still reads no key of it.
   - content parsers registered in `AppConfig.ready()` through
     `community_base.content_sync.parsers.register_parser`. A site writes a parser for the kinds
     whose storage it owns; the package parses `wiki`, `docs`, `person` and `course`, whose
     storage the package owns (D24).
4. Templates. Shared public templates extend `"base.html"` (the site's) and use only the blocks
   and class hooks listed in section 5. Shared Studio templates extend
   `"community_base/studio/base.html"` (the package's, decision D12) and fill their body inside
   both `{% block content %}` and, nested inside it, `{% block studio_content %}`. A site may
   still replace `"community_base/studio/base.html"` outright with its own shell (both AISL and
   DTC do, transitionally); that replacement must expose a reachable slot for at least one of the
   two names, or every shared Studio page it serves renders as an empty shell with no error.
   `community_base.studio.checks.check_studio_content_block_contract` runs on every `manage.py
   check` and fails with `community_base.studio.E001` when a site's replacement exposes neither
   (community-base#279).

   Three pieces cover this contract and none is sufficient alone. A package-tree test asserts
   every shared template fills both names, so a single-name template cannot ship from here. The
   system check answers whether a site's replacement exposes either name. The third piece is
   unownable from the package: whether a consuming site mounts the surface at all. Two blank AISL
   pages were reachable only because that site mounts `community_base.api.urls` and
   `community_base.jobs.studio_urls`; a site mounting neither has the same broken templates
   installed and no symptom. The count that matters to a site is templates filling the unexposed
   name and mounted there, and only the site can know it.

   The failure is worth describing because it is a shape, not an incident. Two failures stacked:
   a site added an override to its Studio base specifically so the package jobs page would render
   in its shell, and the page filled the other block name, so the fix and the bug never met.
   Neither half looked wrong on its own, and the page returned 200 throughout. An empty page
   returning 200 looks like an empty list, and a fix addressing the wrong half of a two-part
   contract looks like a fix. Both sites carried a different half of this for months
   (AI-Shipping-Labs/website#1615 comment thread, community-base#279).
5. Migrations in the package are append-only after a tag. Never edit a migration that shipped in
   a tag; add a new one. A kept-label initial migration is provisional and must remain untagged
   until its compatibility issue verifies the exact donor migration inventory and state. Once
   tagged, its `replaces` marker remains permanently.
6. Settings. Package configuration reads one dictionary, `settings.COMMUNITY_BASE`, with
   documented keys and defaults (`community_base/kernel/conf.py`). Shared code may also use the
   narrow Django framework settings that define integration contracts: `AUTH_USER_MODEL`,
   `LOGIN_URL`, `SECRET_KEY`, `AUTHENTICATION_BACKENDS`, and a Django setting explicitly named as
   a declared config fallback. It never reads other arbitrary `settings.X`. The declared kernel keys include
   `ACCOUNT_BEFORE_DELETE_HOOK`, `ACCOUNT_DELETION_BLOCKER`, `ACCOUNT_MERGE_HOOK`,
   `ACCOUNT_PRIVACY_EXPORT_HOOK`, `ACCOUNT_UNVERIFIED_TTL_DAYS`, `SITE_KEY`, `SITE_URL`,
   `ACCESS_POLICY`, `COURSE_ACCESS_GRANTS`, `COURSEWORK_ANSWER_KEYRING`,
   `COURSEWORK_CERTIFICATE_ISSUED`, `COURSEWORK_DISPLAY_NAME_GENERATOR`,
   `COURSEWORK_ENROLLMENT_PREFERENCES_UPDATED`, `COURSEWORK_HOMEWORK_SUBMISSION_REJECTED`,
   `COURSEWORK_HOMEWORK_SUBMITTED`, `COURSEWORK_OPTIONAL_REVIEW_ADDED`,
   `COURSEWORK_OPTIONAL_REVIEW_DELETED`, `COURSEWORK_PEER_REVIEWS_ASSIGNED`,
   `COURSEWORK_PEER_REVIEWS_ASSIGNMENT_FAILED`, `COURSEWORK_PROJECT_DELETED`,
   `COURSEWORK_PROJECT_LEADERBOARD_UPDATER`, `COURSEWORK_PROJECT_SCORED`,
   `COURSEWORK_PROJECT_SCORING_FAILED`, `COURSEWORK_PROJECT_SUBMITTED`,
   `COURSEWORK_PROJECT_VOTE_UPDATED`, `COURSEWORK_REGISTRATION_CAMPAIGN_CHANGED`,
   `COURSEWORK_REGISTRATION_SUBMITTED`, `COURSEWORK_REVIEW_SUBMITTED`, `JOBS_BACKEND`,
   `MAIL_BACKEND`, `MAIL_TEMPLATE_DIR`, `RELAY_BASE_URL`,
   `CONTENT_SOURCES`, `CONTENT_SYNC_GITHUB_API_URL`, `CONTENT_SYNC_GITHUB_APP_ID`,
   `CONTENT_SYNC_GITHUB_INSTALLATION_ID`, `CONTENT_SYNC_GITHUB_PRIVATE_KEY`,
   `CONTENT_SYNC_HTTP_TIMEOUT`, `CONTENT_SYNC_MAX_ARCHIVE_BYTES`,
   `CONTENT_SYNC_MEDIA_BACKEND`, `CONTENT_SYNC_S3_BUCKET`, `CONTENT_SYNC_S3_PREFIX`,
   `CONTENT_SYNC_S3_PUBLIC_URL`, `CONTENT_SYNC_S3_REGION`,
`RELAY_API_KEY`, `RELAY_WEBHOOK_SECRET`, `STUDIO_TITLE`, `STUDIO_AUDIT_WRITER`,
`STUDIO_AUTHORIZER` and `USER_TAGS_ACCESSOR`.
   Mail also declares `MAIL_PREFERENCE_RESOLVER`, `MAIL_SEND_RECORDER`,
   `MAIL_TEMPLATE_OVERRIDE_LOADER`, `MAIL_UNSUBSCRIBE_URL_BUILDER` and
   `MAIL_VERIFY_EMAIL_URL_BUILDER`; `MAIL_CONTEXT_RESOLVER` enriches persisted non-secret context
   inside the worker. The optional delivery hooks default to no hook.
7. Every network side effect (Relay call, GitHub call, Zoom call, S3 upload) happens in a job
   handler or in an explicit service method called after commit, never inside a model `save()`,
   a signal handler, or a request transaction.
8. Redaction. Anything logged, audited or returned in an error passes through
   `community_base.kernel.redaction.redact`. Recipient tokens, secrets and email addresses never
   appear in logs.

## 3. Package layout and app labels

| Module | App label | Models | Origin | Phase |
|---|---|---|---|---|
| `community_base.kernel` | `cb_kernel` | none (abstract bases `RevisionedModel`, `AppendOnlyManager`) | DTC `core` (redaction, context, services, idempotency, model bases C7.5), AISL `studio/decorators.py` | 0 |
| `community_base.config` | `cb_config` | `Setting`, `SettingChange` | AISL `integrations` (registry, cache, Studio UI), DTC `core` (typing, audit) | 0 |
| `community_base.api` | `cb_api` | `APIKey` | AISL `accounts.Token`, `accounts.MemberAPIKey`, `api/openapi/`, `api/safety.py`; DTC `management_auth` scopes | 0 |
| `community_base.jobs` | `cb_jobs` | `JobIntent`, `JobLease` | DTC `jobs` (dispatch, leases), AISL `jobs` (Studio page, schedules command), Relay tasks API. Backends: `relay`, `django_q` | 1 |
| `community_base.mail` | `cb_mail` | `EmailDelivery`, `PendingUnsubscribe`, `EmailLog` (ses_local backend only) | DTC spec 05 and `email_app` (link bridge), AISL `email_app` (preferences, bounce semantics, markdown renderer and SES client as the `ses_local` backend) | 1 |
| `community_base.accounts` | `accounts` | `User`, `EmailAlias`, `EmailChangeRequest`, `PrivacyRequestLog`, `ImportBatch`, `MemberProfile`, `AccountSession` | AISL `accounts` (model, services, auth views, allauth glue), DTC spec 01 (`MemberProfile` fields), AISL `accounts/models/session.py` and `session_backend.py` (`AccountSession`, phase 7 `C7.6`) | 3, 7 |
| `community_base.questionnaires` | `questionnaires` | as in AISL | AISL `questionnaires` | 3 |
| `community_base.onboarding` | `cb_onboarding` | `OnboardingFlow`, `OnboardingStep`, `FlowAssignment` | AISL `accounts/views/onboarding*.py`, new flow models | 3 |
| `community_base.community` | `community` | as in AISL | AISL `community` | 3 |
| `community_base.notifications` | `notifications` | as in AISL | AISL | 3 |
| `community_base.comments` | `comments` | as in AISL | AISL | 3 |
| `community_base.voting` | `voting` | as in AISL | AISL | 3 |
| `community_base.content_sync` | `cb_content_sync` | `ContentSource`, `SyncLog`, `WebhookLog` | AISL `integrations/services/github_sync/`, `integrations.models`; the content format, kind registry and `check_content` (phase 7 `C7.7`, D23) | 2 |
| `community_base.studio` | `cb_studio` | none | AISL `studio` shell, sidebar, templatetags, users pages | 2 |
| `community_base.events` | `events` | as in AISL | AISL `events` | 4 |
| `community_base.curriculum` | `cb_curriculum` | `Course`, `Cohort`, `Module`, `Unit`, `Enrollment`, `UnitProgress`, `Certificate` | AISL `content` course models, DTC `courses` provenance and cohort split | 5 |
| `community_base.coursework` | `cb_coursework` | `Homework`, `Question`, `Submission`, `Answer`, `Project`, `ProjectSubmission`, `ReviewCriteria`, `PeerReview`, `Leaderboard*` | DTC `courses` | 5 |
| `community_base.knowledge_base` | `cb_knowledge_base` | `KnowledgeBasePage`, `Person` | DTC wiki + docs projections (hierarchy, sanitizer allowlist); new model (D16); the package parsers for the `wiki`, `docs` and `person` kinds and the person record (D24, D31) | 7 |

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
    curriculum/  coursework/  knowledge_base/
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

Local development uses site `core-link` and `core-unlink` wrappers (P1). Before linking, require
clean dependency manifests and capture their exact prior bytes in a unique `.tmp/` snapshot.
Refuse repeated links or missing/conflicting recovery state. Unlink restores that captured tagged
state without discarding unrelated edits. Resolve the package checkout explicitly because a site
agent worktree is not necessarily a sibling of `community-base`.

Local links must never be committed. Each site's parsed TOML/lock guard rejects path, editable,
branch, missing-tag and mismatched package sources. Run the guard in the actual main CI workflow
before dependency installation; a PR-only workflow does not protect sites that use local merges.

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
    "MAIL_UNSUBSCRIBE_URL_BUILDER": "email_app.hooks.build_unsubscribe_url",
    "MAIL_VERIFY_EMAIL_URL_BUILDER": "email_app.hooks.build_verify_email_url",
    "RELAY_BASE_URL": env("RELAY_BASE_URL"),
    "RELAY_API_KEY": env("RELAY_API_KEY"),
    "RELAY_WEBHOOK_SECRET": env("RELAY_WEBHOOK_SECRET"),
    "STUDIO_TITLE": "AI Shipping Labs Studio",
    "STUDIO_AUDIT_WRITER": "website.audit.write_studio_event",
    "USER_TAGS_ACCESSOR": "accounts.studio_tags.UserTagsAccessor",
}
```

## 5. Template contract for shared public pages

Shared public templates (events list and detail, onboarding steps, account pages, notifications
page, course and unit pages) use:

- `{% extends "community_base/public/base.html" %}`, never `base.html` directly;
- blocks `title`, `meta_description`, `page_head_metadata`, `content`, `extra_js`; nothing else;
- structural class hooks, one per element role, prefixed `cb-`: `cb-page`, `cb-page-header`,
  `cb-page-title`, `cb-list`, `cb-card`, `cb-card-title`, `cb-card-meta`, `cb-badge`,
  `cb-button`, `cb-button-primary`, `cb-form`, `cb-field`, `cb-alert`, `cb-empty`, `cb-pager`;
- no colour, spacing or typography utility classes. A site styles the `cb-` hooks in its own
  stylesheet (AISL adds `@apply` rules in `assets/css/tailwind.css`; DTC adds rules to
  `templates/core/_design_system.html`).

### Who owns the `main` landmark

The page owns it. Every shared public template opens exactly one `<main class="cb-page">` as the
outermost element of its `content` block, and a consuming site's chrome must not open a `main`
around `content`.

A site therefore does nothing to get a correct landmark on every shared public page, and a site
that wraps `content` in its own `main` renders one landmark inside another: invalid HTML, two
competing landmarks for assistive technology, HTTP 200, and no sign of it in a browser.

This was not always true. C7.30 found 34 of the 41 templates bringing their own `main` and 7
bringing none, so a site writing a seam had to choose between a nested landmark on 34 pages and no
landmark on 7, with no way to tell which template a route would use. The 7 were wrapped rather than
the 34 unwrapped, for four reasons, in order of weight:

- the shipped default has to be correct with no site action. With the page owning the landmark, a
  site that installs the package and writes nothing gets one. With the seam owning it, correctness
  would depend on the site's own `base.html`, which the package neither ships nor can require;
- the seam stays a pass-through. It defines no blocks and emits nothing, which is what lets a site
  adopt it without changing a byte of any page, and what a site's own override replaces safely. A
  seam that emitted markup would break both;
- the landmark is a per-page extension point. Sixteen of the templates carry a page-specific hook
  on it (`cb-page cb-events-list`) and one carries data attributes. Moving the element into the
  seam would need a sixth contracted block to put them back, widening the contract for every site;
- the 7 had no `cb-page` hook at all, so they were also the 7 pages a site could not style.

`community_base.kernel.checks.check_public_base_block_contract` reads the chain above the seam for
a `main` and reports `community_base.kernel.W005` when it finds one, naming the template. It is a
warning, not an error: the page still serves its body, and the reading is textual, so a site whose
`main` sits on pages these templates never reach silences that one id. `tests/test_template_contract.py`
asserts the rule over the whole template tree, so a public template added on the wrong side fails
there rather than in a browser.

The two adopting sites sit on opposite sides of this, which is what made the defect visible:

| Site | Chrome | Before C7.30 | After C7.30 |
|---|---|---|---|
| AI-Shipping-Labs/website | `templates/base.html` opens no `main` | 34 pages correct, 7 with no landmark | all 41 correct, no site change |
| DataTalksClub/website | `course_platform_templates/base.html` opens `<main id="main-content">` | 34 pages nested, 7 correct | all 41 nested until the site acts, and W005 says so |

A site in the second position does not delete that `main`, because its own bespoke pages need it.
It puts the element in a block of its own in its base, and empties that block in the seam override
it already owns, so the shared public pages take their landmark from the page and every other page
on the site keeps taking it from the chrome:

```
{# the site's base.html #}
{% block page_landmark_open %}<main id="main-content" tabindex="-1">{% endblock %}
{% block content %}{% endblock %}
{% block page_landmark_close %}</main>{% endblock %}

{# templates/community_base/public/base.html #}
{% block page_landmark_open %}{% endblock %}
{% block page_landmark_close %}{% endblock %}
```

That is a site adoption task, tracked by that site's own process, and W005 is what raises it.

A site may override any shared template by placing a file at the same path under its own
`templates/` directory. The package's `tests/test_template_contract.py` asserts that every shared
public template uses only the blocks and hook classes above.

### The seam: `community_base/public/base.html`

`community_base.kernel` ships that path as a pass-through whose entire body is
`{% extends "base.html" %}`. A site whose own base defines the five block names above needs to do
nothing, and the seam changes no byte of any shared public page on such a site.

A site whose base names those slots differently puts its own
`templates/community_base/public/base.html` in its template directory and maps its names onto the
contracted ones there, once, for every shared public page. Django resolves blocks by name across
the whole inheritance chain rather than by lexical nesting, so wrapping a contracted block in a
site block makes the contracted name reachable from a page template. For a base whose body slot is
`body` and whose script slot is `extra_scripts`:

```
{% extends "base.html" %}
{% block body %}{% block content %}{% endblock %}{% endblock %}
{% block extra_scripts %}{% block extra_js %}{% endblock %}{% endblock %}
```

This is the same mechanism the Studio shell uses with `content` wrapping `studio_content`.

### What happens when a block has nowhere to go

Django drops the content of a block that no template in the chain defines. No exception, no
warning, nothing in the logs: the page returns 200 with the site's chrome and the package's
content missing, and it looks fine. `community_base.kernel.checks.check_public_base_block_contract`
reads the chain above the seam at `manage.py check` time and reports every contracted block with
nowhere to render, naming the block and the package templates that fill it.

| Block | Missing from the chain means | Check id | Severity |
|---|---|---|---|
| `content` | the page has chrome and no body | `community_base.kernel.E001` | error |
| `title` | the page falls back to the site default title | `community_base.kernel.W001` | warning |
| `meta_description` | the page falls back to the site default description | `community_base.kernel.W002` | warning |
| `page_head_metadata` | two mail pages lose their `noindex, nofollow` | `community_base.kernel.W003` | warning |
| `extra_js` | the page renders and its progressive enhancement is dead | `community_base.kernel.W004` | warning |

The same check reports one thing that is not a block: a `main` in the chain, which nests inside the
one every public page opens.

| Condition | Means | Check id | Severity |
|---|---|---|---|
| the chain opens a `main` around `content` | shared public pages render a nested landmark | `community_base.kernel.W005` | warning |

`community_base.kernel.E002` is raised instead when the chain cannot be read at all, which is a
louder failure: every shared public page would raise on render.

The check skips a package template the site has shadowed with its own copy at the same name,
because a site's own template fills the site's own blocks. It cannot know which pages a site
mounts, so it reports an unreachable block whether or not the page is reachable. A site that has
answered one of the four warning blocks under a name of its own silences that one id with
`SILENCED_SYSTEM_CHECKS`. The reasoning, and what was rejected, is in
`docs/plan/evidence/c7.25-block-contract-decision-2026-09-18.md`.

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

A parser is a consumer of the document toolkit, never a second implementation of it.
`content_sync.documents` reads a repository once (the collection walk, the two file shapes, the
core and kind keys, slug, `sort_order`, `required_level`, identity and checksums),
`content_sync.resolution` resolves its assets and cross-references, `content_sync.rendering` is
the one renderer and the one sanitiser, and `content_sync.kinds` holds the layouts and schemas.
What is left for a parser is the mapping onto its app's models. The course parser,
`curriculum/parsers.py`, is the shape of that: one parser for one format, registered once as
`curriculum_course`, with no layout sniffing and no second key validation (decision D23, issue
C7.10).
