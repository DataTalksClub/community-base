# Plan status

Single source of truth for progress across all four repositories. Generated rows come from
`docs/plan/phase-*.md`; the `Status` and `Link` columns are edited by hand (or with
`python scripts/plan.py`). Allowed statuses: `todo`, `in-progress`, `blocked`, `review`, `done`, `skipped`.

Update the row for an issue in the same pull request that starts it (`in-progress`, with the
pull request link) and in the pull request that closes it (`done`). When the issue lives in
another repository, open a small pull request here that only changes this file.

Run `python scripts/plan.py summary` for totals and `python scripts/plan.py next` for the
issues that can start now.

## Phase 0

| Issue | Repository | Title | Depends on | Freeze | Status | Link |
|---|---|---|---|---|---|---|
| `C0.1` | community-base | Create the package repository skeleton |  | no | done | https://github.com/DataTalksClub/community-base/pull/6 |
| `C0.2` | community-base | Kernel: configuration dictionary, hooks, access policy, staff decorators | C0.1 | no | done | https://github.com/DataTalksClub/community-base/pull/8 |
| `C0.3` | community-base | Config app: registry, storage, cache, Studio page, import and export | C0.4 | no | done | https://github.com/DataTalksClub/community-base/pull/13 |
| `C0.4` | community-base | API app: keys with scopes, bearer auth, OpenAPI, route registry | C0.2 | no | done | https://github.com/DataTalksClub/community-base/pull/11 |
| `C0.5` | community-base | First release | C0.2, C0.3, C0.4 | no | done | https://github.com/DataTalksClub/community-base/releases/tag/v0.1.0 |
| `C0.6` | community-base | Owner-scoped exception to D1 for a required, always-latest cross-repo check |  | no | done | https://github.com/DataTalksClub/community-base/pull/277 (D15 recorded in docs/01-decisions.md, cross-repo-check.yml on push and pull_request, playbook P16 and AGENTS.md narrowed; branch-protection enrollment stays an owner repository setting) |
| `A0.1` | AI-Shipping-Labs/website | Add the package dependency and the local link targets | C2.4 | no | done | https://github.com/AI-Shipping-Labs/website/commit/2d567da34b493eb9e6901540c1bf5a0a5d1913d7 |
| `A0.2` | AI-Shipping-Labs/website | Replace the settings framework with the package config app | A0.1 | no | done | https://github.com/AI-Shipping-Labs/website/issues/1584 (closed 2026-09-13 with PM acceptance; Deploy Dev 34699777409 green at head 1638e419) |
| `A0.3` | AI-Shipping-Labs/website | Access policy hook | A0.1 | no | done | https://github.com/AI-Shipping-Labs/website/issues/1582 |
| `D0.1` | DataTalksClub/website | Add the package and replace the settings frameworks | D0.1d | no | todo | https://github.com/DataTalksClub/website/issues/407 |
| `D0.1a` | DataTalksClub/website | Install the released kernel and local development tools | C2.4 | no | done | https://github.com/DataTalksClub/website/commit/f8f68c46e84353f59229cbdc113a85a43f5ca246 |
| `D0.1b` | DataTalksClub/website | Inventory settings contracts and prove package parity | D0.1a | no | done | https://github.com/DataTalksClub/website/issues/355 |
| `D0.1c` | DataTalksClub/website | Copy settings and switch readers and writers | D0.1b | no | blocked | https://github.com/DataTalksClub/website/issues/408 — merged as website 3fb9db07; dev deploy waits on a fully green main CI run (website#345: the 2026-09-16 scheduled full regression is red on django, migrations, quality and playwright); the aws-infra#49 worker self-check grant is effective since 2026-09-13 (protected apply fec7f1fb green), and aws-infra#56 (terraform-plan identity trust; needs human sandbox-account IAM access) blocks only future aws-infra applies, not this deploy |
| `D0.1d` | DataTalksClub/website | Retire old settings storage after the rollback window | D0.1c | no | todo | https://github.com/DataTalksClub/website/issues/385 |
| `D0.2` | DataTalksClub/website | Site CI guard and pin bump workflow | D0.1a | no | done | https://github.com/DataTalksClub/website/issues/354 |

## Phase 1

| Issue | Repository | Title | Depends on | Freeze | Status | Link |
|---|---|---|---|---|---|---|
| `R1.1` | DataTalksClub/relay | Relay production environment |  | no | done | https://github.com/DataTalksClub/relay/pull/15 |
| `R1.2` | DataTalksClub/relay | Webhook task hardening |  | no | done | https://github.com/DataTalksClub/relay/pull/9 |
| `R1.3` | DataTalksClub/relay | Template catalog: versions, preview, test send, typed context |  | no | done | https://github.com/DataTalksClub/relay/pull/16 |
| `R1.4` | DataTalksClub/relay | Client callbacks for delivery and engagement events | R1.2 | no | done | https://github.com/DataTalksClub/relay/pull/20 |
| `R1.5` | DataTalksClub/relay | Preference categories and double opt-in |  | no | done | https://github.com/DataTalksClub/relay/pull/19 |
| `C1.1a` | community-base | Durable jobs core and local backends | C0.5 | no | done | https://github.com/DataTalksClub/community-base/pull/19 |
| `C1.1b` | community-base | Relay jobs client and contract tests | C1.1a | no | done | https://github.com/DataTalksClub/community-base/pull/22 |
| `C1.2a` | community-base | Durable mail core, memory backend, and local surfaces | C1.1a | no | done | https://github.com/DataTalksClub/community-base/pull/26 |
| `C1.2b` | community-base | Relay mail, catalog, callback, and reconciliation clients | C1.1b, C1.2a | no | done | https://github.com/DataTalksClub/community-base/pull/29 |
| `C1.3` | community-base | ses_local backend (transitional, for AISL) | C1.2a | no | done | https://github.com/DataTalksClub/community-base/pull/32 |
| `C1.4` | community-base | Test doubles exported for sites | C1.1a, C1.1b, C1.2a, C1.2b | no | done | https://github.com/DataTalksClub/community-base/pull/35 |
| `C1.5` | community-base | Release 0.2.0 | C1.1a, C1.1b, C1.2a, C1.2b, C1.3, C1.4 | no | done | https://github.com/DataTalksClub/community-base/releases/tag/v0.2.0 |
| `D1.1` | DataTalksClub/website | Replace DTC jobs with the package jobs app (relay backend) | C1.5, R1.1, R1.2 | no | done | https://github.com/DataTalksClub/website/issues/350 |
| `D1.2a` | DataTalksClub/website | Install the mail app, move PendingUnsubscribe, commit the purpose templates | D1.1, R1.3, R1.4, R1.5 | no | done | https://github.com/DataTalksClub/website/issues/368 |
| `D1.2b` | DataTalksClub/website | Send through the package mail app with the outbox idempotency keys | D1.2a | no | done | https://github.com/DataTalksClub/website/issues/370 |
| `D1.2ca` | DataTalksClub/website | Send the remaining datamailer mail through the package mail app and retire the datamailer client | D1.2b | no | blocked | https://github.com/DataTalksClub/website/issues/409 — website#372 branch issue-372 gates green; dev deploy waits on the same fully green main CI run as D0.1c (website#345: 2026-09-16 scheduled full regression red); the worker self-check grant is effective since 2026-09-13; aws-infra#56 (human sandbox-account IAM fix) blocks only future aws-infra applies, not this deploy |
| `D1.2cb` | DataTalksClub/website | Retire email_app and the data app, move the bridge settings | D1.2ca | no | todo | https://github.com/DataTalksClub/website/issues/372 (D1.2c umbrella spans D1.2ca and D1.2cb) |
| `D1.3` | DataTalksClub/website | Freeze weekend: DTC on Relay in production | D1.1, D1.2cb | yes | todo | https://github.com/DataTalksClub/website/issues/410 |
| `A1.1` | AI-Shipping-Labs/website | Adopt the package jobs app on the django_q backend | C1.5 | no | done | https://github.com/AI-Shipping-Labs/website/commit/b8d0eb8096668c4b1478840dd3e1c5c4051834c6 |
| `A1.2` | AI-Shipping-Labs/website | Adopt the package mail app on the ses_local backend | C1.5, A1.1 | no | in-progress | https://github.com/AI-Shipping-Labs/website/issues/1610 (closed 2026-09-12 with dev deploy green; canonical final check unmet, remainder filed as https://github.com/AI-Shipping-Labs/website/issues/1629) |

## Phase 2

| Issue | Repository | Title | Depends on | Freeze | Status | Link |
|---|---|---|---|---|---|---|
| `C2.1a` | community-base | Studio shell, registry and security | C1.5 | no | done | https://github.com/DataTalksClub/community-base/pull/43 |
| `C2.1b` | community-base | Integrate existing package Studio screens | C2.1a | no | done | https://github.com/DataTalksClub/community-base/pull/46 |
| `C2.2` | community-base | Users management in Studio | C2.1b | no | done | https://github.com/DataTalksClub/community-base/pull/49 |
| `C2.3` | community-base | Content sync engine | C1.5, C2.1a | no | done | https://github.com/DataTalksClub/community-base/pull/52 |
| `C2.4` | community-base | Release 0.3.0 | C2.1b, C2.2, C2.3 | no | done | https://github.com/DataTalksClub/community-base/releases/tag/v0.3.0 |
| `A2.1` | AI-Shipping-Labs/website | Adopt the Studio shell | C2.4 | no | blocked | https://github.com/AI-Shipping-Labs/website/issues/1615 — registration half done and green on branch `a2.1-studio-shell` (every AISL Studio route now has exactly one disposition, down from 272 unclaimed). The shell cutover is blocked on C7.13 (package apps claim Studio routes the site never mounts, no site-side remedy) and C7.14 (the shared shell renders about 51 destinations always-expanded where the donor collapses to 8 headers) |
| `A2.2` | AI-Shipping-Labs/website | Users pages from the package | A2.1 | no | todo | https://github.com/AI-Shipping-Labs/website/issues/1691 |
| `A2.3` | AI-Shipping-Labs/website | Content sync through the package engine | C2.4 | no | in-progress | https://github.com/AI-Shipping-Labs/website/issues/1617 |
| `D2.1` | DataTalksClub/website | Mount the Studio shell and re-home DTC Studio pages | C2.4 | no | in-progress | https://github.com/DataTalksClub/website/issues/377 |
| `D2.2a` | DataTalksClub/website | Content sync adoption: articles and people through the package engine | C2.4 | no | in-progress | https://github.com/DataTalksClub/website/issues/379 (engineering, independent tester PASS and PM acceptance recorded on the issue; merged to website main as 60a25617 + f2b32dd0; dev deploy pending the website#345 / aws-infra#56 blockers) |
| `D2.2b` | DataTalksClub/website | Content sync adoption: podcast and books | D2.2a | no | done | https://github.com/DataTalksClub/website/issues/382 (closed 2026-09-15 with PM acceptance; merged as website d7e53f5f; dev deploy waiting on a green main CI run — the red quality job is a pre-existing lint regression, website#405) |
| `D2.2c` | DataTalksClub/website | Content sync adoption: docs, FAQ and podwiki, retire the staged pipeline | D2.2b | no | in-progress | https://github.com/DataTalksClub/website/issues/384 (started 2026-09-15 in website worktree `issue-384` off d7e53f5f) |

## Phase 3

| Issue | Repository | Title | Depends on | Freeze | Status | Link |
|---|---|---|---|---|---|---|
| `C3.1a` | community-base | Target accounts schema | C2.4 | no | done | https://github.com/DataTalksClub/community-base/pull/60 |
| `C3.1b` | community-base | Authentication and public account entry points | C3.1a | no | done | https://github.com/DataTalksClub/community-base/pull/63 |
| `C3.1c` | community-base | Account domain services and mail preferences | C3.1b | no | done | https://github.com/DataTalksClub/community-base/pull/68 |
| `C3.1d` | community-base | Account pages and self API | C3.1c | no | done | https://github.com/DataTalksClub/community-base/pull/71 |
| `C3.1e` | community-base | Studio account operations and documentation | C3.1d | no | done | https://github.com/DataTalksClub/community-base/pull/74 |
| `C3.2` | community-base | Questionnaires | C3.1e | no | done | https://github.com/DataTalksClub/community-base/pull/77 |
| `C3.3` | community-base | Onboarding flows | C3.1e, C3.2 | no | done | https://github.com/DataTalksClub/community-base/pull/80 |
| `C3.4` | community-base | Community (Slack) | C3.1e | no | done | https://github.com/DataTalksClub/community-base/pull/83 |
| `C3.5a` | community-base | Notifications | C3.1e | no | done | https://github.com/DataTalksClub/community-base/pull/87 |
| `C3.5b` | community-base | Comments | C3.1e | no | done | https://github.com/DataTalksClub/community-base/pull/90 |
| `C3.5c` | community-base | Voting | C3.1e | no | done | https://github.com/DataTalksClub/community-base/pull/93 |
| `C3.6` | community-base | Identity and community capability checkpoint | C3.1e, C3.2, C3.3, C3.4, C3.5a, C3.5b, C3.5c | no | done | https://github.com/DataTalksClub/community-base/pull/96 |
| `C3.7` | community-base | Identity donor compatibility checkpoint | C3.6, A3.2, D3.1e | no | todo | https://github.com/DataTalksClub/community-base/issues/270 |
| `A3.1` | AI-Shipping-Labs/website | Move tier and Stripe fields off the user model | C5.2a | no | in-progress | https://github.com/AI-Shipping-Labs/website/issues/1579 accepted at website 0b1c7eff, dev deploy green; human checks AC13/AC14 pending |
| `A3.2` | AI-Shipping-Labs/website | Extension models for the remaining site-only user fields | A3.1 | no | todo | https://github.com/AI-Shipping-Labs/website/issues/1692 |
| `A3.3` | AI-Shipping-Labs/website | Freeze weekend: adopt shared accounts, questionnaires, community, notifications, comments, voting | C5.3, C3.7, A3.2 | yes | todo | https://github.com/AI-Shipping-Labs/website/issues/1693 |
| `D3.1a` | DataTalksClub/website | Additive extension schema (courses.LearnerProfile + accounts_ext) | C5.2a | no | in-progress | https://github.com/DataTalksClub/website/issues/390 — engineer lane claimed 2026-09-16 evening (worktree issue-390 off d7b3f10a; no pull request yet) |
| `D3.1b` | DataTalksClub/website | Switch course-platform readers to courses.LearnerProfile | D3.1a | no | todo | https://github.com/DataTalksClub/website/issues/391 |
| `D3.1c` | DataTalksClub/website | Switch identity-window readers to accounts_ext.IdentityState | D3.1b | no | todo | https://github.com/DataTalksClub/website/issues/392 |
| `D3.1d` | DataTalksClub/website | Remove the twelve moved fields from CustomUser (contract) | D3.1c | no | todo | https://github.com/DataTalksClub/website/issues/393 |
| `D3.1e` | DataTalksClub/website | Rename CustomUser to User (RenameModel, AUTH_USER_MODEL) | D3.1d | no | todo | https://github.com/DataTalksClub/website/issues/394 |
| `D3.1f` | DataTalksClub/website | Add the AISL-origin reconciliation fields (schema only) | D3.1d | no | skipped | https://github.com/DataTalksClub/website/issues/395 (dropped by owner decision 2026-09-15: schema-only prep with zero readers; D3.2 owns the fields when scoped) |
| `D3.2` | DataTalksClub/website | Freeze weekend: adopt shared accounts and onboarding | C5.3, C3.7, D3.1e | yes | todo | https://github.com/DataTalksClub/website/issues/411 |

## Phase 4

| Issue | Repository | Title | Depends on | Freeze | Status | Link |
|---|---|---|---|---|---|---|
| `A4.1` | AI-Shipping-Labs/website | Cut the seams in AISL events | C5.2a, A3.2 | no | todo | https://github.com/AI-Shipping-Labs/website/issues/1694 |
| `C4.1a` | community-base | Events models and domain services | C3.6 | no | done | https://github.com/DataTalksClub/community-base/pull/100 |
| `C4.1b` | community-base | Registration, reminders and feedback | C4.1a | no | done | https://github.com/DataTalksClub/community-base/pull/103 |
| `C4.1c` | community-base | Event integrations and job handlers | C4.1b | no | done | https://github.com/DataTalksClub/community-base/pull/107 |
| `C4.1d` | community-base | Event pages, Studio and APIs | C4.1c | no | done | https://github.com/DataTalksClub/community-base/pull/110 |
| `C4.1e` | community-base | Remove event aliases and legacy path compatibility | C4.1d | no | done | https://github.com/DataTalksClub/community-base/pull/264 |
| `C4.2` | community-base | Events capability checkpoint | C4.1d, C4.1e | no | done | https://github.com/DataTalksClub/community-base/pull/113 |
| `C4.3` | community-base | Events donor compatibility checkpoint | C4.2, A4.1 | no | todo | https://github.com/DataTalksClub/community-base/issues/271 |
| `A4.2` | AI-Shipping-Labs/website | Freeze weekend: adopt shared events | C5.3, C4.3, A4.1 | yes | todo | https://github.com/AI-Shipping-Labs/website/issues/1695 |
| `D4.1` | DataTalksClub/website | Database-authored events in DTC | C5.3 | no | todo | https://github.com/DataTalksClub/website/issues/412 |
| `D4.2` | DataTalksClub/website | Freeze weekend: DTC events cutover | D4.1 | yes | todo | https://github.com/DataTalksClub/website/issues/413 |

## Phase 5

| Issue | Repository | Title | Depends on | Freeze | Status | Link |
|---|---|---|---|---|---|---|
| `C5.1a` | community-base | Curriculum models and access | C4.2 | no | done | https://github.com/DataTalksClub/community-base/pull/117 |
| `C5.1b` | community-base | Curriculum import | C5.1a | no | done | https://github.com/DataTalksClub/community-base/pull/119 |
| `C5.1c` | community-base | Curriculum public pages and member APIs | C5.1b | no | done | https://github.com/DataTalksClub/community-base/pull/121 |
| `C5.1d` | community-base | Curriculum Studio and staff APIs | C5.1c | no | done | https://github.com/DataTalksClub/community-base/pull/123 |
| `C5.1e` | community-base | Curriculum ownership: course-owned modules, cohort placement, and nesting | C5.1d | no | done | https://github.com/DataTalksClub/community-base/pull/254 |
| `C5.1f` | community-base | Pre-work checklist items | C5.1e | no | done | https://github.com/DataTalksClub/community-base/issues/272 (merged to main as 202bcb9 and ee82f30: checklist_item unit kind, checklist services, curriculum README) |
| `C5.1g` | community-base | Structured code annotations in unit bodies | C5.1f | no | in-progress | https://github.com/DataTalksClub/community-base/issues/255 |
| `C5.2a` | community-base | Coursework models | C5.1d | no | done | https://github.com/DataTalksClub/community-base/pull/126 |
| `C5.2b` | community-base | Homework scoring and statistics | C5.2a | no | done | https://github.com/DataTalksClub/community-base/pull/128 |
| `C5.2c` | community-base | Projects and peer review | C5.2b | no | done | https://github.com/DataTalksClub/community-base/pull/132 |
| `C5.2da` | community-base | Leaderboard rollup, preferences and complaints | C5.2c | no | done | https://github.com/DataTalksClub/community-base/pull/141 |
| `C5.2db` | community-base | Registration campaigns and course registrations | C5.2c | no | done | https://github.com/DataTalksClub/community-base/pull/138 |
| `C5.2dc` | community-base | Learner views, member APIs and certificates | C5.2da, C5.2db | no | done | https://github.com/DataTalksClub/community-base/pull/146 |
| `C5.2e` | community-base | Coursework Studio and Wrapped | C5.2dc | no | done | https://github.com/DataTalksClub/community-base/pull/159 |
| `C5.2f` | community-base | Peer review assessment modes: per-submission lifecycle, pooled batch formation and assignment | C5.2e | no | done | https://github.com/DataTalksClub/community-base/pull/257 |
| `C5.2g` | community-base | Pooled review expiry and coursework email notifications | C5.2f | no | done | https://github.com/DataTalksClub/community-base/pull/262 |
| `C5.2h` | community-base | Certificate eligibility, learner-requested issuance, and banner-generator artifact seam | C5.2f | no | done | https://github.com/DataTalksClub/community-base/pull/263 |
| `C5.3` | community-base | Release 0.6.0 | C3.7, C4.3, C5.2e, C5.1e, C5.2h | no | todo | https://github.com/DataTalksClub/community-base/issues/273 |
| `A5.1` | AI-Shipping-Labs/website | Map AISL courses to the shared apps | C5.3 | no | todo | https://github.com/AI-Shipping-Labs/website/issues/1696 |
| `A5.2` | AI-Shipping-Labs/website | Freeze weekend: AISL courses cutover | A5.1 | yes | todo | https://github.com/AI-Shipping-Labs/website/issues/1697 |
| `D5.1` | DataTalksClub/website | Map DTC course platform data to the shared apps | C5.3 | no | todo | https://github.com/DataTalksClub/website/issues/414 |
| `D5.2` | DataTalksClub/website | Freeze weekend: DTC courses cutover and self-paced mode | D5.1 | yes | todo | https://github.com/DataTalksClub/website/issues/415 |

## Phase 6

| Issue | Repository | Title | Depends on | Freeze | Status | Link |
|---|---|---|---|---|---|---|
| `R6.1` | DataTalksClub/relay | AISL tenant and SES identity in Relay production | D1.3, D5.2 | no | todo | https://github.com/DataTalksClub/relay/issues/25 |
| `R6.2` | DataTalksClub/relay | History import | R6.1 | no | todo | https://github.com/DataTalksClub/relay/issues/26 — code complete on relay branch `r6.2-history-import` (9 commits, 682 tests pass, 10k-row fixture imported twice with zero rows on the second run). Built ahead of R6.1 deliberately; stays todo until R6.1 closes, and still needs relay Tester verification and PM acceptance per docs/PROCESS.md |
| `R6.3` | DataTalksClub/relay | Campaign parity for AISL | R1.5 | no | done | https://github.com/DataTalksClub/relay/commit/e183b23fb3cff7a782d1406cb5f84104ff17b51f |
| `C6.1` | community-base | Remove transitional backends | A6.4 | no | todo | https://github.com/DataTalksClub/community-base/issues/274 |
| `C6.2` | community-base | Relay contacts, subscriptions and tags clients | C1.2b | no | done | https://github.com/DataTalksClub/community-base/pull/226 |
| `C6.2a` | community-base | Relay verification confirmation scope | C6.2 | no | done | https://github.com/DataTalksClub/community-base/pull/240 |
| `A6.1` | AI-Shipping-Labs/website | Templates into Relay | R6.1, R1.3 | no | todo | https://github.com/AI-Shipping-Labs/website/issues/1698 |
| `A6.2` | AI-Shipping-Labs/website | Contacts and preferences into Relay | C6.2, R6.3, R1.5 | no | done | https://github.com/AI-Shipping-Labs/website/issues/1625 (closed by merge cc8c900d; dev deploy green on run 34735978832 attempt 2 after a transient one-test timeout on attempt 1) |
| `A6.3` | AI-Shipping-Labs/website | Switch backends, campaigns and SES events | A6.1, A6.2, R6.2 | no | todo | https://github.com/AI-Shipping-Labs/website/issues/1699 |
| `A6.4` | AI-Shipping-Labs/website | Freeze weekend: AISL production on Relay | A6.3 | yes | todo | https://github.com/AI-Shipping-Labs/website/issues/1700 |

## Phase 7

| Issue | Repository | Title | Depends on | Freeze | Status | Link |
|---|---|---|---|---|---|---|
| `C7.1` | community-base | Site convergence umbrella |  | no | todo | https://github.com/DataTalksClub/community-base/issues/258 |
| `C7.2` | community-base | Shared knowledge base app: wiki and docs | C2.4 | no | done | https://github.com/DataTalksClub/community-base/releases/tag/v0.4.1 |
| `D7.1` | DataTalksClub/website | DTC wiki and docs onto the shared app | C7.2, C7.4 | no | todo | https://github.com/DataTalksClub/website/issues/406 — unblocked: C7.4 merged, the four storage gaps are closed |
| `A7.1` | AI-Shipping-Labs/website | AISL gains wiki and docs | C7.2 | no | done | https://github.com/AI-Shipping-Labs/website/issues/1685#issuecomment-5704258072 (merged as website ac9a7ea3; Deploy Dev 35144001433 green; wiki and nested docs pages 200 on dev, pages in the sitemap) |
| `C7.3` | community-base | Gate Calendly Studio surfaces behind the Calendly flag |  | no | done | https://github.com/DataTalksClub/community-base/pull/267 |
| `C7.4` | community-base | Knowledge base: site-owned page identity, rendering and record metadata | C7.2 | no | done | https://github.com/DataTalksClub/community-base/issues/406 (unblocks D7.1. Slug unique per (section, parent) with a conditional constraint pair for the NULL-parent case; public_path, body_html_source and record added; sanitize_rendered_html no longer drops class, id, lang and title. A7.1 backward compatibility proven by six tests) |
| `C7.5` | community-base | Kernel model bases: optimistic concurrency and append-only |  | no | done | https://github.com/DataTalksClub/community-base/issues/258 (D19; merged as 9cac088. RevisionedModel, RevisionConflict, AppendOnlyManager and AppendOnlyQuerySet in community_base/kernel/models.py, abstract and manager-only, no migration. The donor AuditEvent carve-out stayed in DTC: it names a site model inside a domain-agnostic queryset) |
| `C7.6` | community-base | Accounts: queryable session record | C3.1e | no | done | https://github.com/DataTalksClub/community-base/issues/258 (D20; merged. Opt-in via SESSION_ENGINE, opt-out proven inert by test; erase and purge as services. Migration 0002_accountsession is provisional: AISL owns the donor equivalence check under C3.7, do not tag before it passes) |
| `C7.7` | community-base | Content format: specification, kind registry and validator |  | no | todo |  |
| `C7.8` | community-base | Shared rendering: one dialect, one sanitiser, rendered at sync | C7.7, C7.4 | no | todo |  |
| `C7.9a` | community-base | Document toolkit: collections, front matter, identity and checksums | C7.7 | no | todo |  |
| `C7.9b` | community-base | Document toolkit: assets and references | C7.9a, C7.8 | no | todo |  |
| `C7.9c` | community-base | Package parsers for the wiki, docs and person kinds | C7.9b, C7.4 | no | todo |  |
| `C7.10` | community-base | One course parser | C7.9b | no | todo |  |
| `C7.11` | community-base | Coursework: homework manifests from cohort bindings | C7.10, C5.2h | no | todo |  |
| `C7.12` | community-base | Conversion scripts and the unified format release | C7.9c, C7.10, C7.11 | no | todo |  |
| `C7.13` | community-base | Studio registration follows the mounted routes | C2.1a | no | todo |  |
| `C7.14` | community-base | Studio sidebar collapse and navigation density | C2.1a | no | todo |  |
