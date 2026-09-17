# Release readiness for the next community-base release

Date: 2026-09-17. Repository: `community-base`. Range examined: `v0.4.7..main`, with `main` at
`34be2a5`. Nothing was tagged, no version was bumped, and no tag was moved or deleted while
producing this report.

Three things wait on this release.

- `D7.1` (DataTalksClub/website#406) is implemented but cannot merge: `D0.2` fails a site pull
  request against anything but a tagged package, and `C7.4` exists only on `main`.
- `C5.2f`, `C5.2g`, `C5.2h` and `A7.1` are merged and unreleased.
- A consumer that bumps its pin past `v0.4.7` hits a known breakage in DataTalks.Club.

## Verdict in one table

| Question | Answer |
|---|---|
| What is unreleased | 83 commits, 117 files, 10206 insertions, 212 deletions; seven capability groups |
| Can a release be cut under the rule as written | No. Nine provisional migrations sit on `main` and neither `C3.7` nor `C4.3` can run yet |
| Is that a new situation | No. Every tag from `v0.4.0` to `v0.4.7` already shipped four provisional migrations |
| Is the `v0.4.7` tag moved | Yes, confirmed independently. The remedy is already merged as `34be2a5` |
| What must ship alongside | One change to `_mapping()` in the DataTalks.Club importer, in the same pull request that bumps the pin |
| Recommendation | Cut the release now under a written, scoped owner exception; see section 6 |

## 1. What is unreleased

Commands and results, run in a clean worktree of `main` at `34be2a5`:

    git rev-parse refs/tags/v0.4.7^{commit}   -> ab8e8ab
    git rev-list --count v0.4.7..main         -> 83
    git diff --shortstat v0.4.7..main         -> 117 files changed, 10206 insertions(+), 212 deletions(-)

### Why work merged before the tag is still unreleased

`v0.4.7` was not cut from the tip of `main`. The tagged commit `ab8e8ab` descends from `v0.4.6`
(`449e315`, 2026-09-16 19:18), while the `C5.2f`/`C5.2g`/`C5.2h` merge `387d8de` landed on `main`
at 2026-09-16 22:19, three hours before `e98c338` was written. The release branch was then merged
into `main` as `9ee3f98`. `git ls-tree -r --name-only v0.4.7 | grep coursework/migrations` returns
only `0001_initial.py`, which confirms it: the coursework work is not in the tag even though it
predates it.

Every `0.4.x` tag is an ancestor of `main`, so there is no divergent maintenance branch to merge
back; the release line simply trails the tip.

### User-visible capability groups

| Group | Merge | Topic commits | What a consumer gains |
|---|---|---|---|
| `C5.2f` | `387d8de` | 6 (shared with `C5.2g`, `C5.2h`) | Pooled peer-review assessment mode, per-submission review lifecycle, `PeerReviewBatch` |
| `C5.2g` | `387d8de` | as above | Pooled review expiry sweep, four coursework mail purposes, extended deadline reminder |
| `C5.2h` | `387d8de` | as above | Certificate eligibility, learner-requested issuance, banner-generator seam, member API route |
| `C5.1g` (issue 255) | `891092e` | 6 | Structured code annotations in curriculum unit bodies, with an overridable template |
| Issue 249 | `225dc5c` | 3 | `EventSeries.visibility`, a hidden-series discovery flag |
| `C7.5` | `9cac088` | 4 | Kernel `RevisionedModel`, `RevisionConflict`, `AppendOnlyManager`, `AppendOnlyQuerySet` (D19) |
| `C7.6` | `72be38f` | 6 | Accounts `AccountSession` plus an opt-in session store and two services (D20) |
| `C7.4` | `c2796cb` | 5 | Knowledge base site-owned page identity, rendering and record metadata |
| `C7.14` | `dfa1b30` | 6 | Studio sidebar collapse, destination icons and external links, grouped search results |

That is 36 topic commits plus 7 merge commits. The remaining 40 commits change no shipped code:
owner decisions `D19` to `D32`, the unified content format specification and its issues `C7.7` to
`C7.12` with the site adoption issues, the `A3.2c` escalations, the `D3.1` phased split, seven
`STATUS.md` updates, the quality-gate `--all-extras` note, the bold-gate glob fix, the cross-repo
baseline verdict, the release-tag guard, and the `v0.4.7` release merge itself.

### Breaking or behaviour-changing, listed separately

- `rendering.sanitize_rendered_html` now passes nh3 the attribute allowlist its filter was written
  against, so `class`, `id`, `lang` and `title` survive where they were silently dropped (`C7.4`).
- The knowledge base constraint `cb_kb_page_section_slug_unique` is gone, replaced by the
  conditional pair `cb_kb_page_child_slug_unique` and `cb_kb_page_root_slug_unique`; anything
  naming the old constraint breaks (`C7.4`).
- `Unit.save` renders through `render_annotated_markdown` and now raises on a malformed annotation
  payload instead of publishing it. Bodies with no `structured: true` comment are unaffected, but
  the failure mode for a bad one changed from silent to fatal (`C5.1g`).
- `assign_peer_reviews_for_project` and `score_project` refuse to run against a pooled project
  (`C5.2f`).
- The leaderboard and project statistics read `ProjectSubmission.review_state` instead of
  inferring completion from `Project.state`; a data migration backfills it (`C5.2f`).
- `PeerReview.state` gains an `EXPIRED` choice (`C5.2g`).
- `community_base.coursework` now imports `pooling` eagerly at startup, which registers the handler
  and the schedule `coursework.expire_pooled_reviews.every_15_minutes` on any site that installs the
  app (`C5.2g`).
- `sync.delete_missing` takes exactly one of `seen_slugs` or `seen_source_paths`; neither is
  positional-required any more and passing both is an error (`C7.4`).
- `accounts` migration `0002_accountsession` issues an `ALTER TABLE` on `django_session`, a table
  `django.contrib.sessions` owns. No consumer installs `community_base.accounts` today, so it runs
  nowhere yet (`C7.6`).
- The Studio sidebar collapse is threshold-guarded: below `STUDIO_NAV_COLLAPSE_THRESHOLD`
  (default 24) the rendering is unchanged, and the package registry is 21 destinations (`C7.14`).

### Package gates on `main` at `34be2a5`

    uv run ruff check .                                              -> All checks passed!
    uv run ruff format --check .                                     -> 667 files already formatted
    uv run python testproject/manage.py check                        -> System check identified no issues (0 silenced)
    uv run python testproject/manage.py makemigrations --check        -> No changes detected
    DATABASE_URL=sqlite:///... migrate (empty database)              -> ends with voting.0001_initial OK
    uv run pytest -q                                                 -> 1476 passed in 243s
    uv run python scripts/plan.py check                              -> OK: 136 issues, STATUS.md consistent
    uv run python scripts/check_no_bold.py                           -> no output

The worktree was synced with `uv sync --all-extras`, so the sixteen `ai`-extra tests were
collected. The count baseline in `docs/04-quality-gates.md` (1318 without extras, 1334 with) is
from an older checkout and is not comparable to 1476.

Not run here, needs: either site's full Django or Playwright suite; a development-copy migration
rehearsal; a deployed smoke check.

## 2. The provisional migration blocker

`AGENTS.md` says a kept-label migration is provisional until its donor inventory and equivalence
checks pass, and that a release containing one must not be tagged. `docs/04-quality-gates.md`
section 5 repeats it as a stop condition.

### Every provisional migration on `main`

Found by reading every file under `community_base/*/migrations/`, not by trusting a list.

| Migration | How it declares itself | Equivalence check owned by |
|---|---|---|
| `accounts/0001_provisional_initial.py` | docstring: provisional package-first schema | `C3.7` |
| `accounts/0002_accountsession.py` | docstring: kept provisional until the AISL donor checks pass | `C3.7` |
| `comments/0001_initial.py` | header comment: provisional kept-label migration | `C3.7` |
| `notifications/0001_initial.py` | header comment: provisional kept-label migration | `C3.7` |
| `questionnaires/0001_squashed.py` | docstring: do not tag before the `C3.7` compatibility proof | `C3.7` |
| `events/0001_provisional_initial.py` | filename | `C4.3` |
| `events/0002_provisional_registration.py` | filename | `C4.3` |
| `events/0003_provisional_integration_attempt.py` | filename | `C4.3` |
| `events/0004_provisional_eventseries_visibility.py` | filename | `C4.3` |

Nine, not the two the brief named. Two more kept-label apps under `D10` carry no marker at all and
should: `community/0001_initial.py` and `voting/0001_initial.py` are initial migrations for apps
whose label is reused from the AISL donor, and neither says it is provisional nor carries a
`replaces` list. `grep -rn 'replaces' community_base --include=*.py` finds no `replaces` marker
anywhere in the package. That is a gap in the marking, not a separate blocker: whatever `C3.7`
concludes about `comments` and `notifications` applies to these two as well.

### Can the release be cut

Not under the rule as written. Both owners are unreachable today.

- `C3.7` (STATUS row: `todo`) depends on `C3.6`, `A3.2` and `D3.1e`.
- `C4.3` (STATUS row: `todo`) depends on `C4.2` and `A4.1`; `A4.1` is `todo` and depends on
  `C5.2a` and `A3.2`.
- `C5.3` "Release 0.6.0" already encodes this: it depends on `C3.7`, `C4.3`, `C5.2e`, `C5.1e` and
  `C5.2h`.

So a release cut now needs an explicit owner exception. The question is how large an exception,
and the history answers it.

### The rule has never been met in the 0.4 line

    for t in v0.4.0 v0.4.5 v0.4.6 v0.4.7; do git ls-tree -r --name-only $t | grep provisional; done

Every one of those four tags already contains `accounts/0001_provisional_initial.py` and the three
`events` provisional migrations. The prohibition has been overridden by practice on at least four
published tags, without a recorded exception. This release adds two more provisional migrations
(`accounts/0002_accountsession` and `events/0004_provisional_eventseries_visibility`) to a tag
line that already carries four.

The practical cost of tagging is not the schema. It is `docs/PROCESS.md` section 2: once tagged,
package migrations are append-only and their `replaces` markers stay. Tagging `events/0004` and
`accounts/0002` removes `C4.3`'s and `C3.7`'s freedom to rewrite those two files when they
finalize the squashes. Section 6 says how to keep that freedom.

## 3. The moved `v0.4.7` tag

Confirmed independently of the earlier note in `d71-knowledge-base-gap-2026-09-17.md`.

| Where | Commit | `pyproject.toml` | `community_base/__init__.py` |
|---|---|---|---|
| `refs/tags/v0.4.7` today | `ab8e8ab` | 0.4.7 | 0.4.7 |
| What `dtc-website/uv.lock` resolved `v0.4.7` to | `e98c338` | 0.4.6 | 0.4.7 |
| `main` at `34be2a5` | `34be2a5` | 0.4.7 | 0.4.7 |

`git log -1 --format='%H %P' ab8e8ab` gives `e98c338` as its only parent, and `ab8e8ab`'s subject
is "Bump the pyproject version to 0.4.7". `dtc-website/uv.lock` line 234 records
`source = { git = "...?rev=v0.4.7#e98c33811593c12a24adeed1df7b91e72feeb86c" }` with
`version = "0.4.6"` on line 233. The tag was cut at `e98c338`, a consumer locked it, and the tag
was then moved to `ab8e8ab`.

### Consequence for D1

D1 says sites pin a git tag in `uv.lock`. A pinned tag is only a pin if it resolves to the same
bytes forever. It did not: a lock taken before the move and a lock taken now produce different
trees for the same tag name. The two trees differ only in a version string, so nothing behaves
differently, but the guarantee D1 relies on was broken and the evidence is visible in the DataTalks.Club
virtualenv, which carries `community_base-0.4.6.dist-info` while its `direct_url.json` records
`requested_revision: v0.4.7`.

There is a second, smaller consequence: the string `0.4.7` currently names three different trees,
`e98c338`, `ab8e8ab` and `main`. A bug report quoting a version number cannot be resolved to a
commit.

### Remedy

Leave `v0.4.7` alone. Do not move or delete it again; a second move would break the consumers that
have since re-locked. Cut the next release at a commit that already carries its own version bump in
both `pyproject.toml` and `community_base/__init__.py`.

The enforcement half is already merged: `34be2a5` adds `scripts/check_release_tag.py`, wired into
`.github/workflows/release.yml` before `uv build`, which fails a tag whose name disagrees with
either version string in the tagged commit. It would have caught `v0.4.7` at `e98c338`, because
`pyproject.toml` there said 0.4.6. No further code is needed for this item.

## 4. What must ship alongside, in DataTalks.Club

### The mapping guard

`scripts/prod/import_shared_course_platform.py:_refuse_mapping_drift` (line 242) walks `_mapping()`
and, for each site-to-package model pair, computes the package model's concrete non-primary-key
fields minus `auto_now`/`auto_now_add` fields, minus the second element of the tuple
(`package_written`), minus the third (`package_defaults`). Anything left is drift and raises
`MappingCoverageDrift`.

For the coursework pairs, `package_written` is built by the local helper `written(site.X, ...)`,
that is from the site model's field names. Any field the package gains and the site does not have
is therefore drift by construction. Three such fields landed since `v0.4.7`, all in
`coursework/migrations/0002_project_pooled_review_window_days_and_more.py`:

| Package model | New field | Issue |
|---|---|---|
| `cb_coursework.Project` | `pooled_review_window_days` | `C5.2f` |
| `cb_coursework.ProjectSubmission` | `review_state` | `C5.2f` |
| `cb_coursework.PeerReview` | `batch` | `C5.2f` |

The new `PeerReviewBatch` model does not trip the guard: it appears in no mapping pair, and the
guard only iterates pairs.

### What `_mapping()` needs

Each of those three fields must be added to the third element of its pair's tuple, the
`package_defaults` frozenset, which today is `frozenset()` for all three. That is the slot the file
already uses for package-only columns the import leaves at their model default, as in the
`cb_curriculum.Course` pair (`description_html`, `cover_image_url`, `required_level` and the rest)
and the `cb_curriculum.Certificate` pair (`hash`). Concretely:

- `("courses.Project", "cb_coursework.Project", False)`: third element becomes
  `frozenset({"pooled_review_window_days"})`.
- `("courses.ProjectSubmission", "cb_coursework.ProjectSubmission", False)`: third element becomes
  `frozenset({"review_state"})`.
- `("courses.PeerReview", "cb_coursework.PeerReview", False)`: third element becomes
  `frozenset({"batch"})`.

Each needs the comment the file's convention requires, saying why the import does not write the
column. For `review_state` that reason is not cosmetic: `C5.2f` ships a data migration that
backfills `review_state` from `Project.state`, so an imported row gets its value from the migration
and not from the copy. Whoever makes the change should confirm that the import runs after the
migration and that the backfill covers imported rows, or write the column explicitly instead of
defaulting it.

`written(...)` is a helper that reads the site model, so nothing on the site side drifts from this
release; the site models are unchanged.

### Correcting the failure count

The note in `d71-knowledge-base-gap-2026-09-17.md` and the `6aa360e` commit message say "17
`MappingCoverageDrift` errors". Seventeen is the number of failing tests, not the number of drift
findings: `scripts/tests/test_import_shared_course_platform.py` holds 18 tests across two
`TestCase` classes that share an `ImportRunMixin`, and each test that reaches the importer raises
the same exception. The exception itself names three fields across three models. The fix is three
lines, not seventeen.

### AI-Shipping-Labs

No equivalent guard exists and none would trip.

- `grep -rln 'MappingCoverageDrift|coverage_drift|_refuse_mapping_drift'` over
  `AI-Shipping-Labs/website` returns nothing. There is no shared-platform importer there; the
  course platform import is a DataTalks.Club-only script.
- `scripts/check_migration_safety.py` is the nearest thing, and it is scoped by
  `first_party_app_labels`, which keeps only apps whose package directory is inside the repository.
  Package apps install into `site-packages`, so every `community_base` migration is out of scope.
- AI-Shipping-Labs installs `kernel`, `config`, `api`, `studio`, `jobs`, `mail`, `content_sync` and
  `knowledge_base`. It installs neither `coursework`, `curriculum`, `events` nor `accounts`, so the
  coursework, events and accounts migrations in this release reach it not at all.

One thing does reach it, and is worth naming even though it is not a guard: AI-Shipping-Labs is
still pinned at `v0.4.6` (`uv.lock` resolves `449e315`), it installs `community_base.knowledge_base`,
and `A7.1` put live rows in those tables on the development environment. A pin bump takes it across
four knowledge base migrations at once, including the constraint swap in
`0002_page_key_scoped_to_parent`. That deserves its own pass; it is not covered by `D7.1`.

## 5. The assembled changelog

The `## Unreleased` section of `CHANGELOG.md` now carries one entry per merged, unreleased
capability, reconciled from the merge commit messages and the issue records: `C5.2f`, `C5.2g`,
`C5.2h`, `C5.1g`, issue 249, `C7.5`, `C7.6`, the two `C7.4` entries that were already there, and
`C7.14`. A closing entry names the provisional migrations the release would contain, so the
exception in section 6 is visible to a reader of the changelog and not only to a reader of this
file.

No version number was assigned, and `pyproject.toml` and `community_base/__init__.py` were not
touched.

One `STATUS.md` inconsistency turned up while collecting the entries: `C5.1g` is recorded
`in-progress` with a link to issue 255, while its work is merged on `main` as `891092e` and the
issue's own plan row was added in the same branch. The row should read `done`. Separately, the
`C7.4` row links to `DataTalksClub/community-base/issues/406`, which is a DataTalks.Club website
issue number; the link belongs to `D7.1`. Neither is fixed here, because this change is a docs
commit and `STATUS.md` edits belong to the issues that own those rows.

## 6. Recommendation

Cut the release now, from `main`, under one written owner exception that is scoped rather than
blanket. Do not wait for `C3.7` and `C4.3`.

The exception should say three things.

- The release may contain the nine provisional migrations listed in section 2, because four of them
  already ship in `v0.4.0` through `v0.4.7` and the two new ones reach no consumer that could be
  harmed: no site installs `community_base.accounts`, and `events/0004` only appends a column with a
  `public` default to an events schema DataTalks.Club already runs.
- The append-only promise in `docs/PROCESS.md` section 2 attaches to `C5.3` ("Release 0.6.0"), not
  to this tag. `C3.7` and `C4.3` keep the right to rewrite every migration named in section 2,
  including the ones this tag contains. This release is declared adoption-provisional in the
  changelog.
- The AI-Shipping-Labs freeze weekends `A3.3` and `A4.2` adopt from `C5.3` and never from this tag.
  Their STATUS dependencies already say so, so nothing changes; the exception only records it.

The version number should be `0.5.0`, not `0.4.8`. The release carries a constraint rename, a
render path that now fails closed, a peer-review lifecycle that moves the leaderboard's source of
truth, and a new schedule that registers itself at startup. Those are minor-version facts under the
project's own `0.x` usage, and `0.6.0` is already reserved by `C5.3`. A previous attempt to bump to
0.4.8 exists on `main` and was reverted (`a14de89`, then `f3fb3c3`), so the release commit starts
from 0.4.7 in both files.

Three things must be true before the tag is pushed.

- The version bump is in the tagged commit itself, in both `pyproject.toml` and
  `community_base/__init__.py`. `scripts/check_release_tag.py` now enforces it, and it is the whole
  remedy for section 3.
- `v0.4.7` is left exactly where it is.
- The DataTalks.Club pull request that bumps the pin carries the `_mapping()` change from section 4
  in the same pull request. A pin bump without it fails that repository's own tests before it
  reaches review.

### Why this rather than waiting

`C4.3` cannot start until `A4.1` does, and `A4.1` waits on `C5.2a` and `A3.2` in another repository;
`C3.7` waits on `C3.6`, `A3.2` and `D3.1e`. Waiting is not a short wait, and it is not a wait the
package can shorten on its own. Against that, `D7.1` is implemented and idle, `A7.1` is live on
development against an older package than the one that now holds its app's code, and four merged
coursework and curriculum capabilities sit unpinnable. The rule exists to stop a provisional squash
from becoming load-bearing under a donor's production tables. Nothing in this release is load-bearing
in that sense yet, because no donor adoption happens before `C5.3`.

### The risk being accepted

If `C3.7` or `C4.3` later concludes that `events/0004` or `accounts/0002` must be rewritten rather
than appended to, this tag will have published a migration that then changes shape. The exposure is
one consumer, DataTalks.Club, on one column with a default, plus a table no consumer installs. The
mitigation is the second clause of the exception: state in the changelog and in the exception that
these migrations remain rewritable until `C5.3`, so a consumer treats them as provisional and
`C3.7` and `C4.3` are not boxed in by the tag.

The residual risk this does not cover is process, not schema: publishing a fifth tag with
provisional migrations while the rule says otherwise makes the rule harder to enforce later. That
is an argument for writing the exception down, with its scope and its expiry at `C5.3`, rather than
for cutting another silent one.

## Addendum, 2026-09-17: the consumer-side blocker is fixed on a branch

Section 4's mapping work is done, on DataTalksClub/website branch
`fix/coursework-mapping-drift` (commits `d979d1da` and `3fe9ca0c`, from
`origin/main` 37874818). Not merged, not pushed; it still needs that repository's
tester and PM gates.

`_refuse_mapping_drift` was not weakened, bypassed or given an escape hatch. The
mapping now names what the package grew, and the three decisions are recorded as
decision 18 in that repository's
`_docs/architecture/course-platform-shared-apps-mapping.md`.

| Field | Decision |
|---|---|
| `ProjectSubmission.review_state` | derived from the site project's state, not defaulted |
| `Project.pooled_review_window_days` | explicit package default, 7 |
| `PeerReview.batch` | explicit null, and no `PeerReviewBatch` rows created |

### Defaulting review_state would have been a silent data bug

This is the part worth recording, because the cheap answer was wrong. C5.2f makes
`review_state` a pure mirror of `Project.state` in deadline mode, and the package
ships a `RunPython` backfill in `cb_coursework/migrations/0002` applying
`COMPLETED` to `SC`, `PEER_REVIEWING` to `IR` and everything else to `AW`.

That backfill runs at deploy. The P6 import creates its rows afterwards, so the
backfill can never see them. A defaulted `review_state` would therefore leave every
migrated submission of a finished DTC project reading as never assigned, and both
`leaderboard.completed_project_submissions_prefetch` and
`statistics.calculate_project_statistics` filter on `review_state == SCORED` since
C5.2f. The leaderboard and the statistics would have been quietly wrong for every
migrated cohort, with nothing failing.

The import applies the package's own table instead, keyed off `row.project.state`.

### It reads correctly on both sides of the pin bump

Naming an absent field is harmless to the guard, which only complains about model
fields the mapping does not name. Writing one is not, so the single derived write
asks the installed model first through `_package_carries`. Verified both ways:
against community-base main the module's tests are 19 passed; against the pinned
v0.4.7 they are 19 passed with 1 skipped, the skip being the new decision-18 test
declining to run on a release that predates C5.2f.

That guard and that skip are deliberate short-lived scaffolding. The bump that
carries C5.2f should remove both and make the write unconditional.
