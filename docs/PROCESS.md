# Process for one issue

The per-issue workflow. `AGENTS.md` says how to pick an issue; this file says how to carry it
from start to done. Every step has a check.

Work inside `AI-Shipping-Labs/website`, `DataTalksClub/website` and `DataTalksClub/relay` follows
that repository's own process (`AGENTS.md`, `_docs/PROCESS.md` or `docs/PROCESS.md`): its issue
tracker, branching, role agents, review, commit rights, test selection and deploy workflows. The
steps below add the plan-specific parts (dependencies, verification, status tracking); they do
not replace the site process.

## 1. Prepare

| Step | Check |
|---|---|
| Read the issue section in `docs/plan/phase-<n>.md` end to end. | You can say in one sentence what "done" is. |
| Read every file in "Read first". | You can name the function or template each step will change. |
| Confirm every id in "Depends on" is `done` in `docs/plan/STATUS.md`. | If not, stop; pick another issue or mark this one `blocked`. |
| For a package version a site issue needs: `git ls-remote --tags https://github.com/DataTalksClub/community-base v<version>`. | Tag exists. |
| Set the STATUS row to `in-progress`. | `python scripts/plan.py check` prints OK. |

## 2. Build

| Step | Check |
|---|---|
| Create a branch named `<issue id lowercase>-<slug>` in the target repository. | `git branch --show-current` matches. |
| Do the steps in order. After each step run the step's verification if it has one. | Expected result matched; if not, fix before the next step. |
| Keep the diff to the issue. Unrelated cleanups go to a separate pull request. | `git diff --stat` shows only files the issue implies. |
| Write or move tests as the issue says. | Quality gate section 3 counts recorded. |
| Update the docs listed under "Docs". | Files changed. |

## 3. Verify

Run, in this order, and paste the outputs into the pull request description:

1. the issue's "Verification" commands;
2. the quality gates in `docs/04-quality-gates.md` section 1;
3. section 2 if migrations changed; section 3 if code moved between repositories;
4. `python scripts/plan.py check` in this repository.

A verification that cannot be run in your environment (needs a deployed environment, a Relay
sandbox key, or the owner) is listed in the pull request under "Not run here, needs:" with the
reason. It is not marked as passed.

## 4. Pull request

- Title: `<issue id> <issue title>`.
- Body: goal in one line; what changed; verification outputs; "Done when" checklist copied from
  the issue with the boxes ticked that you verified; anything not run.
- Link the pull request in `docs/plan/STATUS.md` (pull request in this repository if the issue
  is elsewhere).

## 5. Close

| Step | Check |
|---|---|
| Pull request merged, CI green. | Merge commit on `main`. |
| Site issue: development deploy green and the issue's deployed checks pass. | Output pasted in the issue or pull request. |
| Freeze issue: production checks pasted, freeze label removed (playbook P13). | |
| STATUS row set to `done`. | `python scripts/plan.py summary` reflects it. |
| Last issue of a phase: verify the phase exit criteria in the phase file and update the phase table in `docs/plan/README.md`. | |

## 6. When things go wrong

- A verification fails and the fix is not obvious after one honest attempt: mark the row
  `blocked` with the failing command in `Link`, write what you tried in the pull request, stop.
- The plan step is wrong (references a file that does not exist, a Relay endpoint with a
  different shape, a decision conflict): fix the plan text in this repository in a separate
  small pull request, explain why, then continue. Do not silently deviate.
- A migration rehearsal (playbook P14) loses rows: stop. Report counts. Do not merge.
