# community-base

Shared Django apps for DataTalks.Club community sites. Two sites consume it today:

- DataTalks.Club website (`DataTalksClub/website`)
- AI Shipping Labs website (`AI-Shipping-Labs/website`)

Both sites run independently, with their own database, deployment, user model, public design and
site-specific apps. They install this package and mount the apps they need. Email, contacts,
campaigns, background jobs and schedules are delegated to Relay (`DataTalksClub/relay`), a separate
service that each site talks to over HTTPS.

Status: planning. The Python package does not exist yet. The plan in `docs/plan/` creates it and
moves code out of the two sites phase by phase.

## Documents

| Document | What it is for |
|---|---|
| `docs/00-analysis.md` | Inventory of the two sites and Relay, overlap map, coupling audit. Read once. |
| `docs/01-decisions.md` | Product and architecture decisions already taken by the owner. Do not re-open them. |
| `docs/02-architecture.md` | Target architecture, package layout, app labels, extension seams, template contract. |
| `docs/03-playbooks.md` | Step-by-step procedures reused by many issues: lifting an app, squashing migrations, cutting a seam, releasing, freeze weekend. |
| `docs/04-quality-gates.md` | The checks every issue must pass, the issue template, and when to stop and ask a human. |
| `docs/plan/README.md` | Phase index and dependency order. |
| `docs/plan/phase-*.md` | One file per phase with every issue spelled out: goal, what to read, steps, verification, done criteria. |

## How to work on this

1. Read `docs/04-quality-gates.md` first. Every issue in `docs/plan/` assumes those gates.
2. Pick the lowest-numbered open issue in the current phase whose dependencies are done.
3. Follow the issue steps literally. Run every verification command and compare with the expected
   result. If a check fails, fix it before moving on. Never skip a check.
4. Open one pull request per issue, in the repository the issue names (`community-base`,
   `DataTalksClub/website`, `AI-Shipping-Labs/website`, or `DataTalksClub/relay`).

## Conventions

- Python is managed with `uv`. Never call `pip` directly.
- Documents use plain text, headings, tables and backticks. No bold formatting.
- File paths, commands, setting keys and model names are written in backticks.
- Site repositories keep their own `_docs/PROCESS.md`; this repository's process is documented in
  `docs/04-quality-gates.md` until the package repository gets its own `_docs/PROCESS.md` in
  Phase 0.
