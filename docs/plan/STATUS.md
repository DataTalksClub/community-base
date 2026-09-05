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
| `C0.5` | community-base | First release | C0.2, C0.3, C0.4 | no | todo | https://github.com/DataTalksClub/community-base/issues/5 |
| `A0.1` | AI-Shipping-Labs/website | Add the package dependency and the local link targets | C0.5 | no | todo |  |
| `A0.2` | AI-Shipping-Labs/website | Replace the settings framework with the package config app | A0.1 | no | todo |  |
| `A0.3` | AI-Shipping-Labs/website | Access policy hook | A0.1 | no | todo |  |
| `D0.1` | DataTalksClub/website | Add the package and replace the settings frameworks | C0.5 | no | todo |  |
| `D0.2` | DataTalksClub/website | Site CI guard and pin bump workflow | D0.1 | no | todo |  |

## Phase 1

| Issue | Repository | Title | Depends on | Freeze | Status | Link |
|---|---|---|---|---|---|---|
| `R1.1` | DataTalksClub/relay | Relay production environment |  | no | todo |  |
| `R1.2` | DataTalksClub/relay | Webhook task hardening |  | no | todo |  |
| `R1.3` | DataTalksClub/relay | Template catalog: versions, preview, test send, typed context |  | no | todo |  |
| `R1.4` | DataTalksClub/relay | Client callbacks for delivery and engagement events | R1.2 | no | todo |  |
| `R1.5` | DataTalksClub/relay | Preference categories and double opt-in |  | no | todo |  |
| `C1.1` | community-base | Jobs app | C0.5 | no | todo |  |
| `C1.2` | community-base | Mail app | C1.1 | no | todo |  |
| `C1.3` | community-base | ses_local backend (transitional, for AISL) | C1.2 | no | todo |  |
| `C1.4` | community-base | Test doubles exported for sites | C1.1, C1.2 | no | todo |  |
| `C1.5` | community-base | Release 0.2.0 | C1.1, C1.2, C1.3, C1.4 | no | todo |  |
| `D1.1` | DataTalksClub/website | Replace DTC jobs with the package jobs app (relay backend) | C1.5, R1.1, R1.2 | no | todo |  |
| `D1.2` | DataTalksClub/website | Replace DTC email_app and the Datamailer outbox with the package mail app | D1.1, R1.3, R1.4, R1.5 | no | todo |  |
| `D1.3` | DataTalksClub/website | Freeze weekend: DTC on Relay in production | D1.1, D1.2 | yes | todo |  |
| `A1.1` | AI-Shipping-Labs/website | Adopt the package jobs app on the django_q backend | C1.5 | no | todo |  |
| `A1.2` | AI-Shipping-Labs/website | Adopt the package mail app on the ses_local backend | C1.5, A1.1 | no | todo |  |

## Phase 2

| Issue | Repository | Title | Depends on | Freeze | Status | Link |
|---|---|---|---|---|---|---|
| `C2.1` | community-base | Studio shell | C1.5 | no | todo |  |
| `C2.2` | community-base | Users management in Studio | C2.1 | no | todo |  |
| `C2.3` | community-base | Content sync engine | C1.5, C2.1 | no | todo |  |
| `C2.4` | community-base | Release 0.3.0 | C2.1, C2.2, C2.3 | no | todo |  |
| `A2.1` | AI-Shipping-Labs/website | Adopt the Studio shell | C2.4 | no | todo |  |
| `A2.2` | AI-Shipping-Labs/website | Users pages from the package | A2.1 | no | todo |  |
| `A2.3` | AI-Shipping-Labs/website | Content sync through the package engine | C2.4 | no | todo |  |
| `D2.1` | DataTalksClub/website | Mount the Studio shell and re-home DTC Studio pages | C2.4 | no | todo |  |
| `D2.2` | DataTalksClub/website | Content sync per decision #226 | C2.4 | no | todo |  |

## Phase 3

| Issue | Repository | Title | Depends on | Freeze | Status | Link |
|---|---|---|---|---|---|---|
| `C3.1` | community-base | Accounts app: user model, auth views, services, profile | C2.4 | no | todo |  |
| `C3.2` | community-base | Questionnaires | C3.1 | no | todo |  |
| `C3.3` | community-base | Onboarding flows | C3.1, C3.2 | no | todo |  |
| `C3.4` | community-base | Community (Slack) | C3.1 | no | todo |  |
| `C3.5` | community-base | Notifications, comments, voting | C3.1 | no | todo |  |
| `C3.6` | community-base | Identity and community capability checkpoint | C3.1, C3.2, C3.3, C3.4, C3.5 | no | todo |  |
| `C3.7` | community-base | Identity donor compatibility checkpoint | C3.6, A3.2, D3.1 | no | todo |  |
| `A3.1` | AI-Shipping-Labs/website | Move tier and Stripe fields off the user model | C5.2 | no | todo |  |
| `A3.2` | AI-Shipping-Labs/website | Extension models for the remaining site-only user fields | A3.1 | no | todo |  |
| `A3.3` | AI-Shipping-Labs/website | Freeze weekend: adopt shared accounts, questionnaires, community, notifications, comments, voting | C5.3, C3.7, A3.2 | yes | todo |  |
| `D3.1` | DataTalksClub/website | Extension models and user model rename | C5.2 | no | todo |  |
| `D3.2` | DataTalksClub/website | Freeze weekend: adopt shared accounts and onboarding | C5.3, C3.7, D3.1 | yes | todo |  |

## Phase 4

| Issue | Repository | Title | Depends on | Freeze | Status | Link |
|---|---|---|---|---|---|---|
| `A4.1` | AI-Shipping-Labs/website | Cut the seams in AISL events | C5.2, A3.2 | no | todo |  |
| `C4.1` | community-base | Lift events | C3.6 | no | todo |  |
| `C4.2` | community-base | Events capability checkpoint | C4.1 | no | todo |  |
| `C4.3` | community-base | Events donor compatibility checkpoint | C4.2, A4.1 | no | todo |  |
| `A4.2` | AI-Shipping-Labs/website | Freeze weekend: adopt shared events | C5.3, C4.3, A4.1 | yes | todo |  |
| `D4.1` | DataTalksClub/website | Database-authored events in DTC | C5.3 | no | todo |  |
| `D4.2` | DataTalksClub/website | Freeze weekend: DTC events cutover | D4.1 | yes | todo |  |

## Phase 5

| Issue | Repository | Title | Depends on | Freeze | Status | Link |
|---|---|---|---|---|---|---|
| `C5.1` | community-base | Curriculum app | C4.2 | no | todo |  |
| `C5.2` | community-base | Coursework app | C5.1 | no | todo |  |
| `C5.3` | community-base | Release 0.6.0 | C3.7, C4.3, C5.2 | no | todo |  |
| `A5.1` | AI-Shipping-Labs/website | Map AISL courses to the shared apps | C5.3 | no | todo |  |
| `A5.2` | AI-Shipping-Labs/website | Freeze weekend: AISL courses cutover | A5.1 | yes | todo |  |
| `D5.1` | DataTalksClub/website | Map DTC course platform data to the shared apps | C5.3 | no | todo |  |
| `D5.2` | DataTalksClub/website | Freeze weekend: DTC courses cutover and self-paced mode | D5.1 | yes | todo |  |

## Phase 6

| Issue | Repository | Title | Depends on | Freeze | Status | Link |
|---|---|---|---|---|---|---|
| `R6.1` | DataTalksClub/relay | AISL tenant and SES identity in Relay production | D1.3, D5.2 | no | todo |  |
| `R6.2` | DataTalksClub/relay | History import | R6.1 | no | todo |  |
| `R6.3` | DataTalksClub/relay | Campaign parity for AISL | R1.5 | no | todo |  |
| `C6.1` | community-base | Remove transitional backends | A6.4 | no | todo |  |
| `A6.1` | AI-Shipping-Labs/website | Templates into Relay | R6.1, R1.3 | no | todo |  |
| `A6.2` | AI-Shipping-Labs/website | Contacts and preferences into Relay | R6.3, R1.5 | no | todo |  |
| `A6.3` | AI-Shipping-Labs/website | Switch backends, campaigns and SES events | A6.1, A6.2, R6.2 | no | todo |  |
| `A6.4` | AI-Shipping-Labs/website | Freeze weekend: AISL production on Relay | A6.3 | yes | todo |  |
