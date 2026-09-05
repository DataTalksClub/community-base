# Analysis: what the two sites and Relay contain today

Date: 2026-09-05. Snapshot of `AI-Shipping-Labs/website` (AISL), `DataTalksClub/website` (DTC)
and `DataTalksClub/relay`. Numbers are approximate and will drift; the structure will not.

## 1. Inventory

| | AISL | DTC | Relay |
|---|---|---|---|
| Commits / first commit | 2,920 / 2026-02 | 982 / 2026-08 | 213 / 2026-05 |
| Django apps | 20 | 18 (5 are course-platform compatibility shells) | 3 (`mailing`, `taskdeck`, `jobs`) |
| Source lines (no tests, no migrations) | ~170k | ~110k | small |
| Test functions | ~18,200 | ~4,050 | ~500 |
| Templates | 392 | 176 | own |
| Migrations | ~310 | ~24 | own |
| Settings module | `website/settings.py` (single file) | `website/settings/{base,local,test,development,production}.py` | `relay/settings.py` |
| User model | `accounts.User` (email login, tier, Stripe ids, bounce state, Slack ids, preferences, tags, import metadata) | `accounts.CustomUser` (course-platform legacy fields, identity reconciliation state) | staff only, OIDC |
| Frontend | Tailwind 3.4 compiled by `make css-build`, HSL tokens, Lucide icons | Own inline design system (`templates/core/_design_system.html`), one inline `<style>` and zero external stylesheets per public page, enforced by test | own |
| Runtime configuration | `integrations.IntegrationSetting` + `integrations/settings_registry.py` + Studio page + cross-process stamp cache | `core.OperationalSetting` typed, versioned, audited, declared in `core/operational_settings.py` + Studio page | environment |
| Jobs | django-q2 + `jobs` app (task history, task entities, Studio worker page, `setup_schedules`) | django-q2 + `jobs.DurableJob` (leases, fences, heartbeat, scheduler lease, `dispatch_after_commit`) | `django.tasks` + webhook tasks + cron schedules + read-only status contract |
| Email | Direct SES v2 through `email_app.services.EmailService`; 50 markdown templates in `email_app/email_templates/`; DB template overrides; `EmailLog`; campaigns; SES event ingress | Relay link bridge (open, click, unsubscribe) implemented in `email_app`; `EmailDelivery` intent specified in `_docs/specs/05-events-registration-email.md` but not built; course-platform mail still goes through the Datamailer outbox (`course_management/datamailer_outbox*.py`, `data` app) | Multi-tenant (organisation, audience, client), contacts, tags, subscriptions, campaigns, transactional templates (`PUT /api/transactional/templates/{key}`), `POST /api/transactional/send`, `POST /api/tasks`, `POST /api/schedules`, SES |
| Content | GitHub to DB sync (`integrations/services/github_sync/`): articles, courses, workshops, projects, links, downloads, tiers YAML | GitHub to DB with staged `ContentRelease`; owner decision #226 replaces it with AISL's direct-upsert workflow; articles, podcast, people, docs, FAQ, podwiki | none |
| Events | DB-owned: `Event`, `EventSeries`, `Host`, `EventRegistration`, `SeriesRegistration`, `SeriesOccurrenceOptOut`, `EventFeedback`, reminders, ICS, Zoom, banners, recap, recording | GitHub-owned `Event` with UUID plus numeric `public_id` and `EventAlias`; lifecycle; Q&A sessions; historical registration aggregates; accountless registration only in spec | none |
| Courses | `content.Course/Module/Unit` synced from `course.yaml`; per-unit tier gating and drip; `UserCourseProgress`; simple `Cohort`/`CohortEnrollment`; `CourseAccess` purchases; certificates; light peer review | Course platform adopted as `courses`: `Course` to `Cohort` split, curriculum import from GitHub with `SourceProvenanceModel`, homework with questions/answers/scoring, projects with criteria and peer review, leaderboards, `RegistrationCampaign`, certificates, wrapped statistics | none |
| Studio | `studio`: 27k lines, 60 view modules, 177 templates, 8 sidebar sections hardcoded in `studio/sidebar.py`, list-page conventions in `_docs/studio-conventions.md`, global search, impersonation, settings, worker, sync, email log, users import and merge | `studio` (capability registry in `management_registry.py` driving Studio and admin API parity: settings, navigation, sponsors, credentials, audit) and `studio_courses` (course-platform admin) | ops views |
| Admin API | `api` (31k lines, apispec OpenAPI in `api/openapi/`, `accounts.Token`, `asl_cli`), `member_api` with `accounts.MemberAPIKey` scopes | `management_api` + `management_auth` (principals, credentials, rate classes, idempotency records) driven by the capability registry | client API keys |
| Onboarding | `/onboarding/`: self-identification, persona, questionnaire fill or AI chat (`accounts/views/onboarding*.py`, `questionnaires`); sprint plans in `plans` | `MemberProfile` v1 specified in `_docs/specs/01-platform-architecture.md`; not implemented | none |
| Only here | `payments` (tiers, Stripe), `plans` (sprints), `crm`, `bookclub`, `analytics` (UTM), `triggers` (outbound webhooks), Maven, Calendly | people, podcast, podwiki, FAQ content; sponsors; navigation; audit; event Q&A; course platform | transport |

## 2. Overlap map

"Donor" is the codebase the shared implementation starts from.

| Capability | AISL today | DTC today | Donor | Fit |
|---|---|---|---|---|
| Email verification, password reset, email change, aliases, merge, privacy export, timezone | complete | partial (allauth plus course-platform fields) | AISL | high, as mixins and services; no shared concrete user model |
| Member profile and onboarding | questionnaires, personas, AI chat, plans | spec only | AISL, plus the DTC profile field contract | high |
| Slack access and identity | `community` app | `SlackAccessGrant` in spec | AISL | high |
| Studio shell, sidebar, staff auth, list helpers, global search, impersonation | hardcoded sections, 1,288-line base template | design-system base, capability registry | AISL shell; DTC registry idea for the API | high for staff surfaces |
| Users management in Studio | list, detail, export, import, merge, notes, tags | minimal | AISL | high |
| Runtime settings | `IntegrationSetting` | `OperationalSetting` | AISL UI and registry, DTC typing and audit | high |
| GitHub content sync engine | source lock, checkout, parse, upsert, `SyncLog` | staged releases, to be replaced (decision #226) | AISL | high, DTC already decided this |
| Events with series, registration, reminders, ICS, Zoom | complete | GitHub read model, registration in spec | AISL | high; DTC keeps `public_id` and aliases as an extension |
| Notifications, comments, voting | complete | none | AISL | high, small, self-contained |
| Jobs | history and Studio page | leases, fences, after-commit dispatch | DTC model, AISL Studio page, Relay transport | high |
| Email transport | direct SES | Relay (spec) | Relay plus DTC intent model | high |
| Curriculum from GitHub, progress, gating | complete | course-platform import | AISL rendering and gating, DTC provenance | medium, largest model merge |
| Coursework (homework, projects, peer review, leaderboard, certificates) | light | complete | DTC | medium, optional app |
| Workshops, downloads, tutorials, projects, curated links, tiers YAML | complete | none | stay in AISL on top of shared sync | low |
| Payments and tiers | complete | none | AISL only, behind the access hook | not shared |
| Public page markup and design system | Tailwind | inline system | none | not shared; block contract only |

## 3. Coupling audit (AISL)

Import counts are the number of files in the row app that import from the column app. This is why
extraction must cut seams first: `events` and `content` import each other, and `studio` imports
everything.

| App | Imports from |
|---|---|
| `events` | content (45 files), accounts (34), integrations (31), email_app (29), payments (7), notifications (7), community (3), studio (2), plans (2), bookclub (2), analytics (2), jobs (1) |
| `content` | events (41), integrations (28), accounts (20), plans (12), payments (8), notifications (8), questionnaires (6), studio (5), voting (4), community (3), bookclub (3) |
| `accounts` | email_app (25), questionnaires (18), payments (18), integrations (18), content (9), community (6), plans (4) |
| `community` | accounts (25), integrations (14), payments (12), content (4), plans (3), analytics (3) |
| `email_app` | accounts (22), integrations (16), events (3), content (3), payments (2), jobs (2) |
| `notifications` | content (10), events (9), voting (4), integrations (4), accounts (3), plans (2), payments (2), comments (2) |
| `comments` | notifications (4), content (4), accounts (3), plans (2), events (1), bookclub (1) |
| `voting` | accounts (6), content (4), notifications (1) |
| `questionnaires` | integrations (11), community (3), content (2), crm (1) |
| `jobs` | integrations (11), events (5), email_app (3), content (2) |
| `studio` | integrations (118), events (83), content (82), accounts (70), email_app (54), plans (53), payments (49), crm (21), questionnaires (19), notifications (18), community (14), jobs (12), analytics (11), bookclub (6) |

Most `integrations` imports are `get_config`, `is_enabled` and the Zoom, banner, S3 and Slack
service clients. Most `payments` imports are tier level checks. Most `email_app` imports are
`EmailService().send(...)`. These three become the config, access-policy and mail seams described in
`docs/02-architecture.md`, which removes the majority of the coupling before any code moves.

## 4. Facts that shape the plan

- Both sites already run Django 6.0 on Python 3.13 with uv, allauth (Google, GitHub, Slack), and
  django-q2, and both deploy to ECS from GitHub Actions. There is no framework gap to close.
- AISL is in production with ~310 migrations; DTC is not yet serving the apex domain and has ~24
  migrations. AISL therefore donates most code and its migration history must be preserved; DTC
  can accept table rebuilds during a freeze.
- Both sites have the same app labels for `accounts`, `content`, `email_app`, `events`, `jobs`,
  `studio` and `api`. Only some of those can be replaced wholesale by a package app with the same
  label; the rest get a `cb_` prefixed label. See `docs/02-architecture.md`, section 3.
- The DTC decision log (`_docs/specs/open-decisions.md`, #226) already commits DTC's content sync to
  AISL's workflow, and its spec 05 already defines the Relay email intent model the package builds.
- Relay already exposes template upsert, transactional send, task submission with idempotency keys,
  signed webhook tasks and cron schedules. It runs in a sandbox only; production is a Phase 1
  prerequisite.
- The two design systems are incompatible and both are enforced by tests. Public templates are
  therefore not shared; the Studio shell is shared with one design (decision D12).
