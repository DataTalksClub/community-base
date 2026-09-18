# D3.1 stack review, 2026-09-18

Independent review of the five rebased D3.1 branches in DataTalksClub/website before landing.
Commits: `d3.1a-rebased@1b17ec51`, `d3.1b-rebased@149f0888`, `d3.1c-rebased@208ef740`,
`d3.1d-rebased@1798e25d`, `d3.1e-rebased@eec8e350`. Shared base `3787481817a5`, strictly linear.

Verdict: do not land. Two confirmed silent data-loss defects, both in the expand window, plus one
authorization consequence. The stack is repairable and parts of it are good; nothing here argues
for discarding it.

## Findings

| # | Severity | Evidence | Finding |
|---|---|---|---|
| 1 | Critical, silent data loss | confirmed | The expand phase does not dual-write. Every value written to the twelve moved fields between the D3.1a deploy and the D3.1b/c deploy is discarded. |
| 2 | Critical, silent wrong authorization | confirmed | `identity_state` is dual-written on no path at all, so an account absorbed or quarantined during the window reads back as `legacy`, which is eligible. |
| 3 | High | confirmed | `test_support/factories/current_domain.py` still resolves three moved models under the `accounts` label. Five tests fail from D3.1a and are still failing at D3.1e. |
| 4 | High | confirmed | No standalone back-copy and no rollback plan. For the two identity fields there is no way to back-copy without destroying the expand. |
| 5 | High | plausible | The account-merge apply lost its compare-and-swap: an `exists()` check followed by an unchecked `update()`. A concurrent write yields a zero-row update and a merge reported as successful. |
| 6 | Medium | confirmed | Both new relations on `User` were added without touching `ACCOUNT_RELATIONS`, and the ratchet asserts a count against the hand-written list rather than walking `User._meta.related_objects`. |
| 7 | Medium | confirmed | A D3.1e rename leaked into the D3.1c commit, so the type gate is red on D3.1c and D3.1d. |
| 8 | Medium | confirmed | The stack is 50 commits behind main and inherits a migration-stability failure main has already fixed. |
| 9 | Low | deviates | D3.1e does not use `RenameModel`. It rewrites six applied migration files. The reasoning is sound and is recorded only in a docstring. |

## 1. The expand phase never dual-writes

`courses.0017_learnerprofile_data` copies one row per user at D3.1a migrate time and skips users
that already have a row. D3.1a switches no reader and no writer. D3.1b and D3.1c add no migration,
and there is no post-save receiver on the courses side. Between the two deploys every write lands
in `accounts_customuser` only.

Reproduced on `d3.1a-rebased@1b17ec51`:

```
profile row after create: None
user columns after save: Alexey G True Germany
profile row after save : None
```

After D3.1b those accounts read `profile_field_default(...)`. After D3.1d the columns are dropped.

The team already understood the failure mode: the D3.1b guard carries a reviewed exemption saying
that splitting reads from writes across two deploys would let an operator merge write a decided
field to the column nobody reads. The reasoning was applied to the merge script and not to the
deploy boundary between the branches.

## 2. `identity_state` drifts on every write path

`accounts_ext/signals.py` syncs only `normalized_email`. Reproduced on the same commit:

```
after create:             user.identity_state= legacy      row= ('legacy', 'drift@example.com')
after queryset .update(): user.identity_state= active      row= ('legacy', 'drift@example.com')
after absorb .update():   user.identity_state= absorbed    row= ('legacy', 'drift@example.com')
after full save():        user.identity_state= quarantined row= ('legacy', 'drift@example.com')
```

Live writers in the window include `accounts/auth.py::_activate_verified_identity`, a queryset
update that bypasses the receiver and runs on every first verified social sign-in.

After D3.1c every reader goes through `identity_state_of(user)`. An absorbed account reads
`legacy`, so `identity_state_eligible()` is true, the middleware ABSORBED redirect never fires and
the account can sign in again on its own id. A quarantined account reads `legacy` and
`can_login_as` stops refusing it.

The signals docstring notes that `queryset.update()` and `bulk_update()` bypass the receiver
"unchanged". That framing is the error: before the move those calls wrote the authoritative
column, and after it they write a column nobody reads. The code shape is unchanged; the behaviour
is not.

## What was checked and is fine

The reader-switch guard in D3.1b pins the rule rather than a file list: an AST walk over every
tracked production module rejecting a moved-field read off a user-ish object, plus a template scan
that is an allowlist of holders rather than a denylist of names, chosen because the first reader it
caught rendered the fields off a context variable named `public_profile`. A second test fails if an
exemption outlives its module.

Migrations: `check` and `makemigrations --check` clean on all five branches; fresh-database
`migrate` applies on a, d and e; reverse and re-apply verified. No step depends on a later one, no
cycle, no numbering collision with main. All seven new migrations import only `django` and `uuid`
and none serialises a callable through a live module. The four state-only model moves are genuinely
state-only with `db_table` pinned. The constraint move drops the index from the user table and
recreates it under the same name on `IdentityState`, ordered by an explicit dependency.

DTC has no GDPR export and no account-deactivation service, so of P7's three named enumerating
services only account merge exists here. `development_content_import` is the one enumerator that
cannot go quietly no-op, because it walks the live schema rather than the model graph.

## Edges of this review

No full suite on any branch, and no `scripts/ci.py` run, so no count here is comparable to a
baseline. No Playwright and no screenshots, though D3.1b changes the shell head and the dark-mode
toggle. No development-copy rehearsal, so the Postgres behaviour of `AlterModelTable` on the two
through tables and the column rename in `0009` are untested against a real dump. Finding 5 is not
reproduced. Branches b and c were not applied to a fresh database. The roughly 200 rewritten test
files were not audited for assertions weakened rather than moved, and the D3.1b commit body itself
admits fixing three defects in ported assertions. The type gate was run on one file, not the full
set. AISL was not reviewed.
