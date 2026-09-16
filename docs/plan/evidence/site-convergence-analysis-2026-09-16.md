# Site convergence analysis

Date: 2026-09-16. Code-derived feature comparison of `AI-Shipping-Labs/website` (AISL),
`DataTalksClub/website` (DTC) and this package. Read from the code, not from `docs/00-analysis.md`,
which is dated 2026-09-05 and is stale on several points recorded in section 7.

Purpose: decide what the two sites should share, what they should converge on, and what stays
site-owned. The plan issues that follow from it are `C4.1e` (phase 4) and phase 7.

Method: `INSTALLED_APPS` and root URLconf of both sites; every app's models, urls, services, views,
`apps.py` and management commands; the package's apps, hooks, registries and tests. Line counts
exclude tests and migrations.

## 1. Scale

| Measure | AISL | DTC | community-base |
|---|---|---|---|
| App source lines | ~182,000 | ~110,000 | ~35,000 |
| Test functions | ~18,000 | ~4,000 | 1,051 |
| Studio routes | 330 | 26 | 119 |
| API routes | 166 plus 24 member | 30 public plus 29 admin | 43 plus 7 self |
| Runtime settings keys | 147 declared in the package registry | 28 in `core.OperationalSetting` | 91 in `COMMUNITY_BASE` |
| Package pin | `v0.3.9` | `v0.3.0` | `0.3.8` in tree |

Package adoption today, counted as `community_base.*` imports per site:

| Package app | AISL | DTC |
|---|---|---|
| `mail` | 179 | 30 |
| `config` | 117 | 8 |
| `content_sync` | 106 | 47 |
| `jobs` | 22 | 54 |
| `kernel` | 11 | 8 |
| `api` | 9 | 2 |
| `studio` | 1 | 0 |

No site imports `accounts`, `events`, `curriculum`, `coursework`, `questionnaires`, `onboarding`,
`community`, `notifications`, `comments` or `voting`.

## 2. Common and already on community-base

| Capability | Package app | Adoption state |
|---|---|---|
| Runtime settings, typed, encrypted, audited, Studio-editable | `config` | AISL cut over; `integrations/config.py` is a shim over the package. DTC bridges through `core/configuration.py` and a copy migration but still runs `OperationalSetting` in parallel. |
| Durable jobs | `jobs` | Done on both sides. DTC deleted its own `jobs` app. AISL wraps the runner as `django_q` tasks. |
| Durable mail | `mail` | Both dual-mounted mid-cutover. AISL is on the transitional `ses_local` backend. DTC still runs the Datamailer client and outbox alongside. |
| GitHub content sync engine | `content_sync` | Both register site-owned parsers. DTC still runs its legacy staged pipeline in parallel. |
| API keys, route registry, OpenAPI with drift check | `api` | Thin relative to either site's own API. |
| Access policy seam, levels 0, 5, 10, 20, 30 | `kernel.access` | AISL implements `TierAccessPolicy` against it. DTC has no tiers, per D5. |

## 3. Common, built in the package, adopted by neither site

Every app in this table carries a provisional initial migration and is imported by no site.

| Capability | Package app | Donor | Gap against the donor |
|---|---|---|---|
| Email-first user, verification, reset, email change, aliases, merge, privacy export | `accounts` | AISL | No `slug`, no `contact_tags` many-to-many, no custom session model. AISL has `AccountSession(AbstractBaseSession)`. |
| Member profile | `accounts.MemberProfile` | DTC field contract | DTC's equivalents still live on `CustomUser`. |
| Questionnaires and AI onboarding chat | `questionnaires` | DTC | No plain non-AI response form is routed; only `ai/`, `ai/message/` and `ai/stream/` exist. |
| Onboarding flows | `onboarding` | neither | A new abstraction matching no site's current code. |
| Slack grants and Calendly calls | `community` | Slack from DTC's model, Calendly from AISL's | Calendly is flag-gated in public views but not in Studio. See section 6. |
| Notifications, comments, voting | three apps | AISL | `voting` default poll levels are literally AISL's values. |
| Events | `events` | AISL schema, DTC `public_id` | No `EventInstructor`, `EventJoinClick` or `HostInviteDelivery`. Carries `EventAlias`, which is being removed by `C4.1e`. |
| Curriculum | `curriculum` | both, split at the parser layer | No `CurriculumFormat`, `DeliveryMode`, `CurriculumRouteAlias` or `SharedCurriculum` family. |
| Coursework | `coursework` | DTC | View layer is about 960 lines against the donor's about 10,300. Deadline reminders are 156 lines against the donor's 781. |
| Studio shell | `studio` | AISL | 18 destinations and 119 routes against AISL's 330 routes and 175 templates. |

## 4. Different today, worth integrating

| Capability | AISL today | DTC today | Convergence note |
|---|---|---|---|
| Wiki | none | `content/wiki_content.py`, podwiki parser, knowledge graph | Owner decision D16: AISL gains a wiki and the capability becomes shared. |
| Docs | none | `content/docs_projection.py`, `docs_presentation.py`, hierarchical tree | Owner decision D16: AISL gains docs and the capability becomes shared. |
| Authentication | email and password, verification TTL, resend throttle, reset | social login only; password reset and email management routed to a disabled stub | The package ships AISL's full stack. DTC adopts a strict subset. Password auth stays optional. |
| User model | 30 or more fields including Stripe, tier, Slack and import provenance | `role`, `certificate_name`, `country`, `identity_state`, `normalized_email` and seven identity-migration tables | The package `User` already merges both. Site-only fields move to extension models under A3.2 and D3.1. |
| Events ownership | database-authored with Zoom lifecycle | GitHub-authored with a numeric `public_id` | Already merged in the package. DTC converges under D4.1. |
| Curriculum ingestion | one engine, including courses | a second bespoke pipeline in `content_sync/course_repository_*.py` that borrows only the jobs runner | The package already implements DTC's repository layout as a `content_sync` parser. D5.1 retires the bespoke pipeline. |
| Staff API and Studio | 166 routes, apispec OpenAPI | 61 capabilities generating the Studio page and the admin API from one declaration | Candidate. DTC's capability declaration is the stronger pattern. Needs an owner decision before an issue exists. |
| Optimistic concurrency | none | `RevisionedModel` compare-and-swap, `AppendOnlyManager` | Candidate. The package has no equivalent and DTC's admin API assumes these bases. |
| Articles | concrete `content.Article` model | `SyncedDocument` plus a typed projection | Candidate. A real modelling clash; mergeable only by choosing one shape. |
| Sessions | custom database-backed session model | Django default | Candidate. The package should take AISL's. |

## 5. Site-owned, not to be merged

AISL only: payments, tiers and Stripe, 14 models with dunning, reconciliation and checkout-fraud
guards; sprint plans, 24 models; CRM with Slack-thread progress ingestion; book club; analytics and
UTM attribution; outbound webhooks and embeddable claim widgets; Maven; Calendly round-robin
booking; banner generator; AI evaluation harness.

DTC only: podcast with its own `s<N>e<N>` identity scheme; FAQ; people profiles; sponsors and
placements; event Q and A, five models with hand-rolled QR generation; historical registration
aggregates, five revisioned models; the CMP, Mailchimp and Datamailer legacy imports; the `cadmin`
redirect shim; Wrapped.

Both sites, not shared: the public design systems. AISL uses Tailwind 3.4 with HSL tokens and a
build step. DTC uses one 3,892-line `_design_system.html` included inside each page's own `style`
tag, with no external stylesheet link and dark mode keyed on `body.dark-mode`. Both are enforced by
tests. Owner confirmed on 2026-09-16 that public templates stay site-owned; this is the public-pages
clause of D12.

Also not shared: the test harnesses. DTC has a 43KB `conftest.py` with an autouse network-denial
guard and PII redaction scanning, plus separate `playwright_tests/`, `e2e/` and `tests_ci/` suites.
AISL gates on diff-based `make test-affected` with an 85 percent coverage floor.

## 6. Package findings raised by this pass

- `events.EventAlias` ships five alias kinds. DTC dropped the model and table on 2026-09-11 in
  `events/migrations/0007_delete_eventalias.py`. AISL never had an events-specific alias model and
  solves the same problem generically with `integrations.Redirect`. Removed by `C4.1e` under D17.
- `coursework` has no `README.md`. It is the largest package app at 6,031 lines and is the only app
  besides `testing` with no README, and the only domain app with no provisional marker in either a
  README or a migration, so its schema status is unstated.
- `questionnaires/README.md` line 42 documents `get_or_create_response(questionnaire, respondent)`.
  No such function exists. The nearest real function is `get_or_create_ai_onboarding_response(user)`
  in `services_onboarding_ai.py`, a different module and signature.
- `kernel/conf.py` defines 91 `COMMUNITY_BASE` keys. `kernel/README.md` documents 35.
- `EVENT_URL_STYLE`, `EVENT_PRIVACY_NOTICE_VERSION` and `EVENT_NEWSLETTER_CONSENT_VERSION` exist in
  both `kernel.conf` and the `config` registry as independent, unlinked values. Runtime code reads
  the `kernel.conf` copy.
- `mail/preferences.py::allow_all` has no callers anywhere in the package or its tests.
- `studio.providers` and `studio.user_registry` are implemented and tested registries with no
  registered producers anywhere in the package.
- Calendly is gated in the public views of `community` but not in its Studio views or its Studio
  destination registration, so a site with `CALENDLY` false still shows two working, empty Studio
  sections. See `C7.3`.

## 7. Corrections to docs/00-analysis.md

| Claim in the 2026-09-05 analysis | State on 2026-09-16 |
|---|---|
| DTC keeps `public_id` and aliases as an events extension | DTC deleted `EventAlias` outright on 2026-09-11. |
| DTC has a capability registry driving Studio and admin API parity | True, and larger than implied: 61 capabilities composed from per-app tuples, not a prototype. |
| DTC identity is allauth plus course-platform fields | Also: DTC is social-login only. Password reset and email management routes are wired to a disabled stub. |
| DTC content sync will adopt AISL's workflow | Done for editorial content. Course curriculum ingestion is still a separate bespoke pipeline. |
| DTC jobs use leases, fences and after-commit dispatch | DTC's own `jobs` app is deleted; it runs on the package app against Relay. |

## 8. Headline

Buckets 2 and 3 hold comparable capability counts, but bucket 2 is roughly 23,000 lines behind
provisional migrations that nothing imports, while bucket 1 is roughly 12,000 lines live on both
sites. The risk concentrates in the view layers: `coursework` is about a tenth of its donor and
`studio` about a third of its donor. Ported there currently means models and services ported and
screens not.
