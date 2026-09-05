# Agent notes

You are implementing the unification plan for DataTalks.Club community sites. This file is the
entry point. Read it fully before doing anything else.

## What this repository is

`community-base` is the shared Django package extracted from two sites, AI Shipping Labs
(`AI-Shipping-Labs/website`) and DataTalks.Club (`DataTalksClub/website`), with Relay
(`DataTalksClub/relay`) as the email and jobs service. The package code does not exist yet; the
plan in `docs/plan/` builds it and moves code out of the sites in seven phases. Work happens in
four repositories; progress for all of them is tracked here in `docs/plan/STATUS.md`.

## Read in this order, once

1. `docs/04-quality-gates.md`: the checks every pull request must pass and when to stop.
2. `docs/01-decisions.md`: decisions already taken. Do not re-open them.
3. `docs/02-architecture.md`: what the package looks like and the rules that keep it composable.
4. `docs/03-playbooks.md`: reusable procedures the issues refer to by number (`P4`, `P13`).
5. `docs/plan/README.md`: the phase index.
6. `docs/00-analysis.md`: background. Skim; come back when an issue's "Read first" list points
   to something you do not understand.

## How to pick work

1. `python scripts/plan.py next` lists issues whose dependencies are done. Take the first one in
   the lowest phase unless the owner assigned you something else. Relay issues in Phase 1 are
   the critical path and may be taken in parallel with Phase 0.
2. Open the issue's section in `docs/plan/phase-<n>.md`. It has: goal, "Read first", numbered
   steps, verification commands with expected results, "Done when" checkboxes, docs to update.
3. Mark it `in-progress` in `docs/plan/STATUS.md` (see "Tracking" below) before starting.

## Working in the site repositories

Most issues change `AI-Shipping-Labs/website`, `DataTalksClub/website` or `DataTalksClub/relay`.
Those repositories have their own development process, and it governs the work there:

| Repository | Local clone | Process to follow |
|---|---|---|
| `AI-Shipping-Labs/website` | `../ai-shipping-labs` | `AGENTS.md`, `_docs/PROCESS.md` (issue pipeline, role agents, who may commit), `_docs/testing-guidelines.md`, `scripts/affected_tests.py` |
| `DataTalksClub/website` | `../dtc-website` | `AGENTS.md`, `_docs/PROCESS.md`, `_docs/specs/` as the product authority, `_docs/architecture/app-boundaries.md` |
| `DataTalksClub/relay` | `../relay` | `AGENTS.md`, `docs/PROCESS.md`, `docs/testing-guidelines.md` |

Concretely: open the issue in that repository's tracker the way its process says, use its
branch, review and merge rules, run its test selection, deploy through its workflows, and never
bypass its rules because "the plan says so". This plan tells you what to build and how to verify
it; the site process tells you how work is done in that repository. When the two conflict, the
site process wins for anything about branching, review, commit rights, testing scope, deploys and
production access, and the conflict is reported here as a plan fix.

## How to do an issue

- Work in the repository the issue names, following that repository's process (previous
  section). This repository's `docs/PROCESS.md` describes the per-issue flow for the plan.
- Follow the steps literally. Run every verification command. Compare with the expected result.
  A failing check is fixed before the next step; it is never skipped or reworded.
- One pull request per issue, titled `<issue id> <issue title>`, in the repository the issue
  names. The pull request description contains the verification output the issue asks for.
- Package changes that a site issue needs must be tagged first (playbook P15). A site pull
  request never points at a branch or a local path.
- When a step is ambiguous, choose the reading that matches `docs/02-architecture.md` and say so
  in the pull request. When a step contradicts a decision or hits a stop condition
  (`docs/04-quality-gates.md` section 5), stop and report instead of improvising.
- If an issue turns out to be too large for one pull request, split it: add the sub-issues to the
  phase file (same numbering with a letter suffix, `C2.3a`), run `python scripts/plan.py sync`,
  and continue with the first part.

## Tracking

`docs/plan/STATUS.md` is the single progress view across all four repositories. It is generated
from the phase files by `scripts/plan.py`; only the `Status` and `Link` columns are edited by hand.

- Starting an issue: set `in-progress` and put the pull request URL in `Link`.
- Blocked: set `blocked` and write the blocking issue id or reason in `Link`.
- Finished: set `done` after the pull request merged and the verification passed; for site
  issues, after the development deploy is green.
- Because STATUS.md lives in this repository, a status change for a site issue is a small pull
  request here that touches only `docs/plan/STATUS.md`. Do it in the same session as the site
  pull request.
- Run `python scripts/plan.py check` before pushing; CI runs it too.
- Phase status in `docs/plan/README.md` changes when the phase exit criteria are verified.

Optionally mirror an issue as a GitHub issue in its repository (label `community-base`) and put
that URL in `Link` until the pull request exists. STATUS.md remains the source of truth.

## Conventions

- `uv` for every Python command. Never `pip`.
- Documents: plain text, headings, tables, backticks. No bold. One idea per bullet.
- No secrets, tokens, production data or email addresses in logs, issues, pull requests or docs.
  Agents never access production databases or credentials (site rules).
- Commit messages and pull request descriptions carry no attribution lines.
- Keep the package free of site imports; `tests/test_boundaries.py` enforces it once it exists.
