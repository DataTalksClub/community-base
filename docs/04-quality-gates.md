# Quality gates

Every issue in `docs/plan/` assumes the gates in this file. An executor runs them without being
told again. A pull request that does not pass them is not done.

Apply each gate where its evidence can be produced truthfully. Package capability pull requests
run package-local checks. Donor equivalence, development-copy rehearsals, real Relay conformance,
site CI and deployed smoke checks belong to compatibility or adoption issues. Until then, preserve
them as `Not run here, needs:` rather than weakening or claiming the check.

## 1. Gates for every pull request

| Gate | Command | Expected |
|---|---|---|
| Lint | `uv run ruff check .` | no output, exit 0 |
| Format | `uv run ruff format --check .` | "already formatted" |
| Django checks | `uv run python manage.py check` (site) or `uv run python testproject/manage.py check` (package) | "System check identified no issues" |
| Migrations complete | `uv run python manage.py makemigrations --check --dry-run` | "No changes detected" |
| Migrations apply from empty | `rm -f /tmp/cb.sqlite3 && DATABASE_URL=sqlite:////tmp/cb.sqlite3 uv run python manage.py migrate` | ends with `OK` lines, no errors. In the package use `testproject/manage.py`. |
| Tests for touched apps | site: `uv run python manage.py test <app> --parallel 4`; package: `uv run pytest tests/<app>` | all pass |
| Affected tests (AISL only) | `make test-affected` | plan printed and executed, all pass |
| Boundary test (package only) | `uv run pytest tests/test_boundaries.py` | pass |
| No local link committed (sites only) | `grep -n 'path = "../community-base"' pyproject.toml` | no output |
| Docs updated | the issue's "Docs" line | files listed in the issue changed |

Full-suite rule for AISL: do not run the full Django suite locally. CI runs it on every push to
`main`. Local scope is `make test-affected` plus the touched app.

Package extras: run `uv sync --all-extras` in any fresh checkout or git worktree before the test
gates. Several test modules begin with `pytest.importorskip(...)` and are silently NOT COLLECTED
when their extra is missing, so the suite passes with a lower count instead of failing. At the
time of writing that is the sixteen tests in `tests/questionnaires/test_ai.py`,
`test_ai_persistence.py` and `test_ai_views.py`, which need the `ai` extra: a default worktree sync
collects 1318 where a full sync collects 1334. CI already uses `uv sync --all-extras`, so a
regression there is caught on push; the risk is a local run reporting a green full suite that never
executed those modules. Report the collected count alongside the result, and compare it against a
baseline measured in the same checkout -- counts are not comparable between checkouts with
different extras installed.

## 2. Gates for a pull request that touches migrations

Run in addition to section 1.

| Gate | How | Expected |
|---|---|---|
| Migration is reversible or documented | `uv run python manage.py migrate <app> <previous>` then `migrate <app>` | both succeed, or the migration docstring says "irreversible" and why |
| Squash equivalence (playbook P4 only) | `uv run python manage.py migrate --plan` on a database at the pre-squash state | plan shows zero operations for the squashed app |
| Rehearsal on a copy of the development database (playbook P14) | restore dump, migrate, run smoke | migrate finishes, smoke passes |
| No data loss | row counts before and after for every table the migration touches, recorded in the PR description | equal, or the difference is explained by the issue |

## 3. Gates for a pull request that moves code between repositories

| Gate | How | Expected |
|---|---|---|
| Tests moved, not dropped | count `def test_` in the removed site directory before, and in the package directory after | package count is greater than or equal to site count minus the tests the issue explicitly lists as site-specific |
| Import rewrite complete | `grep -rn "from <old_app>" --include=*.py <site>` | only the shim module the issue allows, or nothing |
| Templates moved | `find templates/<old_app>` in the site | empty, unless the issue lists overrides that stay |
| Site suite green | site CI on the PR | green |
| Package tag exists before the site PR merges | `git ls-remote --tags origin v<version>` | tag present |

## 4. Issue template

Every issue opened from this plan uses this template. Fields map to the sections of each issue in
`docs/plan/phase-*.md`.

```
Title: <phase>.<n> <short imperative>
Repository: community-base | DataTalksClub/website | AI-Shipping-Labs/website | DataTalksClub/relay
Depends on: <issue ids>
Freeze required: yes | no

Goal
<one paragraph>

Read first
- <file paths in the donor repository>

Steps
1. ...

Verification
- <command> -> <expected>

Done when
- [ ] ...

Docs
- <files to update>
```

## 5. Stop conditions

Stop, do not work around, and report to the owner when:

- a step needs production data or production credentials (agents never touch production);
- a verification command fails twice after a genuine fix attempt;
- a migration rehearsal on a development copy loses rows;
- a step would change a decision in `docs/01-decisions.md`;
- a squash `replaces` list does not match the migration names actually present in the donor;
- a tag or release would include a provisional kept-label migration;
- a Relay endpoint the issue relies on does not exist or returns a different shape than the
  issue describes;
- the package version needed by a site issue has not been tagged;
- an AISL freeze weekend has not been announced and the issue says "Freeze required: yes".

## 6. Definition of done for a phase

- every issue in the phase is merged and its tag or deployment is live in the development
  environment of each affected site;
- the phase's exit criteria in `docs/plan/phase-<n>.md` are verified with the listed commands;
- `docs/plan/README.md` status table is updated in the same pull request that closes the last
  issue.

## A gate that measures the wrong thing

A failing gate is a signal. A gate that passes while measuring something other than what it claims
is worse than no gate, because it produces confidence instead. Five instances inside twenty-four
hours, all found by accident rather than by a check:

- A DataTalksClub main run reported green having executed no tests at all: playwright ran in reused
  mode. Months of accumulated breakage sat behind a gate that reported success the whole time.
- A cached template loader made four separate mutations render identically, so a mutation test
  passed on all four.
- A missing CSS build artefact left a hidden element clickable, so a test asserting it could be
  clicked passed for the wrong reason.
- Playwright's `to_have_count` passes against elements with `display: none`, so a count assertion
  held while nothing was visible.
- A local editable install repointed a whole site suite onto unreleased package code, so every
  local run in that checkout measured something the site does not ship.

The shape is the same each time: the gate's subject was not what the reader assumed. So when a
gate passes on something that matters, ask what it would take for it to pass while the thing it
names is broken, and check that case specifically. A green run is evidence only about the thing it
actually measured.

Two habits that catch this cheaply. Prove a new gate fails: write it, watch it go red against a
deliberately broken input, and only then fix the input. And when a gate passes unexpectedly early
or unexpectedly fast, treat that as a reason to look rather than a result.

## A bad change rides in on a good one

Two unrelated edits sitting in one working tree get committed together by a single `git add -A`,
and the commit is then reviewed as the change its message names. This survives review by
construction, not by bad luck: a reviewer looking at a commit that adds a canonical URL to an event
API is checking whether that URL logic is sound. A one-line dependency entry at the bottom of the
file list reads as incidental, and nobody reviewing a good change looks hard at it. The broken half
gets in on the good half's back.

Observed on 2026-09-18, where a shared site checkout held real, wanted API work and a local
editable dependency pin at the same time. The pin would have failed CI, because the local path does
not exist on a build machine -- but only after being approved.

So: stage by explicit path, never `git add -A`, in any checkout you do not know you are alone in.
Read `git status` before every commit and account for every line of it, including the ones you did
not write. If a file you did not touch is modified, find out why before committing, and do not
assume a checkout is yours because you have been using it all day.

## Work in a repository other sessions may be using

Three habits, each of which removes a whole class of accident:

- Merge from a throwaway detached worktree at `origin/main` and push `HEAD:main`. This never reads
  or writes the shared working tree, so it cannot pick up someone else's uncommitted change, cannot
  conflict with their files, and cannot rewrite files underneath a test run someone is about to
  read as evidence. That last one matters most: a suite whose files changed mid-run gives a result
  that is worthless whether or not anyone notices.
- Do not revert someone else's change while a run may be using it. A run that completes against a
  wrong state and reports green is recoverable if you know it happened; it is not recoverable if
  the state was reverted underneath it and the result was kept.
- A clean worktree isolates the files, not the machine. A run there still shares CPU with whatever
  else is executing, so a starved run in a clean worktree can still be caused by a contended one.
  Isolation of state is not isolation of measurement.

## Report observations with their shelf life

When several sessions work the same trees at once, the most common wrong statement is not a
careless one. It is a confident report about a tree that has since moved, made by someone who
looked.

Four instances on 2026-09-18, none from carelessness: a dependency list measured on a branch eight
commits behind main and quoted as current; a session concluding a branch had landed because its
commit message said "Refs #384"; one session reading a link snapshot that another found absent
minutes later; and the reverse, a directory reported present that was gone by the next reader. Each
reporter had checked. No amount of individual care removes this, because it is a property of shared
mutable state rather than of anyone's rigour.

Two habits make these reports survive contact with a moved tree.

Timestamp the observation and name the tree. "As of 08:23, `.tmp/core-link/` exists" and "measured
on `d71-rebased`, which is 8 commits behind main" are both still true after the fact, and a reader
can tell whether they still apply. "The snapshot exists" and "the dependency surface is 12 names"
silently become false.

Separate the inference from the observation, and flag what it rests on. An observation has a short
shelf life; the conclusion drawn from it usually sounds permanent. "The sanctioned recovery path is
unavailable" invites action and outlives its evidence. "If the snapshot is genuinely absent, then
`unlink` will refuse" says the same thing, is cheap for the next person to re-check, and fails
safely when the premise has expired.

This applies to what you tell a person as much as to what you tell another session. A conclusion
handed over without its premise is one the reader cannot re-derive when it stops being true.

## Shipping an asset is not shipping what it references

C7.20 vendored a minified JavaScript bundle and shipped it without the source map
its own trailing `sourceMappingURL` names. Every check passed: the file was in
the wheel, the icons rendered, the package suite was green, and the consuming
site's full suite was green twice. It broke on the first `collectstatic` under
manifest-based static storage, which post-processes JavaScript and hard-fails on
a reference it cannot resolve. That took a site's deploy down, five releases
after the file landed.

The verification asked "does the asset ship", and the failing claim was "does
what the asset points at ship". Those are different questions and only the first
was put. `tests/test_static_asset_references.py` now asks the second for every
shipped `.js` and `.css`, and it is pinned by its own emptiness guard, because an
enumeration that finds nothing passes silently.

Generalising past source maps: a vendored file is a promise about its
dependencies as well as itself. Fonts referenced from CSS, images from a
stylesheet, a chunk another chunk imports -- each is a reference a consumer's
static pipeline will try to resolve, in an environment stricter than the one the
package tests in. When vendoring anything, enumerate what the file points at and
ship all of it, or strip the reference.

A note on how this was diagnosed, because the false trail cost more than the
fix. The first traceback in the failing build was a `no such table` error that a
handler caught, logged and continued past; it appears twelve times in the green
build too. Careful reasoning about it was wasted, because it was never
load-bearing. The first log line that looks like an error is not the same as the
line that failed the build. Find the step that actually returned non-zero before
explaining anything.

