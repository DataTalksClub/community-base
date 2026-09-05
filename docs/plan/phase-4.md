# Phase 4: events

Goal: one events app with series, registration, series registration, reminders, feedback, ICS,
Zoom and banners on both sites. Events are authored in Studio and stored in the database on both
sites (decision D7). DTC keeps its numeric public ids, aliases, Q&A sessions and historical
registration aggregates as extensions.

Freeze: AISL one weekend (A4.2), DTC one weekend (D4.2).

Exit criteria:

- `ls ~/git/ai-shipping-labs/events ~/git/dtc-website/events` -> both missing.
- DTC: every event URL in `_docs/compatibility/` still resolves (existing compatibility test).
- AISL: series registration, reminders and Zoom creation work in production (checks in A4.2).

## A4.1 Cut the seams in AISL events

Repository: AI-Shipping-Labs/website. Depends on: C5.2, A3.2. Playbook P3. One pull request per row.

| Import in `events` | Replacement |
|---|---|
| `content.models.Workshop` (writeup hand-off, recording page links) | hook `EVENT_WRITEUP_RESOLVER(event) -> {"url", "title"} | None`; template block `event_writeup` with default empty; AISL implements in `content/hooks.py` |
| `content.models.Instructor` (`EventInstructor`) | shared `events.Host` gains `kind` (host, instructor, speaker) and `external_ref`; AISL `Instructor` rows become `Host(kind=instructor)` with a data migration; `WorkshopInstructor` stays in `content` referencing `Host` |
| `payments` tier checks | `community_base.kernel.access.can_access(user, event)` |
| `plans`, `bookclub`, `analytics` | signals `event_registered`, `event_unregistered`, `event_published`, `event_cancelled`, `event_rescheduled`; consumers move into those apps |
| `community` Slack announcements | already package; import path change only |
| `email_app` | already `community_base.mail.send` after A1.2; confirm none remain |
| `integrations` Zoom, banner generator, calendar invite, observability | Zoom client and ICS builder move into the package with the app (`community_base/events/integrations/`); banner generator stays in AISL behind hook `EVENT_BANNER_GENERATOR` |
| `studio` helpers | already package after A2.1 |

Verification per pull request: playbook P3 step 4. Final: `grep -rn "^from \(content\|payments\|plans\|bookclub\|analytics\|integrations\)" events/ --include=*.py | grep -v tests` -> nothing.

## C4.1a Events models and domain services

Repository: community-base. Depends on: C3.6. Playbook P4 for `events` (label kept).

Read first
- `~/git/ai-shipping-labs/events/models/`, `events/services/` and `specs/07-events.md`.
- DTC `_docs/specs/05-events-registration-email.md` event fields and `_docs/compatibility/` URL
  identity requirements.

Steps
1. Record the donor commit, model and test baseline. Build the target `Event`, `EventSeries`,
   `Host`, host-assignment and alias models with a provisional kept-label migration.
2. Add `Event.public_id` with concurrency-safe allocation and `EventAlias(event, source_path,
   kind, reason)` for DTC compatibility.
3. Add `Host.kind`, `Host.external_ref` and `HOST_PROFILE_RESOLVER(host) -> url | None`.
4. Lift framework-independent event, series and host domain services. Replace tier checks with
   `community_base.kernel.access.can_access` and cross-domain writes with events.

Verification
- Package tests cover event status, public identity, alias uniqueness, series cadence, host roles,
  access and domain transitions without importing a site app.
- Fresh migrations, reversal, drift and boundary checks pass. Donor equivalence remains C4.3.

## C4.1b Registration, reminders and feedback

Repository: community-base. Depends on: C4.1a.

Read first
- `~/git/ai-shipping-labs/events/` registration, series registration, reminder and feedback
  services and tests.
- DTC `_docs/specs/05-events-registration-email.md` registration lifecycle.

Steps
1. Lift authenticated registration and series-registration behavior, including future-occurrence
   enrollment and per-occurrence opt-outs.
2. Add anonymous email signup for free events through the lifecycle `pending_verification`,
   `confirmed`, `cancelled`, `expired`, `attended`, `no_show` and send verification through
   `community_base.mail.send`.
3. Lift reminder and feedback state as domain services with durable job inputs and explicit
   recipient ownership.
4. Emit `event_registered`, `event_unregistered`, `event_published`, `event_cancelled` and
   `event_rescheduled` after successful transactions.

Verification
- `testproject`: register for a series, add an occurrence and observe the inherited registration;
  unregister one occurrence and observe its opt-out row.
- Tests cover anonymous verification, idempotency, lifecycle constraints, reminder selection,
  feedback ownership and cross-domain events.

## C4.1c Event integrations and job handlers

Repository: community-base. Depends on: C4.1b.

Read first
- `~/git/ai-shipping-labs/events/` ICS, Zoom, reminder, recording and task code.
- Package jobs, mail and configuration integration contracts.

Steps
1. Lift the ICS builder and Zoom client behind package configuration with bounded HTTP behavior,
   stable request/response objects and no provider secrets in logs.
2. Add `EVENT_BANNER_GENERATOR`, `EVENT_WRITEUP_RESOLVER` and recording hooks. Keep the banner
   implementation site-owned.
3. Register reminder, registration-verification and integration jobs with opaque scalar inputs,
   idempotency and retry-safe state transitions.
4. Add synthetic adapters for success, provider failure, timeout and disabled configurations.

Verification
- Package tests cover ICS output, Zoom boundaries, hooks, handler registration, idempotency,
  retries and redacted failures without network or credentials.
- Installed-wheel checks find handlers, templates and optional integration modules.

## C4.1d Event pages, Studio and APIs

Repository: community-base. Depends on: C4.1c.

Read first
- `~/git/ai-shipping-labs/templates/events/`, `templates/studio/events/`,
  `templates/studio/event_series/`, `api/views/events.py`, `event_series.py`, `hosts.py` and
  `event_guest_invitations.py`.

Steps
1. Lift public list, detail, registration, verification and feedback routes. Support
   `COMMUNITY_BASE["EVENT_URL_STYLE"]` values `slug` and `public_id`.
2. Rewrite public templates to the package contract and Studio templates to extend the shared
   shell. Preserve stable URL names and documented override paths.
3. Lift Studio event, series, host, registration and guest-invitation operations with audit hooks.
4. Lift session-authenticated APIs, enforce recipient and staff ownership and publish OpenAPI.
5. Complete the AISL event-test behavior matrix. Keep exact copied-test and migration-equivalence
   claims for C4.3 after A4.1.

Verification
- Both URL styles, aliases, public templates, Studio routes and APIs pass package tests.
- Full package, boundary, fresh-migration and installed-wheel checks pass.

## C4.2 Events capability checkpoint

Repository: community-base. Depends on: C4.1d.

Goal: prove package-local events behavior without tagging the provisional kept-label migration.

Verification
- Fresh-database migrations and package events tests pass.
- Both URL styles, registration lifecycles and synthetic integration adapters pass.

## C4.3 Events donor compatibility checkpoint

Repository: community-base. Depends on: C4.2, A4.1.

Goal: finalize the provisional events squash against the prepared AISL donor state.

Steps
1. Record the exact donor commit SHA, model state, migration names and test count.
2. Finalize the squash, leaving new shared schema in appended migrations.
3. Run equivalence, reversibility, synthetic PostgreSQL and development-copy rehearsals.

Done when
- [ ] the events migrations are adoption compatible and no longer provisional

## A4.2 Freeze weekend: adopt shared events

Repository: AI-Shipping-Labs/website. Depends on: C5.3, C4.3, A4.1. Freeze required: yes. Playbook P4 steps 9 and 10, P13.

Production checks
- events list and detail render; a registered member sees the join link within the window;
- Studio: create an event with Zoom -> meeting created; series page renders;
- reminder schedule fires in the next window and `EmailDelivery` rows appear for it.

## D4.1 Database-authored events in DTC

Repository: DataTalksClub/website. Depends on: C5.3. Playbook P5 for `events`.

Read first
- `events/models.py`, `events/identity.py`, `events/importers.py`, `events/qna/`,
  `events/services.py`, `_docs/specs/05-events-registration-email.md` "Event model",
  `_docs/architecture/event-qna-integration.md`, `_docs/compatibility/`.

Steps
1. Export current events, aliases, Q&A sessions and historical aggregates (P5 step 1).
2. Create `event_qna` app: models from `events/qna/` with `session.event` as a `OneToOneField`
   to `events.Event` (integer pk now); views and Studio pages unchanged otherwise.
   `historical_registrations` app for the aggregate models keyed by `event_id`.
3. Remove the `events` parser from the content sync; remove `events/` app; install
   `community_base.events` with `EVENT_URL_STYLE="public_id"`; rebuild tables (P5 steps 2 to 4).
4. Import command: old `Event` rows -> shared `Event` with `public_id` preserved, `slug`
   preserved, speakers -> `Host(kind=speaker, external_ref=<people short>)`, lifecycle mapped to
   `status`; `EventAlias` rows preserved; Q&A sessions and aggregates re-linked by `public_id`.
5. Studio: DTC event pages come from the package; Q&A and historical totals register under the
   `Events` section.
6. Public detail keeps speaker links through `HOST_PROFILE_RESOLVER`; description bridge from
   `_docs/event-description-bridge.md` becomes the description field content.

Verification
- Row counts before and after import equal for events, aliases, Q&A sessions, aggregates.
- `uv run pytest events event_qna historical_registrations -q` -> pass; compatibility route
  test passes; Playwright core events tests pass.

## D4.2 Freeze weekend: DTC events cutover

Repository: DataTalksClub/website. Depends on: D4.1. Freeze required: yes. Playbook P13 on the development environment
(and production if DTC is live by then).

Checks
- `/events` list and one detail by `public_id` render; an alias path redirects one hop;
- anonymous registration on a free event -> verification email delivered through Relay ->
  confirm link -> `confirmed`.

Done when
- [ ] spec 05 "Accountless event registration" marked implemented by the package; events removed
  from `_docs/specs/03-github-content-and-people.md` data ownership list
