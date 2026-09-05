# Package-first direction synthesis

## Conclusions

- [HUMAN] Shared functionality should be implemented inside `community-base` first so later site
  porting is easier.
- [FACT execution-plan] The current plan interleaves package construction, Relay changes, donor
  preparation, site adoption, freezes, and production evidence.
- [INFERENCE execution-plan,target-architecture] “Package-first” must mean package behavior and
  integration contracts first, not moving Relay server responsibilities or site-specific apps into
  the package.
- [INFERENCE execution-plan,quality-gates] Package capability acceptance and external adoption
  acceptance need separate issues and evidence. A fake Relay or synthetic migration snapshot cannot
  prove a real Relay endpoint or site database migration.
- [INFERENCE owner-decisions,target-architecture] Kept-label apps can be developed against their
  intended shared schema before donor preparation, but their initial migrations remain provisional
  and no tag may contain them until exact donor compatibility is proven.
- [INFERENCE execution-plan,target-architecture] Foundation releases through `v0.3.0` can remain
  independent. Domain releases `v0.4.0` and `v0.5.0` should become compatibility checkpoints, with
  one `v0.6.0` adoption-candidate release after all kept-label migrations are finalized.

## Immediate defects in the current plan

- [FACT execution-plan] C0.3 needs the API registry from C0.4, while C0.4 incorrectly verifies a
  C0.3-owned settings endpoint.
- [FACT execution-plan] C2.1 accepts re-homed jobs/mail pages without depending on their package
  implementations, and C2.3 includes Studio pages without depending on the Studio shell.
- [FACT execution-plan] C3.1 behavior can be built locally, but its donor-compatible migration must
  wait for AISL user-field contraction.
- [FACT execution-plan] C4.1 makes site seam work a prerequisite to all package events behavior;
  local package adaptation and later donor compatibility should be separate.
- [FACT execution-plan] Phase 6 promises package Relay-proxied campaign pages without a package
  issue that builds them.
- [FACT execution-plan] The tracker does not support the letter-suffixed issue IDs prescribed by
  the process and mines dependencies from explanatory prose.
- [INFERENCE owner-decisions,target-architecture] P4’s instruction to remove `replaces` after a
  tagged deploy conflicts with the append-only tagged-migration rule; the marker should remain until
  a separately approved migration policy says otherwise.

## Boundary of package-first completion

- [INFERENCE target-architecture] Complete here: shared models and services, backends and clients,
  hooks/signals, public and Studio views, API routes, management commands, templates/static assets,
  migrations, synthetic adapters, donor fixtures, test doubles, and documentation.
- [INFERENCE owner-decisions,quality-gates] Still external: donor schema contraction and seam work,
  exact migration equivalence, development-copy rehearsals, site route/import/template replacement,
  Relay server changes, real sandbox/production conformance, deployments, freezes, and D13 evidence.

- [OPEN] Record the current thesis, evidence, and dissent.
