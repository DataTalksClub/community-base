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

Repository: AI-Shipping-Labs/website. Depends on: A3.3. Playbook P3. One pull request per row.

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

## C4.1 Lift events

Repository: community-base. Depends on: A4.1 merged, C3.6. Playbook P4 for `events` (label kept).

Read first
- `~/git/ai-shipping-labs/events/` after A4.1, `templates/events/`, `templates/studio/events/`,
  `templates/studio/event_series/`, `api/views/events.py`, `event_series.py`, `hosts.py`,
  `event_guest_invitations.py`, `specs/07-events.md`.

Steps
1. Lift models, services, tasks (as job handlers), views, Studio views, API endpoints, ICS, Zoom.
2. Add shared fields DTC needs in a second migration appended after the squash:
   `Event.public_id` (nullable, unique) with an allocation sequence, and `EventAlias(event,
   source_path unique, kind, reason)`. Public URL pattern becomes configurable:
   `COMMUNITY_BASE["EVENT_URL_STYLE"]` in `slug` (AISL: `/events/<id>/<slug>`) or `public_id`
   (DTC: `/events/<public_id>/<slug>`).
3. Hosts: `Host.kind` and `external_ref`; hook `HOST_PROFILE_RESOLVER(host) -> url | None` (DTC
   links to `/people/<short>.html`).
4. Registration: keep AISL's authenticated registration and anonymous email signup on free
   sessions; the anonymous path uses `community_base.mail.send` for verification and the DTC spec
   05 lifecycle (`pending_verification`, `confirmed`, `cancelled`, `expired`, `attended`,
   `no_show`) and constraints. Series registration semantics unchanged.
5. Public templates rewritten to the template contract; Studio templates extend the shell.
6. Tests moved from AISL `events/tests/` (25k lines) minus the ones the issue lists as AISL-only.

Verification
- squash equivalence per P4 step 7 in AISL; `make test tests/events` -> pass.
- `testproject`: create a series with weekly cadence, register a user for the series, add an
  occurrence -> the user is registered for it; unregister one occurrence -> opt-out row exists.

## C4.2 Release 0.5.0

Playbook P15.

## A4.2 Freeze weekend: adopt shared events

Repository: AI-Shipping-Labs/website. Depends on: C4.2. Playbook P4 steps 9 and 10, P13.

Production checks
- events list and detail render; a registered member sees the join link within the window;
- Studio: create an event with Zoom -> meeting created; series page renders;
- reminder schedule fires in the next window and `EmailDelivery` rows appear for it.

## D4.1 Database-authored events in DTC

Repository: DataTalksClub/website. Depends on: C4.2. Playbook P5 for `events`.

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

Repository: DataTalksClub/website. Depends on: D4.1. Playbook P13 on the development environment
(and production if DTC is live by then).

Checks
- `/events` list and one detail by `public_id` render; an alias path redirects one hop;
- anonymous registration on a free event -> verification email delivered through Relay ->
  confirm link -> `confirmed`.

Done when
- [ ] spec 05 "Accountless event registration" marked implemented by the package; events removed
  from `_docs/specs/03-github-content-and-people.md` data ownership list
