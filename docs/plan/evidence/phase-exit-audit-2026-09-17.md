# Phase exit audit, 2026-09-17

Read-only audit of every phase's exit criteria (`docs/plan/phase-0.md` to `phase-7.md`), the
phase status table in `docs/plan/README.md`, the `C7.1` umbrella, the dependency graph, and the
STATUS.md Link notes named as possibly stale. No code changed in any repository. Method: the
literal commands each exit criterion names, run against `../ai-shipping-labs`, `../dtc-website`
and this package's `main` (checked out in this worktree); `gh issue`/`gh run` reads against the
four GitHub repositories for Link-note verification; `scripts/plan.py check` and a short Python
script reusing its loaders for the semantic checks the script does not run itself.

Definition of done for a phase, `docs/04-quality-gates.md` section 6: every issue in the phase is
merged and deployed to each affected site's development environment, the phase's exit criteria
are verified with the listed commands, and the README status table is updated in the same pull
request that closes the last issue. Applied conservatively below: a criterion counts as met only
when the listed command was run and returned the stated result, not when the issues that would
produce it read `done`.

## Part 1: phase exit criteria

### Phase 0: package repository, kernel, config, API layer

| Criterion | Verdict | Evidence |
|---|---|---|
| `uv add community-base@v0.1.0` installs and imports in an empty project | met | ran it in a scratch `uv init` project: `community-base==0.1.0` resolved from the `v0.1.0` tag and `import community_base` printed `OK` |
| Neither site has surviving `integrations.config` / `core.operational_settings` / `core.site_settings` reads outside the named shims | not met | AISL: `grep -rn "integrations.config" --include=*.py . | grep -v tests | grep -v migrations` still returns roughly 150 call sites across `community/`, `events/`, `payments/`, `studio/`, `email_app/` and more, because `A0.2` step 6 (delete the shim, rewrite every import) has not run; DTC: the same grep still hits `core/operational_settings_service.py`, `core/site_settings.py`, `management_registry.py`, `studio/views.py`, because `D0.1c`/`D0.1d` have not shipped |
| `GET /api/v1/settings` returns the same JSON shape on both sites' development environments | unverifiable from here | needs a live request against each site's deployed development environment; no such environment is reachable from this worktree |

Blocking issue for the second criterion: `A0.2` (in-progress; STATUS row: closed 2026-09-12 with
dev deploy green, but "canonical final check unmet", and step 6 of the issue text, the shim
deletion, is explicitly a later pull request) on the AISL side, and `D0.1` (todo; blocked
transitively through `D0.1c`, blocked, and `D0.1d`, todo) on the DTC side.

Verdict: not closeable. README says "in progress", which matches.

### Phase 1: jobs and mail through Relay

| Criterion | Verdict | Evidence |
|---|---|---|
| No `qcluster` in DTC task definitions | met | `grep -n qcluster deploy/task_definitions.py` in `dtc-website` prints nothing |
| DTC has no Datamailer code outside migrations | not met | `grep -rln datamailer --include=*.py . | grep -v migrations` in `dtc-website` returns well over 100 files, concentrated in `course_management/datamailer/`, `courses/`, `studio_courses/`, `data/`; this is not a residue, it is the code the transitional Datamailer backend still runs on |
| Relay status contract for the DTC tenant green for seven consecutive days | unverifiable from here | needs Relay's monitoring/status-contract dashboard, not reachable from this worktree |
| AISL `INSTALLED_APPS` carries `community_base.jobs`/`community_base.mail`, and no live `EmailService()` call sites outside tests | partially met | `INSTALLED_APPS` carries both apps (`website/settings.py:187-188`); but `grep -rn "EmailService()" --include=*.py . | grep -v tests` still returns four sites (`accounts/services/privacy_workflow.py`, `email_app/tasks/send_campaign.py`, `studio/views/campaigns.py` twice). These four are not unnoticed leftovers: AISL issue 1629 (closed 2026-09-16) records them as accepted, documented exemptions — the campaign family until `A6.3`, `privacy_workflow.py` until the package grows a redacted-recipient send seam — but the exit criterion's literal grep still fails and the phase file's criterion text was never amended to carry the exemption. This is a plan-text gap worth a separate small fix (docs/PROCESS.md 6, "the plan step is wrong"), not something this audit corrects |

Blocking issue: `D1.2cb` (retire `email_app`/`data` app, todo) and `D1.3` (freeze weekend, todo)
for the Datamailer criterion; no single package issue closes the Relay-status criterion, it is a
time-based external gate under `D13`.

Verdict: not closeable. README says "in progress", which matches.

### Phase 2: Studio shell, users management, content sync engine

| Criterion | Verdict | Evidence |
|---|---|---|
| Neither site has `templates/studio/base.html` | not met | both `ai-shipping-labs/templates/studio/base.html` and `dtc-website/templates/studio/base.html` exist |
| `manage.py studio_routes --check` passes on both sites | not met | AISL: `uv run python manage.py studio_routes --check` reports 333 route-partition errors and exits non-zero; DTC: the command does not exist yet (`Unknown command: 'studio_routes'`) because `community_base.studio` is not in DTC's `INSTALLED_APPS` (`website/settings/base.py` lists `community_base.events`, `.curriculum`, `.coursework`, `.jobs`, `.mail`, `.kernel`, `.config`, `.api`, `.content_sync`, but not `.studio`) |
| Both sites sync content through `community_base.content_sync`; AISL's `integrations/services/github_sync/` and DTC's `content_sync/` are gone | not met | both directories still exist and are non-trivial (AISL: `dispatchers/`; DTC: `course_repository*.py`, `dtc_content`, `legacy_main`, `snapshot.py`, `webhook_delivery.py`, `models.py`) |

Blocking issues: `A2.1` (blocked on `C7.13`, still todo) and `D2.1` (in-progress) for the base
template removal; `C7.13` itself for the route-partition check on AISL, and `D2.1` for DTC even
having the command; `A2.3` (in-progress) and `D2.2c` (in-progress) for the sync directory
removals.

Verdict: not closeable. README says "in progress", which matches.

### Phase 3: accounts and auth, onboarding, community, notifications, comments, voting

| Criterion | Verdict | Evidence |
|---|---|---|
| Both sites: `get_user_model().__module__` is `community_base.accounts.models` | not met | AISL prints `accounts.models.user`; DTC prints `accounts.models` — neither site has cut over yet (`A3.3` and `D3.2`, the freeze weekends, both `todo`; `D3.1e`, the `CustomUser` rename, is `in-progress`, unmerged) |
| AISL: `accounts/` holds only `accounts_ext`/`payments` remnants; `questionnaires/`, `community/`, `notifications/`, `comments/`, `voting/` do not exist | not met | all five directories still exist in `ai-shipping-labs`, and `accounts/` still carries `adapters.py`, `auth.py`, `gating.py`, `session_backend.py`, `signals.py`, full `models/`, `views/`, `services/` |
| DTC: registration, verification, onboarding and Slack access page work end to end | unverifiable from here | needs a running DTC development server and a manual or Playwright walk-through; out of scope for this audit's narrow-test-run instruction |

Blocking issue: `A3.3` (freeze weekend, todo; depends on `C5.3`, `C3.7`, `A3.2`, all not done)
and `D3.2` (freeze weekend, todo; depends on `C5.3`, `C3.7`, `D3.1e`, none done).

Verdict: not closeable. README says "in progress", which matches.

### Phase 4: events

| Criterion | Verdict | Evidence |
|---|---|---|
| `events/` is gone from both sites | not met | `ls ai-shipping-labs/events dtc-website/events` both resolve; neither directory is gone |
| DTC: every event URL in `_docs/compatibility/` still resolves | not run | would require running DTC's compatibility test suite; excluded by the instruction to keep test runs narrow and not run a site's full Django suite |
| AISL: series registration, reminders and Zoom creation work in production | unverifiable from here | production-only check, no access from this worktree |

Blocking issue: `A4.1` (cut the seams, todo) and `D4.1` (database-authored events, todo); both
feed `A4.2`/`D4.2`, the freeze weekends, also todo.

Verdict: not closeable. README says "in progress", which matches.

### Phase 5: curriculum and coursework

| Criterion | Verdict | Evidence |
|---|---|---|
| Neither site defines `Course`, `Module` or `Unit` | not met | `grep -rn "^class \(Course\|Module\|Unit\)("` finds `content/models/course.py` in AISL (`Course`, `Module`, `Unit`) and `courses/models/cohort.py` + `curriculum.py` in DTC (`Course`, `Module`, `Unit`) |
| AISL course pages, progress, drip, tier gating and purchase access work in production | unverifiable from here | production-only check |
| DTC cohorts with homework, projects, leaderboards and certificates work in development with imported data | not run | would need a full DTC development rehearsal against imported data; excluded by the narrow-test-run instruction and not yet possible: `D5.1` (map DTC data to the shared apps) is still todo |

Blocking issue: `A5.1`/`A5.2` and `D5.1`/`D5.2`, all todo, all waiting on `C5.3` (package release
0.6.0, todo; itself waiting on `C5.1g`, in-progress, and `C3.7`/`C4.3`, both todo checkpoints).

Verdict: not closeable. README says "in progress", which matches.

### Phase 6: AISL cutover to Relay

| Criterion | Verdict | Evidence |
|---|---|---|
| AISL has no `sesv2`/`django_q` code outside migrations | not met | `grep -rn "sesv2\|django_q" --include=*.py . | grep -v migrations` returns 300 hits; this is expected under `D13`, AISL is deliberately still on these backends |
| `email_app` directory and its tables gone | not met | `ai-shipping-labs/email_app/` exists in full |
| Package ships no `ses_local`/`django_q` backend | not met | `community_base/mail/backends/ses_local.py` and `community_base/jobs/backends/django_q.py` both exist on `main` |

Blocking issue: `C6.1` (remove transitional backends, todo; depends on `A6.4`) and the whole
`A6.1`-`A6.4` chain (all todo except `A6.2`, done), themselves gated on the `D13` four-clean-week
proof, which has not started (`R6.1` todo).

Verdict: not closeable. README says "in progress", which matches.

### Phase 7: site convergence

| Criterion | Verdict | Evidence |
|---|---|---|
| Both sites serve wiki and docs from the same package app, site-owned parsers and templates | partially met | AISL: met, `A7.1` done, STATUS confirms wiki/docs pages 200 on dev and in the sitemap; DTC: not met, `D7.1` is in-progress and explicitly cannot merge yet — its own STATUS note says the docs reader breaks against the last tagged release (`v0.4.7`) with `TypeError: upsert_page() got an unexpected keyword argument 'body_html'`, which needs a release containing `C7.4`. Confirmed independently: `git merge-base --is-ancestor` shows the `C7.4` merge commit (`c2796cb`) is not an ancestor of `v0.4.7`, and `git log v0.4.7..main` lists `C7.4` through `C7.7` and more as un-released commits |
| Candidate table in `C7.1` has no `undecided` row | met | all 16 rows in the table read `accepted`, `site-owned` or `deferred`; none read `undecided` (see Part 3) |
| No shared app carries a legacy path/alias/redirect model | met | `grep -rn EventAlias --include=*.py community_base/` (excluding tests and migrations) returns nothing; `C4.1e` is done |
| One content format, enforced by `check_content`, read by one toolkit; `parsers_aisl.py`/`parsers_dtc.py` gone | not met | `community_base/curriculum/parsers_aisl.py` and `parsers_dtc.py` both still exist on `main`; no `check_content` management command exists on `main` (it exists only on the unmerged `C7.7` work) |
| Every content repository of both sites syncs from its default branch with zero errors | not run | would require running a live sync against sixteen external content repositories; out of scope for this audit |

Blocking issues: `D7.1` waiting on a package release that includes `C7.4` (already merged to
`main`, not yet tagged); the content-format criterion waiting on `C7.7`, `C7.8`, `C7.9a`, `C7.9b`,
`C7.9c`, `C7.10` (all todo, see Part 3 for the exact chain).

Verdict: not closeable. README says "not started", which does not match: `C7.2` through `C7.6`,
`C4.1e` and `A7.1` are done, and `C7.1`/`D7.1` are open with real work behind them. Corrected
below.

## Part 2: the phase table in README.md

Phase 7's row read "not started". That does not match `docs/plan/STATUS.md`: seven phase-7
issues are done (`C7.2`, `C7.3`, `C7.4`, `C7.5`, `C7.6`, `C4.1e`, `A7.1`), `C7.1` and `D7.1` are
open, and none of the fifteen remaining issues are blocked from starting for lack of prior work.
Corrected to "in progress" in this pull request.

Every other row already read "in progress" and no phase meets `docs/04-quality-gates.md` section
6 (every issue merged and deployed, exit criteria verified, table updated same pull request), so
no phase is corrected to "done". None of the seven phases is closeable today.

## Part 3: C7.1, the site convergence umbrella

Done when, from `phase-7.md`: no row in state `undecided`; every `accepted` row names at least
one issue that is `done`.

Full candidate table read from `phase-7.md`, cross-checked against `docs/plan/STATUS.md`:

| Row | State | Named issues | At least one done? |
|---|---|---|---|
| Wiki | accepted, D16 | C7.2, A7.1, D7.1 | yes (C7.2, A7.1) |
| Docs section | accepted, D16 | C7.2, A7.1, D7.1 | yes (C7.2, A7.1) |
| Event aliases and legacy paths | accepted, D17 | C4.1e | yes |
| Calendly Studio surfaces | accepted | C7.3 | yes |
| Public design systems | site-owned, D18 | none | n/a |
| Capability declaration for Studio and admin API | deferred, D22 | none | n/a |
| Optimistic concurrency and append-only model bases | accepted, D19 | C7.5 | yes |
| Custom session model | accepted, D20 | C7.6 | yes |
| Article storage shape | site-owned, D21 | none | n/a |
| Content format and importer | accepted, D23 | C7.7 to C7.12 | no, all six todo |
| Markdown dialect and sanitiser | accepted, D23 | C7.8 | no, todo |
| Course parser | accepted, D23 | C7.10 | no, todo |
| Parsers for the wiki, docs and person kinds | accepted, D24 | C7.9c | no, todo |
| Course entitlement keys | site-owned, D29 | none | n/a |
| Podcast, FAQ, people, sponsors, event Q and A | site-owned | none | n/a |
| Payments, sprint plans, CRM, book club, analytics, triggers | site-owned | none | n/a |

No row is `undecided`; the first condition is met. Four `accepted` rows fail the second
condition: Content format and importer, Markdown dialect and sanitiser, Course parser, and
Parsers for the wiki, docs and person kinds. All four were accepted today under D23 and D24, and
every issue named by any of them is still `todo`.

C7.1 cannot close today.

What it is waiting on, read from the dependency chain in `phase-7.md` and `STATUS.md`:
`C7.7` (content format specification, no dependency, can start now) then `C7.9a` (depends on
`C7.7`) then `C7.8` (depends on `C7.7`, `C7.4` already done) then `C7.9b` (depends on `C7.9a`,
`C7.8`) then, in parallel, `C7.9c` (depends on `C7.9b`, `C7.4`) and `C7.10` (depends on `C7.9b`).
Completing `C7.7` alone would satisfy the "Content format and importer" row (it names the whole
`C7.7`-`C7.12` range), but the other three rows each name one specific issue and need that exact
issue done: `C7.8` for the markdown-dialect row, `C7.10` for the course-parser row, `C7.9c` for
the wiki/docs/person-parser row. `C7.11` and `C7.12` are not required by any row's name and do not
block C7.1's own closure, though they are needed for the phase's own exit criteria (Part 1).

## Part 4: dependency graph cross-check

`scripts/plan.py check` output: `OK: 136 issues, STATUS.md consistent`. It checks duplicate ids,
issues missing a STATUS row, STATUS rows without an issue, unknown status values, dependency ids
that do not exist anywhere in the phase files, dependency cycles, and drift between the generated
columns (Issue/Repository/Title/Depends on/Freeze) and the phase files. All clean; no dangling
dependency ids, no cycles.

That check does not look at whether a `done` issue's own dependencies are also `done`, and it
does not read the free-text `Link` column at all, so it cannot notice a `blocked` row whose
named blocker has since closed. Hand-checked both, reusing `plan.py`'s own loaders:

Done issue with a not-done dependency: `D2.2b` (done) depends on `D2.2a` (in-progress). Read
both STATUS notes: `D2.2a`'s says "engineering, independent tester PASS and PM acceptance
recorded on the issue; merged to website main ...; dev deploy pending the website#345 /
aws-infra#56 blockers"; `D2.2b`'s says "closed 2026-09-15 with PM acceptance; merged ...; dev
deploy waiting on a green main CI run — the red quality job is a pre-existing lint regression,
website#405". Both are in the same state (code merged and accepted, development deploy still not
green), yet one reads `done` and the other reads `in-progress`, and the `done` one depends on the
`in-progress` one. `docs/PROCESS.md` step 5 ("Close") requires a green development deploy before
a site issue's row goes to `done`; by that rule `D2.2b` looks like it was closed early, or
`D2.2a` was left open too conservatively. Either way, the pair is inconsistent and worth the
owner's attention; this audit does not edit STATUS.md.

Blocked row whose named blocker has since closed: `A2.1` is blocked citing `C7.13` and `C7.14`.
`C7.14` is done (`STATUS.md` phase 7 row, merged, "Collapse with per-viewer persistence..."). Only
`C7.13` (still todo) is a live blocker; the `C7.14` half of the note is stale. `A2.1`'s own status
value (`blocked`) is still correct, only the free-text reason is half out of date.

Possible improvements to `scripts/plan.py`, reported rather than made: (1) a check that every
`done` issue's structured dependencies are also `done` or `skipped`; (2) a check that scans the
`Link` column for `[CADR]\d+\.\d+[a-z]*` issue-id mentions in a `blocked` row and flags any whose
current STATUS is `done`, since that free text is exactly what stops being true without anyone
touching the row.

No dependency names an id that does not exist (script-verified), and no cycle exists
(script-verified).

## Part 5: stale Link notes

Checked the two rows the request named, plus what turned up while checking others, using
`gh issue view` / `gh run list` against the live repositories (read-only, no `gh` write calls).

`D0.1c` and `D1.2ca` (both blocked, citing `website#345` red on django/migrations/quality/
playwright, and `aws-infra#56` blocking future applies only): checked live. `aws-infra#49` is
closed (confirms the "effective since 2026-09-13" clause). `aws-infra#56` is still open. The
2026-09-17 scheduled full-regression run on `dtc-website` main (`gh run list`, run `35227624779`,
today) failed with exactly the same four jobs the note names: quality, migrations, django,
playwright. Both notes are current, not stale, as of today.

`A2.1` (blocked, citing `C7.13` and `C7.14`): `C7.14` closed in this repository since the note was
written. Stale in half; see Part 4.

`A1.2` (in-progress; note: "closed 2026-09-12 with dev deploy green; canonical final check unmet,
remainder filed as ...#1629"): AISL issue 1629 is now closed (2026-09-16), with five slices
shipped and "Deploy Dev green" recorded on the closing comment; the remaining four non-test
`EmailService()` call sites this audit found in Part 1 (phase 1) are the exact, named, accepted
exemptions from that same closing comment (campaign family until `A6.3`; `privacy_workflow.py`
until the package grows a redacted-recipient seam). The STATUS row still describes the remainder
as merely "filed", not shipped and closed. Stale: the row undercounts what is actually done on
the AISL side. Left for the owner to update, per the instruction not to edit STATUS.md here.

Not independently re-verified (would need more `gh`/site access than the above and are lower
priority given the request's examples were the two confirmed-current rows above): `D2.2a`'s and
`D2.2b`'s references to `website#345`/`aws-infra#56` (same blockers just reconfirmed live) and
`website#405` (checked: still open, so `D2.2b`'s note is current); `D3.1a`'s "245 commits ahead"
count, which is a moving target by construction and was not re-measured.

## Commands run

```
uv init test0 && uv add "community-base @ git+https://github.com/DataTalksClub/community-base@v0.1.0"
uv run python -c "import community_base"
grep -rn "integrations.config\|core.operational_settings\|core.site_settings" --include=*.py . | grep -v tests | grep -v migrations   (both sites)
grep -n qcluster deploy/task_definitions.py   (dtc-website)
grep -rln datamailer --include=*.py . | grep -v migrations   (dtc-website)
grep -rn "EmailService()" --include=*.py . | grep -v tests   (ai-shipping-labs)
ls templates/studio/base.html   (both sites)
manage.py studio_routes --check   (both sites)
ls integrations/services/github_sync/, content_sync/   (both sites)
manage.py shell -c "from django.contrib.auth import get_user_model as g; print(g().__module__)"   (both sites)
ls accounts/, questionnaires/, community/, notifications/, comments/, voting/   (ai-shipping-labs)
grep -rn "^class \(Course\|Module\|Unit\)(" --include=*.py . | grep -v migrations   (both sites)
ls events/   (both sites)
grep -rn "sesv2\|django_q" --include=*.py . | grep -v migrations, ls email_app/   (ai-shipping-labs)
ls community_base/mail/backends/, community_base/jobs/backends/, community_base/curriculum/parsers_*.py, find -iname "*check_content*"   (community-base)
git merge-base --is-ancestor <C7.4 commit> v0.4.7; git log v0.4.7..main
uv run python scripts/plan.py check, summary
gh issue view / gh run list / gh run view   (community-base, ai-shipping-labs, dtc-website, aws-infra, read-only)
```
