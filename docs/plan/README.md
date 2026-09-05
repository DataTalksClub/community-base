# Plan index

Seven phases. Each phase file lists its issues with goal, reading list, steps, verification and
done criteria. Issue ids are `<letter><phase>.<n>`: `C` package (community-base), `A` AISL,
`D` DTC, `R` Relay.

| Phase | File | Goal | Freeze | Depends on | Status |
|---|---|---|---|---|---|
| 0 | `phase-0.md` | Package repository, kernel, config, API layer; both sites consume config through the package | none | | not started |
| 1 | `phase-1.md` | Jobs and mail apps with `relay`, `django_q` and `ses_local` backends; Relay production; DTC runs on Relay; AISL adopts the apps on local backends | DTC one weekend | 0 | not started |
| 2 | `phase-2.md` | Shared Studio shell with registered sections, users management, content sync engine | none | 0, 1 | not started |
| 3 | `phase-3.md` | Shared accounts and auth, onboarding flows, Slack community, notifications, comments, voting | AISL one weekend, DTC one weekend | 2 | not started |
| 4 | `phase-4.md` | Shared events with series and registration on both sites | AISL one weekend, DTC one weekend | 3 | not started |
| 5 | `phase-5.md` | Shared curriculum (cohort and self-paced) and coursework | AISL one weekend, DTC one weekend | 4 | not started |
| 6 | `phase-6.md` | AISL cutover to Relay for mail, jobs, campaigns, contacts and email-log history | AISL one weekend | 1 proven per D13, 5 | not started |

Order inside a phase: package issues first, then Relay, then DTC, then AISL, unless an issue's
"Depends on" says otherwise. Relay issues in Phase 1 have the longest lead time and should be
opened on day one.

Sizing guidance: an issue is meant to be one pull request that one executor completes in one to
three working sessions. If an issue turns out larger, split it and add the split to the phase
file in the same pull request.

Status values: not started, in progress, blocked (with the blocking issue id), done. Update this
table when a phase changes state.
