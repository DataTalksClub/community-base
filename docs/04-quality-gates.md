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
