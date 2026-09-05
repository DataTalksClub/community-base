# Community-base target architecture

Locator: `/home/alexey/git/community-base/docs/02-architecture.md`

Summary: Authoritative package shape and composability constraints.

- [FACT target-architecture] Package apps may use only the named access, config, mail, jobs, signal, Studio, API, template, and extension-model seams.
- [FACT target-architecture] Package modules cannot import site apps and must read settings through `settings.COMMUNITY_BASE`.
- [FACT target-architecture] Network side effects must occur in explicit services or post-commit jobs, never model saves, signals, or request transactions.
- [FACT target-architecture] Migrations become append-only after their first package tag.
- [FACT target-architecture] Kept-label apps must reuse AISL tables and migration history through squashed migrations with exact `replaces` lists.
- [FACT target-architecture] `cb_` labels create new package-owned tables and site adoption copies data later.

Limitations: The architecture does not describe provisional development before donor-compatible migration baselines are finalized.

Related: [owner decisions](owner-decisions.md), [execution plan](execution-plan.md).
