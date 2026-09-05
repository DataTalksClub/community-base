# Phase 3: accounts and auth, onboarding, community, notifications, comments, voting

Goal: one user model and one authentication stack (decision D14); onboarding flows per site and
per group (D6); Slack access; notifications, comments and voting available to both sites.

Freeze: AISL one weekend (A3.3), DTC one weekend (D3.2).

Exit criteria:

- Both sites: `manage.py shell -c "from django.contrib.auth import get_user_model as g; print(g().__module__)"`
  prints `community_base.accounts.models`.
- AISL: `ls accounts/` shows only `accounts_ext` remnants moved to `payments` and `accounts_ext`;
  `questionnaires/`, `community/`, `notifications/`, `comments/`, `voting/` directories do not
  exist.
- DTC: a new member can register, verify email, complete the configured onboarding flow and see
  the Slack access page.

## C3.1a Target accounts schema

Repository: community-base. Depends on: C2.4.

Read first
- `~/git/ai-shipping-labs/accounts/models/` (including `UserManager` in `models/user.py`) and
  model tests.
- `~/git/dtc-website/_docs/specs/01-platform-architecture.md` "Member profile version 1";
  `accounts/models.py`.

Shared `User` field table (the only fields the shared model has):

| Field | Origin |
|---|---|
| `email` unique, `username` removed, `first_name`, `last_name`, `is_staff`, `is_active`, `is_superuser`, `date_joined`, `last_login` | Django plus AISL manager |
| `email_verified`, `verification_expires_at`, `verification_reminder_sent_at`, `verification_resend_claimed_at`, `verification_resend_claim_token` | AISL |
| `unsubscribed`, `email_preferences` JSON, `soft_bounce_count`, `bounce_state`, `bounce_recorded_at`, `last_bounce_diagnostic` | AISL |
| `slack_user_id`, `slack_member`, `slack_checked_at` | AISL |
| `theme_preference`, `preferred_timezone`, `dashboard_dismissals` JSON | AISL |
| `tags` JSON, `signup_source`, `account_activated`, `import_source`, `imported_at`, `import_metadata` | AISL |

Not shared, moved to site extension models before the swap: AISL `tier`, `pending_tier`,
`billing_period_end`, `stripe_customer_id`, `subscription_id` (to `payments.Membership`); DTC
`role`, `certificate_name`, `country`, `region`, `registration_role`, `github_url`,
`linkedin_url`, `personal_website_url`, `about_me`, `dark_mode` (to `courses.LearnerProfile`),
identity state fields (to `accounts_ext.IdentityState`).

Steps
1. `community_base/accounts/models.py` (`label = "accounts"`, `db_table = "accounts_user"`):
   `User(AbstractUser)` with the table above, `UserManager` from AISL, `BounceState` choices;
   `EmailAlias`, `EmailChangeRequest`, `PrivacyRequestLog`, `ImportBatch` from AISL;
   `MemberProfile(user OneToOne)` with the DTC spec fields (country, work status, organisation,
   role, seniority, about, ambitions, why joined, links, completion version, revision).
2. Generate a provisional initial migration without `replaces`. Keep it untagged. C3.7 records
   donor inventories and finalizes the squash only after A3.1 and D3.1 prepare compatible schemas.
3. Move or adapt model and manager tests. Record which donor model tests are package-owned,
   site-owned or deferred to compatibility.

Verification
- `make check && make test tests/accounts/test_models.py` -> pass.
- Fresh database migrate, reverse `accounts` to zero and reapply -> pass.
- `User._meta.db_table` is `accounts_user`; the app label is `accounts`; no site import exists.

## C3.1b Authentication and public account entry points

Repository: community-base. Depends on: C3.1a.

Read first
- `~/git/ai-shipping-labs/accounts/` auth views, forms, signals, urls, templates under
  `templates/accounts/` and `templates/account/`; `website/settings.py` allauth section.
- `~/git/dtc-website/_docs/specs/01-platform-architecture.md` "Member signup, profile, Slack, and
  course registration"; `accounts/forms.py`, `course_platform_templates/account/` and
  `website/settings/base.py` allauth section.

Steps
1. Move views from `accounts/views/auth.py` (login, register, verify email, resend, password
   reset request and reset), allauth adapter and `ACCOUNT_*` and `SOCIALACCOUNT_*` settings
   helper `community_base.accounts.settings.allauth_settings()` returning the dictionary both
   sites use today (compare AISL `website/settings.py` and DTC `website/settings/base.py`; where
   they differ, choose the AISL value and list the differences in the pull request).
2. Move the public forms, signals, URLs and templates through the public template contract.
3. Adapt authentication and verification tests without tier or Stripe assumptions.

Verification
- `make check && make test tests/accounts/test_auth.py` -> pass.
- `testproject`: register, verify with the memory outbox, log in, request a password reset and
  complete the reset.

## C3.1c Account domain services and mail preferences

Repository: community-base. Depends on: C3.1b.

Read first
- `~/git/ai-shipping-labs/accounts/services/`, account/settings views and forms, API integrations,
  Studio account operations and tests.
- `~/git/dtc-website/_docs/specs/01-platform-architecture.md` member profile sections and profile
  forms.

Steps
1. Services: verification, email change, aliases and resolution, merge, privacy export and
   deletion, free welcome (mail purpose), timezone, import users (batches). Import from
   `~/git/ai-shipping-labs/accounts/services/`.
2. Mail preference resolver: implement `MAIL_PREFERENCE_RESOLVER` default reading
   `User.email_preferences` and `unsubscribed` and `bounce_state`, replacing the Phase 1 default.
3. Adapt service tests without tier, Stripe, Slack workspace or site email-template assumptions;
   record the donor behavior matrix for later extraction.

Verification
- `make check && make test tests/accounts/test_services.py` -> pass.
- `testproject`: preference resolver suppresses global unsubscribe and permanent bounce, and an
  import dry run writes no users or batches.

## C3.1d Account pages and self API

Repository: community-base. Depends on: C3.1c.

Read first
- `~/git/ai-shipping-labs/accounts/views/account.py`, account forms, templates and API tests.
- `~/git/dtc-website/_docs/specs/01-platform-architecture.md` member profile sections and profile
  forms.

Steps
1. Add the account page and self API: `/api/v1/me`, `/api/v1/me/profile` GET and PATCH with
   revision check, email preferences, timezone, dismiss card, change password and data export
   request.
2. Add account templates following the public template contract.
3. Adapt member-owned permission, validation, stale-write and privacy-request tests.

Verification
- `make check && make test tests/accounts/test_self_api.py` -> pass.
- `testproject`: complete profile through PATCH with `If-Match` -> 200; stale revision -> 409.

## C3.1e Studio account operations and documentation

Repository: community-base. Depends on: C3.1d.

Read first
- `~/git/ai-shipping-labs/accounts/` Studio account operations, import commands and tests.
- `community_base/studio/README.md` and C2.2 user registries.

Steps
1. Add Studio user create, CSV import (batches and dry run), merge, privacy-request and email-change
   review operations, registered into the `People` section; extend C2.2 registries.
2. Classify AISL `accounts/tests/` (22k lines) as adapted or site-owned in the C3.1 coverage
   matrix; copied-test count remains a C3.7 extraction gate.
3. Document the accounts field table, allauth settings helper, hooks, routes and integration
   assumptions.

Verification
- `make check && make test tests/accounts` -> pass.
- `testproject`: staff can create, dry-run import and review account operations; non-staff gets
  403 or the standard Studio denial response.

Done when
- [ ] `community_base/accounts/README.md` lists the field table, the allauth settings helper and
  the hooks

## C3.2 Questionnaires

Repository: community-base. Depends on: C3.1e. Playbook P4 for `questionnaires` (label kept).

Read first
- `~/git/ai-shipping-labs/questionnaires/` (models, services, onboarding.py, views, templates).

Steps
1. Lift models, services, fill-in renderer, Studio pages (questionnaires, personas, responses).
2. The AI conversation models and views (`OnboardingConversation`, `OnboardingTurnAttempt`,
   `Message`) move with the app; the Anthropic client comes from the `ai` extra and is used only
   when `COMMUNITY_BASE["AI_ONBOARDING"]` is true and a key is configured.

Verification
- squash equivalence per P4 step 7 in AISL.

## C3.3 Onboarding flows

Repository: community-base. Depends on: C3.1e, C3.2.

Read first
- `~/git/ai-shipping-labs/accounts/views/onboarding.py`, `onboarding_ai.py`, `questionnaires/onboarding.py`,
  `templates/accounts/onboarding*`, dashboard prompt banner in `templates/home.html`.

Steps
1. Models (`label = "cb_onboarding"`): `OnboardingFlow(slug, title, is_default, active)`,
   `OnboardingStep(flow, order, kind profile|questionnaire|ai_chat|plan|custom, config JSON,
   required)`, `FlowAssignment(flow, group FK to auth Group null, min_level int null, priority)`,
   `OnboardingProgress(user, flow, current_step, completed_at, data JSON)`.
2. Selector: `flow_for(user)`: highest-priority assignment whose group the user belongs to or
   whose `min_level` the access policy satisfies; else the default flow.
3. Steps: `profile` renders the `MemberProfile` form; `questionnaire` reuses the fill-in
   renderer with the persona self-identification from AISL; `ai_chat` the AI flow; `plan` calls
   hook `ONBOARDING_PLAN_STEP` (AISL wires sprint plans); `custom` renders a site template.
4. Views at `/onboarding/`: start, step, submit, resume; dashboard prompt partial; completion
   emits signal `onboarding_completed(user, flow)`.
5. Gate: `ONBOARDING_ELIGIBILITY` hook (AISL: paid members only; DTC: every verified member).
6. Studio: flows, steps, assignments, progress list; registered under `Onboarding`.
7. Tests: selector precedence, resume, each step kind with the memory backends.

Verification
- `testproject` with two flows and a group assignment: a user in the group gets the group flow;
  another gets the default.

## C3.4 Community (Slack)

Repository: community-base. Depends on: C3.1e. Playbook P4 for `community` (label kept).

Read first
- `~/git/ai-shipping-labs/community/` (Slack invite, identity import, staff notifications,
  Calendly, booked calls, audit log).

Steps
1. Lift; Calendly and booked calls behind `COMMUNITY_BASE["CALENDLY"]` (AISL true, DTC false).
2. `SlackAccessGrant` semantics from DTC spec 05: grant created on onboarding completion or on
   eligibility; reveal page at `/accounts/community/slack/` with no-store headers; invite email
   purpose `community_invite`.

Verification
- squash equivalence in AISL; `testproject` reveal page returns 403 for ineligible and 200 with
  `Cache-Control: no-store` for eligible.

## C3.5a Notifications

Repository: community-base. Depends on: C3.1e. Playbook P4 for `notifications` (label kept).

Read first
- `~/git/ai-shipping-labs/notifications/` (delivery sources, preferences, bell and JSON routes).

Steps
1. Lift the app. Replace imports of `content`, `events`, `plans` and `bookclub` with signals
   consumed through `register_notification_source`.
2. Keep the notification bell partial and JSON endpoint names. Public templates follow the
   package template contract.

Verification
- Package tests cover source registration, preferences, read state and recipient ownership.
- `testproject` bell shows an unread count after a registered source emits a notification.
- AISL squash equivalence remains C3.7 work.

## C3.5b Comments

Repository: community-base. Depends on: C3.1e. Playbook P4 for `comments` (label kept).

Read first
- `~/git/ai-shipping-labs/comments/` (generic targets, moderation, member and Studio routes).

Steps
1. Lift the app and replace site-domain imports with generic relations and registered target
   adapters.
2. Preserve public template blocks and URL names used by both sites.

Verification
- Package tests cover generic targets, ownership, moderation and target deletion.
- `testproject` can comment on a fixture target without importing a site app.
- AISL squash equivalence remains C3.7 work.

## C3.5c Voting

Repository: community-base. Depends on: C3.1e. Playbook P4 for `voting` (label kept).

Read first
- `~/git/ai-shipping-labs/voting/` (generic targets, vote transitions and JSON routes).

Steps
1. Lift the app and replace site-domain imports with generic relations and registered target
   adapters.
2. Preserve public template blocks and URL names used by both sites.

Verification
- Package tests cover generic targets, vote transitions, counts and recipient ownership.
- `testproject` can vote on a fixture target without importing a site app.
- AISL squash equivalence remains C3.7 work.

## C3.6 Identity and community capability checkpoint

Repository: community-base. Depends on: C3.1e, C3.2, C3.3, C3.4, C3.5a, C3.5b, C3.5c.

Goal: prove package-local identity and community behavior without tagging provisional kept-label
migrations.

Verification
- Fresh-database migrations and package tests pass with all identity/community apps installed.
- Behavior coverage matrices classify copied donor tests as moved, adapted or site-owned.

## C3.7 Identity donor compatibility checkpoint

Repository: community-base. Depends on: C3.6, A3.2, D3.1.

Goal: finalize provisional kept-label migrations against prepared donor schemas before release.

Steps
1. Record exact AISL and DTC donor commit SHAs, model state, migration names and test counts.
2. Finalize each kept-label squash and append genuinely new shared schema in later migrations.
3. Run donor equivalence, reversibility, synthetic PostgreSQL and development-copy rehearsals.

Done when
- [ ] every identity/community migration is adoption compatible and no longer provisional

## A3.1 Move tier and Stripe fields off the user model

Repository: AI-Shipping-Labs/website. Depends on: C5.2. Playbook P7, AISL part, step 1.

Steps
1. `payments.Membership(user OneToOne, tier FK, pending_tier FK, billing_period_end,
   stripe_customer_id, subscription_id)`; data migration copies from `User`; `Membership` gets
   a `for_user(user)` accessor that creates the free row lazily.
2. Rewrite readers: `grep -rn "\.tier\b\|stripe_customer_id\|subscription_id\|billing_period_end\|pending_tier" --include=*.py . | grep -v migrations | grep -v tests | wc -l`
   gives the list; one pull request per app. `TierAccessPolicy` reads through `Membership`.
3. Contract migration removing the five fields from `User`.

Verification
- After contraction: `grep -rn "user\.tier\b" --include=*.py . | grep -v migrations` -> nothing.
- `make test-affected` and `uv run python manage.py test payments accounts content events --parallel 4` -> pass.
- Development copy (P14): `Membership.objects.count()` equals `User.objects.count()`; sum of
  paid members by tier equals the pre-migration numbers recorded in the pull request.

## A3.2 Extension models for the remaining site-only user fields

Repository: AI-Shipping-Labs/website. Depends on: A3.1.

Steps
1. Any `User` field not in the C3.1 field table moves to `accounts_ext.MemberExtra` (create the
   app). Expected: none if the field table is complete; verify with a diff of
   `User._meta.get_fields()` against the table and list the result in the pull request.
2. `TierOverride`, `Token`, `MemberAPIKey` move to `payments` (override) and to `community_base.api`
   (keys, P6 data copy).

Verification
- `makemigrations --check` clean; `uv run python manage.py test accounts payments api member_api --parallel 4` -> pass.

## A3.3 Freeze weekend: adopt shared accounts, questionnaires, community, notifications, comments, voting

Repository: AI-Shipping-Labs/website. Depends on: C5.3, C3.7, A3.2. Freeze required: yes. Playbook P4 for each app, P13.

Steps
1. Delete local `accounts` (keep `accounts_ext` if created), `questionnaires`, `community`,
   `notifications`, `comments`, `voting`; install the package apps; pin `v0.6.0`.
2. Wire hooks: `ONBOARDING_ELIGIBILITY` (paid members), `ONBOARDING_PLAN_STEP` (sprint plans),
   `CALENDLY=True`, notification sources for plans, bookclub, workshops.
3. Rehearse with P14: `migrate --plan` shows only `0001_squashed` marker rows for the six labels
   and no schema operations.

Production checks
- login with email and password; login with Google; password reset email arrives (ses_local);
- onboarding start page for a paid member renders; notification bell count loads;
- Studio users list renders with tier pills.

Done when
- [ ] checks pasted in the issue, freeze removed, tagged `replaces` markers retained

## D3.1 Extension models and user model rename

Repository: DataTalksClub/website. Depends on: C5.2. Playbook P7, DTC part,
steps 1 to 3.

Steps
1. `courses.LearnerProfile` with the course-platform fields; `accounts_ext.IdentityState` with
   the identity reconciliation fields and the `AccountIdentityAlias`, `AccountIdentityQuarantine`,
   `AccountReconciliationRun`, `CmpLearnerImportProgress` models; data migrations; readers rewritten.
2. `RenameModel("CustomUser", "User")`, `AlterModelTable("accounts_user")`.
3. Field reconciliation to the C3.1 table (add missing AISL-origin fields with defaults).

Verification
- `uv run pytest -q` -> pass; development login works after deploy; counts equal (P14).

## D3.2 Freeze weekend: adopt shared accounts and onboarding

Repository: DataTalksClub/website. Depends on: C5.3, C3.7, D3.1. Freeze required: yes. Playbook P7 step 4, P13.

Steps
1. Delete local `accounts` app code except `accounts_ext`; install `community_base.accounts`,
   `questionnaires`, `onboarding`, `community`, `notifications`, `comments`; `migrate accounts 0001_squashed --fake`
   after deleting DTC's `accounts` rows from `django_migrations`.
2. Configure flows: default flow (profile, questionnaire "Welcome"); a `learners` group flow
   (profile, questionnaire "Course goals"). `ONBOARDING_ELIGIBILITY`: verified email.
3. Slack grant on onboarding completion; reveal page; the public `/slack` landing stays.
4. Enable comments on event and course pages, notifications for event and cohort changes.

Production checks (development environment, DTC is not at the apex yet)
- register, verify, complete the default flow, open `/accounts/community/slack/` -> 200 with the
  invite; a user in `learners` sees the second questionnaire.

Done when
- [ ] spec 01 "Member profile version 1" marked implemented by the package; spec 05 Slack section updated
