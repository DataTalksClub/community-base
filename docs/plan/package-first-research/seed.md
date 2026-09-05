# Package-first community-base unification

## Problem

The existing seven-phase plan interleaves shared-package construction with adoption work in AI
Shipping Labs, DataTalks.Club, and Relay. The owner wants to change execution direction so that all
functionality that can live in `community-base` is implemented and verified there first. This
should make later website porting easier and reduce repeated cross-repository coordination.

The immediate symptom is that C0.3 requires admin API endpoints and scope enforcement supplied by
C0.4 even though C0.3 appears first and neither declares the other as a dependency.

## Desired behavior

Produce a clear, executable package-first implementation plan. It should reorder or split the
existing plan so shared apps, extension seams, migrations, tests, documentation, and package
releases are built in `community-base` before site adoption work, except where donor preparation,
site database compatibility, Relay production evidence, or freeze operations are inherently
required first.

The plan must be saved durably and be usable as the authoritative sequence for subsequent work.

## Acceptance criteria

- [ ] Every existing issue and phase is accounted for as package-first, site prerequisite,
  adoption, operational evidence, or deferred cleanup.
- [ ] Dependency/order contradictions such as C0.3 and C0.4 are resolved explicitly.
- [ ] Each milestone names concrete issues/PRs, dependencies, release points, and verification.
- [ ] Package functionality has test-project substitutes, fixtures, contracts, or donor snapshots
  sufficient to verify it without pretending site integration has passed.
- [ ] Model labels, migration compatibility, append-only migration rules, and freeze boundaries are
  preserved.
- [ ] Relay/D13 constraints and production-only proof remain explicit and cannot be bypassed.
- [ ] The plan distinguishes work possible entirely in `community-base` from work requiring donor
  seams, site data, deployed environments, or owner action.
- [ ] Existing decisions D1-D14 and quality-gate stop conditions remain unchanged.
- [ ] The saved plan includes risks, rejected alternatives, and any genuine owner decisions still
  required.

## Constraints

- Follow `/home/alexey/git/community-base/AGENTS.md` and repository process documents.
- Use `uv`; never use `pip`.
- One pull request per issue, with dependency-aware status tracking and every prescribed gate.
- Keep package code free of site imports and arbitrary Django settings access.
- Preserve existing Django app labels and migration histories where decisions require them.
- Never use production data or credentials; migration rehearsals use development copies only.
- Do not claim site adoption or production proof from package-only tests.
- Continue making small, coherent commits during implementation.

## Current understanding

- C0.1 and C0.2 are merged, released/tracked as required, and marked done.
- C0.3 and C0.4 are currently dependency-ready.
- The present plan has package issues in every phase but intersperses site seam-cutting and
  adoption work between package releases.
- Some lifts cannot be safely completed package-first because P4 requires donor seams to be empty
  and migration names/current model state to be captured from AISL.
- D13 prevents AISL Relay integration until DTC has run Relay in production for four consecutive
  incident-free weeks with a green status contract.
- The exact boundary between package-first implementation, donor preparation, and adoption needs
  independent architecture review.

## Comparison sources

- `/home/alexey/git/community-base/docs/` and current package code.
- `/home/alexey/git/ai-shipping-labs` donor code and process documents.
- `/home/alexey/git/dtc-website` donor/specification code and process documents.
- `/home/alexey/git/relay` transport contracts and process documents.

## Non-goals

- Reopening owner decisions D1-D14.
- Weakening or skipping quality gates, freezes, migration rehearsals, or production proof.
- Performing site adoption, production access, or deployment during the planning pass.
- Treating package unit tests as proof that a site migration or integration is safe.
