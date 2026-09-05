# Community-base quality gates

Locator: `/home/alexey/git/community-base/docs/04-quality-gates.md`

Summary: Mandatory evidence and stop conditions for plan execution.

- [FACT quality-gates] Every PR must pass lint, format, Django checks, migration drift, fresh migration, relevant tests, boundary checks, and issue-specific documentation.
- [FACT quality-gates] Migration PRs require reversibility, row-count evidence, and development-copy rehearsal where specified.
- [FACT quality-gates] Cross-repository moves require test-count, import, template, site-CI, and package-tag evidence.
- [FACT quality-gates] Production credentials/data, migration loss, decision conflicts, incorrect migration lists, contract mismatches, missing tags, and unannounced freezes are stop conditions.
- [FACT quality-gates] A phase is complete only after every issue is merged and affected development deployments and exit criteria pass.

Limitations: These gates define acceptance evidence but do not require package and adoption work to share a phase.

Related: [execution plan](execution-plan.md), [owner decisions](owner-decisions.md).
