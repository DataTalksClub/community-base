# Critique

## Reflection

- Every seed acceptance criterion maps to sections 3-9 of `guideline.md`.
- All 66 existing issues remain represented by package work, donor/site adoption, Relay work, or
  post-adoption cleanup; none are silently skipped.
- The plan preserves D1-D14 and every quality-gate category.
- Package tests are explicitly separated from real Relay, migration-rehearsal, deployment, freeze,
  and production evidence.
- Kept-label migration risk is addressed by prohibiting tags while baselines are provisional.
- New-label migrations remain locally finalizable and later use site-side data-copy migrations.
- Oversized donor lifts are split, requiring tracker suffix support first.
- The missing campaign/contact package interfaces are called out as new scope rather than assumed.
- Rollback remains the existing tag-pin/site workflow; no new destructive production procedure is
  introduced.

## Rejected alternatives

- Keep the current interleaved phase order: rejected because it conflicts with the owner’s new
  package-first direction and contains dependency contradictions.
- Mark site issues skipped: rejected because it falsifies readiness and the tracker treats skipped
  dependencies as satisfied.
- Reimplement Relay inside this package: rejected because it contradicts D3/D4.
- Tag provisional kept-label migrations: rejected because later donor reconciliation would require
  editing a shipped migration, violating the append-only rule.
- Claim donor compatibility from synthetic snapshots alone: rejected because quality gates require
  actual donor state and development-copy rehearsal.
- Keep C4.1 blocked on A4.1 for all work: rejected because package behavior can be adapted locally;
  only compatibility acceptance requires the prepared donor.
- Put all site adoption into one release/freeze: rejected because it magnifies migration and
  rollback risk and violates the one-issue/one-PR process.

## Approved decisions

1. The package-first execution policy and plan-correction PR are the next work.
2. Use one `v0.6.0` adoption-candidate domain release instead of publishing provisional
   `v0.4.0` and `v0.5.0` tags.
3. Preserve `replaces` markers after tagging, resolving P4 in favor of append-only
   migrations.

The owner explicitly approved these decisions on 2026-09-05.

## Human grilling

The approval request isolated the three subjective tradeoffs above. The owner approved them
without changes.

## Accepted risks

- Package-first scheduling delays the start of D13's four-week production evidence window.
- Domain work remains untagged while kept-label migrations are provisional.
- Real Relay and donor compatibility may reveal changes after package-local behavior is complete.
