# Plan index

Seven phases. Each phase file lists its issues with goal, reading list, steps, verification and
done criteria. Issue ids are `<letter><phase>.<n>`: `C` package (community-base), `A` AISL,
`D` DTC, `R` Relay. A lowercase suffix identifies a split issue, for example `C2.3a`.

The current campaign is package-first: implement and verify shared behavior in `community-base`
before either site adopts it. Package capability does not complete a phase; external compatibility,
site adoption and deployed exit criteria still determine phase completion. Use
`uv run python scripts/plan.py next --repo community-base` during this campaign.

| Phase | File | Goal | Freeze | Depends on | Status |
|---|---|---|---|---|---|
| 0 | `phase-0.md` | Package repository, kernel, config, API layer; both sites consume config through the package | none | | not started |
| 1 | `phase-1.md` | Jobs and mail apps with `relay`, `django_q` and `ses_local` backends; Relay production; DTC runs on Relay; AISL adopts the apps on local backends | DTC one weekend | 0 | not started |
| 2 | `phase-2.md` | Shared Studio shell with registered sections, users management, content sync engine | none | 0, 1 | not started |
| 3 | `phase-3.md` | Shared accounts and auth, onboarding flows, Slack community, notifications, comments, voting | AISL one weekend, DTC one weekend | 2 | not started |
| 4 | `phase-4.md` | Shared events with series and registration on both sites | AISL one weekend, DTC one weekend | 3 | not started |
| 5 | `phase-5.md` | Shared curriculum (cohort and self-paced) and coursework | AISL one weekend, DTC one weekend | 4 | not started |
| 6 | `phase-6.md` | AISL cutover to Relay for mail, jobs, campaigns, contacts and email-log history | AISL one weekend | 1 proven per D13, 5 | not started |

Order during the current campaign: ready package issues first. After the adoption-ready `v0.6.0`
release, use dependency order across Relay, DTC and AISL. Relay issues in Phase 1 have the longest
external lead time and may be opened independently.

Package readiness milestones:

| Milestone | Package evidence | Adoption evidence |
|---|---|---|
| Capability ready | tests, fresh migrations, installed wheel, synthetic adapters and fixture contracts | not required yet |
| Adoption compatible | capability evidence remains green | donor inventories, migration equivalence, real service conformance and development-copy rehearsal |
| Phase done | all package and external issues done | site CI, deploy and phase exit criteria pass |

Sizing guidance: an issue is meant to be one pull request that one executor completes in one to
three working sessions. If an issue turns out larger, split it and add the split to the phase
file in the same pull request.

Status values: not started, in progress, blocked (with the blocking issue id), done. Update this
table when a phase changes state.
