# DTC main CI: diagnosis, and a gate that stopped observing

Date: 2026-09-17. Produced while repairing `DataTalksClub/website` main, whose redness blocks the
development deploys that D0.1c and D1.2ca wait on. Branch `ci-repair-20260917`, 18 commits, not
merged.

## The finding that matters most

The last main run recorded as green, 34733441117 on 2026-09-13, ran its playwright job in reused
mode and executed no tests at all: 255 log lines, no pytest output. The browser suite has been
accumulating breakage for months while the gate reported success.

Local ground truth on that suite is 97 distinct failing tests at the branch start, 84 at its head.
None of it is new. This is not a regression to repair inside one issue; it is a programme, and it
needs its own issue rather than being carried by whatever change happens to notice it.

The generalisable lesson is the one worth keeping: a reuse mechanism that can report success
without executing anything is worse than no gate, because it converts silence into evidence. Any
other gate in these four repositories with a reuse or skip path deserves the same look.

## What was wrong, by job

### quality, red on current main and not visible in the earlier survey

The survey read run 35165307928, which predates three merges. `quality` fails on current main, and
its failure cancels the whole run, so it was the first real blocker rather than a later one.

Three `tests_ci` failures came from the app-extraction wave: `event_qna/`,
`event_registrants/` and `historical_registrations/` were carved out of `events/` on 2026-09-16
with no `ci/ownership.json` entry, and `events/queries.py` had begun reading
`content.models.EventSource`, escaping the `content` closure. One
`database-portability-check` failure came from `rebuild_events_tables.py` using
`connection.vendor` for a Postgres-only `DROP TABLE ... CASCADE`, now recorded in that checker's
own reviewed-exception mechanism with its reason.

Verified green after the fix: the full quality contract exits 0 with all nine targets passing and
`test-ci` at 671 passed.

### django, root-caused and green

The named symptom was a migration serialising its validator as
`courses.models.cohort.validate_course_progression`, so every replay imported the live cohort
module. Moved to the app's existing stable-validator module; the contract test was not touched.

CI never got past that, because the job stops on first failure. Behind it were 11 failures and 30
errors across nine unrelated regressions, the largest being 29 `review_import` errors from three
course-family columns landing NOT NULL without the seeder following.

Verified after the fix: `Ran 4379 tests ... OK (skipped=11, expected failures=1)`.

### playwright, still red, three causes

Real-corpus binding is the largest cluster: the browser database moved to a synthetic catalogue on
2026-09-12 and about seven modules still assert retired identifiers. Then browser helpers passing
identity UUIDs where the package model has a `BigAutoField`, the same bug class fixed twice before.
Then a harness pinned to the real corpus, now fixed in two places.

## Four things this leaves, none of them fixed here

1. The browser suite is still bound to the retired reviewed corpus. Blocks the playwright job.
   Four fixes already on the branch show the pattern is mechanical, roughly one module at a time.
2. A new top-level app must land with its `ci/ownership.json` entry. The quality break is fixed,
   but the process gap that allowed it is not.
3. `studio/urls.py` declares `events/<int:event_id>/registration-total/` while the view annotates
   `event_id: uuid.UUID`, and the sibling identity routes were restored to `<uuid:>`. This looks
   like an incomplete revert. It is a staff-routing product call, so it was left alone; it is the
   only thing keeping two of the four historical-registration-total cases red.
4. `test_project_gallery`, ten tests, expects an "Explore courses" link in an empty state the
   unified gallery template does not render. A product acceptance question, not a test bug.
