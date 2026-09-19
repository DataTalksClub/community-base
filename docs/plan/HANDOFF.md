# Handoff, 2026-09-19

State and open work for whoever picks this up next. Written to be read once, top to bottom, before
touching anything. Every claim here has a date on it because four repositories are moving; verify
before relying on any of it.

## Where the four repositories stand

| Repository | main | State |
|---|---|---|
| community-base | `de90a4b`, tag `v0.5.4` | complete for this campaign, pushed |
| DataTalksClub/website | `550f714f` plus unmerged branches | green at 4338 tests |
| AI-Shipping-Labs/website | `7ac27353` | green, A7.4 merged and deployed |
| DataTalksClub/relay | `e4dc005` | blocked on production, see below |

`docs/plan/STATUS.md` is the single source of truth. Run `uv run python scripts/plan.py next` for
what is startable and `check` before every push.

## The one thing blocking the most

`DataTalksClub/aws-infra` issue 56. The `website-development-terraform-plan` role's live trust
policy does not accept the immutable OIDC subject the workflow now presents. The terraform already
declares the correct policy, so this is drift, not a code defect, and terraform cannot fix it
because the role gates the apply that would.

It needs one out-of-band IAM action in account `817685572750` by a human with sandbox IAM
authority. The exact commands are in aws-infra pull request 57 (`fix/website-terraform-plan-trust-
reconciliation`), which is documentation only. Reconcile the `-apply` role in the same operation;
it has the identical defect by construction.

The chain behind it: dev deploys, then D1.2ca and D1.2cb's gates, then the D1.3 freeze weekend,
then a four-week observation window (decision D13), then R6.1 and R6.2 in Relay. Relay cannot be
finished before that window closes, and nothing in Relay is waiting on code.

## Branches with committed work, not merged

- dtc-website `d2.1a-pin-bump` (1 commit): pin to v0.5.4, mapping drift fixed, frozen hashes
  regenerated. Verified green apart from two timing failures under host load, attributed.
- dtc-website `d3.3-relation-guard` (2 commits): the relation guard derived from the model graph,
  plus the evidence-invariant fix that completing the measurement exposed. NOT verified: its test
  run produced no output in 280s under load 150-170 with swap exhausted. Verify before merging --
  it changes the reviewed account merge, which merges real member accounts.
- dtc-website `d7.1-rebased` (6 commits): D7.1, fully verified, BLOCKED. Two files it touches are
  uncommitted in the shared checkout by a session nobody has identified: `core/views.py` and
  `playwright_tests/test_accessibility.py`. Do not move the ref around git's refusal; their copies
  would then silently revert D7.1's changes when committed.
- community-base `c7.24-config-reset-and-restart` (1 commit): verified, 34 config tests pass.
- community-base `c7.30-main-landmark` (1 commit): not verified here.

## Open issues worth knowing about before you start

`C7.12a` blocks the AISL content adoption and contains two real defects: the sanitiser strips
`target="_blank"` from the extension whose only purpose is setting it, and strips
`data-event-widget`, which is the JavaScript hydration key, so every event widget in synced
markdown renders as a permanent loading state.

`A7.2a` carries an access-gating trap. C7.12's shipped `aisl-wiki` profile writes the package wiki
kind, and that site's member wiki is gated at Basic and above. Registering it as shipped routes 20
member-gated pages into public wiki storage. Rule on it before registering any kind.

`D3.4` is unstarted and was stopped mid-flight; it needs a real concurrency reproduction, which
needs a quiet machine.

`C7.31`, `A7.5`, `D7.6` are the unstyled-page problem: a shared public page's primary action can be
undiscoverable before a site writes its `cb-` rules.

## How to work here, learned the hard way

Read `docs/04-quality-gates.md` before writing a check. Its longest section is the dominant failure
of this programme: a check that runs, reports success and measures nothing. Six instances in two
days, six unrelated mechanisms. Make every new gate fail on purpose before believing it.

Three repositories have shared working directories that several sessions write to at once. Never
`git add -A`. Stage by explicit path, read `git status` before every commit, and account for every
line including ones you did not write. Check overlap before merging into a shared checkout.

Do not run full test suites in parallel. This box is 12 cores; a previous session put load at 320
with swap exhausted, and the results from that period are not trustworthy. One suite at a time.

Commit as you go. Three agents in one wave left substantial work uncommitted for over an hour, and
work that is uncommitted also makes a branch look empty to a cleanup pass.

`uv` for every Python command. No bold in documents. No attribution lines in commits.
