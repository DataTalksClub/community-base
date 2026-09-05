# Accounts

`community_base.accounts` owns the shared email-first user and private member profile. It also owns
authentication, member self-service, account domain services and Studio account operations. It uses
the kept Django app label `accounts` and database table `accounts_user`.

The initial migration is provisional. Do not tag or release a package containing it until the AISL
and DTC schema-preparation issues and C3.7 compatibility rehearsal are complete.

## Installation

Set the shared model before the first migration:

```python
AUTH_USER_MODEL = "accounts.User"
```

Install the required Django and allauth applications before the package apps. The Django
applications are auth, sessions, sites and messages. Install `community_base.kernel`,
`community_base.accounts`, `community_base.api`, `community_base.jobs` and `community_base.mail`.
Studio is optional for public/member operation but is required for the staff routes in this
document.

Apply the portable allauth policy in the settings module:

```python
from community_base.accounts.settings import allauth_settings

globals().update(allauth_settings())
```

This configures email-only identity, no username field and package verification/reset entry points.
It also configures the package social adapter plus Google, GitHub and Slack provider scopes. Sites
still create their own allauth `SocialApp` rows and own provider credentials. DTC may override the
adapter during its identity-quarantine adoption work.

Mount the route groups:

```python
from django.urls import include, path

from community_base.api.registry import urlpatterns as api_urlpatterns

urlpatterns = [
    path("accounts/", include("community_base.accounts.urls")),
    path("api/v1/", include((api_urlpatterns(), "cb_api"))),
    path("studio/", include("community_base.studio.urls")),
    path("studio/", include("community_base.accounts.studio_urls")),
]
```

`AccountsConfig.ready()` registers member self routes with the API registry. Build the API URL list
after Django application startup, as in a normal root URL module. When Studio is installed it also
registers Account operations under People. `studio_routes --check` fails if the accounts Studio URL
group was not mounted.

Public templates extend the site's `base.html`, and the account page is `/accounts/account/`. A site
may override any package template by placing the same relative path in a template directory that is
searched before `APP_DIRS`.

## User fields

The model retains standard `AbstractUser` permissions, names, active/staff state and timestamps.
It removes `username` and uses `email` as the unique login identifier.

| Group | Fields | Contract |
|---|---|---|
| Verification | `email_verified`, `verification_expires_at`, `verification_reminder_sent_at`, `verification_resend_claimed_at`, `verification_resend_claim_token` | Verification lifetime and database-clock resend claim state |
| Mail preference | `unsubscribed`, `email_preferences`, `soft_bounce_count`, `bounce_state`, `bounce_recorded_at`, `last_bounce_diagnostic` | Global/category suppression and delivery health |
| Community identity | `slack_user_id`, `slack_member`, `slack_checked_at` | Shared identity state; workspace calls remain site-owned |
| Display | `theme_preference`, `preferred_timezone`, `dashboard_dismissals` | Member-controlled presentation state |
| Classification | `tags`, `signup_source`, `account_activated` | Shared lifecycle and operator labels |
| Import provenance | `import_source`, `imported_at`, `import_metadata` | Earliest source and source-scoped adapter metadata |

Payment tier, subscription, Stripe customer, course learner and certificate fields do not belong on
the shared user. Sites put those values in domain-owned one-to-one or relationship models.

## Member profile fields

`MemberProfile` is a private one-to-one user record rather than a public editorial person.

| Field | Type and rule |
|---|---|
| `country` | Required for completion; ISO 3166-1 alpha-2 |
| `work_status` | Required stable choice |
| `organisation` | Optional trimmed text, 160 characters |
| `professional_role` | Required stable choice |
| `seniority` | Required stable choice |
| `about`, `ambitions`, `why_joined` | Required trimmed plain text, 1 to 1,000 characters at completion |
| `github_url`, `linkedin_url`, `website_url` | Optional HTTP/HTTPS URL without userinfo or control characters |
| `completion_version`, `completed_at` | First satisfied profile schema and its completion time |
| `revision`, `confirmed_revision` | Optimistic concurrency and the last member-confirmed revision |

Completion version 1 requires all required fields and a verified account email. A completed profile
cannot clear a required field. Ordinary valid edits retain completion and the original completion
time.

## Member routes

| Method and path | Purpose |
|---|---|
| `GET /api/v1/me` | Read member-controlled account state |
| `PATCH /api/v1/me` | Update names, email preferences, timezone, theme or add one card dismissal |
| `GET /api/v1/me/profile` | Read profile, missing fields, completion state and ETag |
| `PATCH /api/v1/me/profile` | Update allowlisted profile fields with strong `If-Match` |
| `POST /api/v1/me/password` | Change or establish a password and retain the session |
| `GET /api/v1/me/data-export` | Download the portable privacy export and write an audit row |
| `POST /api/v1/me/deletion-request` | Create or return the active deletion request |

These endpoints use Django session authentication, private no-store responses and normal Django
CSRF enforcement for mutations. Profile PATCH accepts `If-Match: "rev-0"` for a missing profile and
returns `409` with the current revision for a stale write. They are declared in the generated
OpenAPI document.

## Domain services

Use the modules under `community_base.accounts.services` as the integration boundary:

- `email_resolution`: normalize and resolve active primary/alias identity.
- `verification`: unverified TTL and database-clock resend claims.
- `aliases`: validated operator alias add/remove.
- `email_change`: password-protected, throttled and single-use email changes.
- `merge`: transactional merge, dry run, API-key revocation and secondary scrubbing.
- `privacy`: portable export, idempotent requests and local deletion/anonymization.
- `free_welcome`: idempotent durable welcome intent.
- `timezones`: IANA validation, options and display formatting.
- `import_users`: adapter registry, reconciliation, audit batches and rollback-only dry run.
- `profile`: profile version 1 validation, completion and revision compare-and-swap.
- `account_settings`: bounded member-controlled account updates.

Import adapters return `ImportRow` objects. Keep course CSV aggregation, Stripe subscription/tier
mutation, Slack workspace access and site queue pacing outside the generic service. Dry run performs
the real reconciliation inside a rolled-back transaction. It returns planned counts but persists no
user, batch or mail delivery.

## Mail purposes

Accounts sends these logical mail purposes: `accounts.verify_email`, `accounts.password_reset`,
`accounts.email_change_confirm`, `accounts.email_changed_notice` and `accounts.free_welcome`.
Verification, reset and email-change bearer URLs are created by the mail context resolver only while
a worker sends. Durable `EmailDelivery.context_data` contains no bearer token. Sites own catalog
templates and branding.

The default `MAIL_PREFERENCE_RESOLVER` suppresses globally unsubscribed users, permanent bounces and
explicit false category preferences. Enabling the newsletter preference clears global unsubscribe,
matching the member account control.

## Extension hooks

Configure hooks as callables or dotted paths in `COMMUNITY_BASE`:

| Key | Called for |
|---|---|
| `ACCOUNT_MERGE_HOOK` | Site relation reconciliation inside the merge transaction |
| `ACCOUNT_PRIVACY_EXPORT_HOOK` | Additional site-owned export sections |
| `ACCOUNT_DELETION_BLOCKER` | Subscription or other policy that blocks deletion |
| `ACCOUNT_BEFORE_DELETE_HOOK` | Site row erasure/anonymization inside the delete transaction |
| `ACCOUNT_UNVERIFIED_TTL_DAYS` | Positive verification lifetime in days |

Hooks must not import the site into the package. The configured site callable imports and owns its
domain models. Merge and delete hooks execute inside atomic operations and must be safe to roll back.

## Studio operations

Mount `community_base.accounts.studio_urls` under the same prefix as the Studio shell.

Staff can:

- create an activated passwordless account and optionally queue the free welcome.
- run a UTF-8 CSV import as a rollback-only dry run or committed audited batch.
- dry-run and confirm an account merge.
- review recent import batches, privacy requests and email-change state.

The create operation synchronizes a primary allauth `EmailAddress` for a verified user. Staff cannot
force a merge involving staff/superuser accounts. Only a superuser can do that. Review templates
never render an email-change token or token hash.

## Adoption assumptions

Package and site adoption follow these constraints:

- Never point a site at a branch or local path. A site adopts only an allowed package tag.
- Do not create a tag while the accounts initial migration is provisional.
- The package never imports payment, course, CRM, Slack workspace or other site applications.
- Donor-equivalence tests, migration `replaces`, row-count rehearsal and deployed smoke belong to
  C3.7 and the site adoption issues.
- Site templates may change presentation, but they do not weaken session ownership, CSRF,
  `If-Match`, redaction or private-cache behavior.
