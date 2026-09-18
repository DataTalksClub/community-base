# D3.1 enumeration audit, and one open decision about the expand window

Date: 2026-09-18. Run after an independent tester found a silent enumeration defect in the
equivalent AI-Shipping-Labs work (A3.2). The question was whether D3.1's moves take a relation or
field out of some service's reach the same way.

Two instances found, both reproduced side by side before fixing. One further finding is not a
defect to fix but a decision for the owner.

## The DTC enumerators, and why the AISL list did not transfer

There is no RELATION enumerator in DataTalksClub at all. Zero matches for `_meta.related_objects`,
`_meta.many_to_many`, `apps.get_models()` or reverse-accessor walking outside tests. Account merge
here reaches relations through a named `ACCOUNT_RELATIONS` tuple, and DTC has no deactivation or
GDPR-export service. So the three services that carried the defect on the other site do not exist
in this shape here, which is exactly why the audit grepped rather than assuming.

What DTC has instead is FIELD enumerators, and two of them matter.

## Instance 1: a learner profile counted as course activity

`courses/services/development_content_import.py:500` proves a target carries no learner work by
enumerating every `courses_` table outside a content allowlist. D3.1a puts a per-account table into
that namespace, one row per account on every migrated database.

| | behaviour |
|---|---|
| main | development content import succeeds |
| D3.1a | `DevelopmentContentImportError: target-course-activity-not-empty` |

So the development content import refuses on any development database that has accounts at all.
It stayed invisible because the test creates its user with `create_user`, which leaves no profile
row; profile rows come from the migration and from write paths. That test file was 81 passed and
green on D3.1a before the fix.

Fixed on `d3.1a-rebased`: `courses_learnerprofile` joins the non-activity tables beside
testimonials, staying outside the content allowlist so the import still proves every profile row
byte-unchanged. A test seeds the row the migration leaves.

## Instance 2: the account inventory stops naming the fields the operator must decide

`accounts/identity_inventory.py:155` walks `User._meta.get_fields()`.

| | field count | moved fields missing |
|---|---|---|
| main | 29 | none |
| D3.1d | 17 | all twelve |

Nothing raises; the report simply gets shorter. That inventory is what the account-reconciliation
runbook has an operator read before building the reviewed mapping, and the merge still demands an
explicit source or survivor decision for ten of the twelve, raising `field_decision_required`. So
the operator would be asked to decide fields the inventory no longer mentions.

It stayed green because the covering test asserts on relations, routes and a checksum length,
never on the field list.

Fixed on `d3.1d-rebased`: the enumerator walks the durable account rather than one model, the user
model plus `accounts_ext.IdentityState` and `courses.LearnerProfile`, minus each extension's join
column and surrogate key. Output is field-for-field identical to main. The new test was verified to
fail without the fix.

## The open decision: the expand window is broken in both directions

Not fixed, because fixing it is a material scope change that contradicts D3.1a's own charter.

One `toggle_dark_mode` POST, identical data:

| branch | `accounts_customuser.dark_mode` | `courses_learnerprofile.dark_mode` |
|---|---|---|
| main | True | no table |
| D3.1a | True | False, stale |
| D3.1b | False, stale | True |

D3.1a copies the data and leaves writers on the user column. D3.1b moves writers wholesale to the
profile. No branch keeps both locations correct, so the two images disagree.

Within any single deployed state nothing reads the stale side, and D3.1b pins that with an AST and
regex check over literal reads. Migration 0017's reverse restores the user columns, so a rollback
THROUGH the migration is safe. The exposure is narrower than it first looks and real: rolling back
CODE while leaving the migration applied loses writes made since the deploy.

The decision is whether that matters. Making both images agree means dual-write signals across
roughly fifteen write paths, which contradicts D3.1a's stated charter of pure additions with no
reader switched, and playbook P7's three-step shape. The alternative is to accept it and state that
a rollback of D3.1b must roll back the migration too, which turns an implicit property into a
documented deploy constraint.

## Three smaller things left for the owner

`_docs/architecture/single-durable-account.md` states that no learner profile is introduced. D3.1a
introduces one, and the whole stack touches zero documentation files.

`ACCOUNT_RELATIONS` does not list `courses.LearnerProfile.user` or `accounts_ext.IdentityState.user`,
so reconciliation evidence does not count or checksum the two new per-account tables. Adding them
changes a documented count and an assertion, so it was not taken unilaterally.

The five branches are rebased onto `37874818`, and main is now roughly twenty-six commits ahead at
`84c68dba`. The 29 `review_import` failures on the stack are from that stale base, not from D3.1:
they reproduce identically at the merge base and pass on current main. The stack needs re-rebasing
before its numbers mean anything.
