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

## Addendum: the corpus binding is half repaired, and the other half is not corpus binding

Branch `fix/playwright-corpus-binding`, nine commits on top of `ci-repair-20260917`, not merged.
Per-module sweep, run identically at the base and at the head:

| | failures | errors |
|---|---|---|
| base | 79 | 7 |
| head | 42 | 2 |

Cleared 37 failures and 5 errors, of which 36 and 4 are attributable to the commits; one of each was
a flake that passed at head unchanged.

### A measurement finding that outranks the count

The first full-suite run was invalidated and the reason generalises. Under load average 29 on 12
cores, `test_reflow_zoom_spacing_reduced_motion_and_forced_colors` hung, the browser died, and every
one of the roughly 330 tests after it reported an error: 273 apparent failures from one hang.

A single full-suite Playwright run is not a trustworthy measurement on a contended machine. The
replacement was one pytest process per module with the same markers the CI target uses. Anyone
reading a browser-suite number from this box should ask how it was produced before believing it.

### Roughly half of what remains is not corpus binding

This is the part worth acting on. The following are browser tests that never followed a deliberate
product change, so each is an acceptance question rather than a test defect:

- homepage climb copy rewritten on 2026-09-10, with the browser pin never following. The Django
  test pins the new copy, so the browser pin is simply stale.
- FAQ dropped from the default primary navigation.
- every extensionless and trailing-slash detail alias retired on 2026-09-16, where the owner ruled
  the URL break acceptable, and this module still expects a 301.
- the article reading measure widened to 896px on owner feedback, against a test pinning 480 to 640.

They are cheap individually and should be batched into one issue that puts the product decisions in
front of the owner, rather than absorbed silently by whoever is next in the file. Absorbing them is
how a suite becomes green and meaningless, which is the failure this whole diagnosis started from.

### Three findings that are not test defects at all

- `test_accessibility` has three genuine axe `target-size` violations on the courses hub, on
  `a[href$="de-zoomcamp"]` and two catalogue-card title links. A real accessibility defect.
- `test_issue_237_qna_review` sees `JobIntent.objects.count()` of 3 where 0 is expected: a jobs or
  email side effect, not a corpus question.
- `test_podcast_episode_graph` fails because the synthetic graph has 78 nodes and 9 links, all
  wiki to wiki, so no episode has a single graph link and every episode page renders the empty
  state. Making those pass means designing synthetic episode-graph data, which has knock-on effects
  on the wiki graph page and the homepage explorer. That is a fixture design decision and was left
  alone rather than invented.

### The shapes that recur, for whoever continues

- a name that was one string in the real corpus and is two in the synthetic one, which bit three
  separate modules.
- the newest or first record silently assumed to carry a video, a transcript, show notes or three
  platform links.
- arithmetic of the old corpus written as a literal: 24 seasons, 23 graph connections, 51 event
  rows.

Deriving the value from the record is the fix in every case. A scan for path literals is not
enough: two modules were found only by reading failures, because their bindings were an event title
and an implicit assumption about the newest episode.
