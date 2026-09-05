# Community-base owner decisions

Locator: `/home/alexey/git/community-base/docs/01-decisions.md`

Summary: Binding product and architecture decisions that the execution-plan change must preserve.

- [FACT owner-decisions] D1 requires a separate public `community-base` distribution installed independently by each site.
- [FACT owner-decisions] D2 prohibits cross-site database, cache, deployment, credential, or runtime assumptions.
- [FACT owner-decisions] D3 and D4 make Relay the target jobs/mail transport while retaining transitional AISL backends until D13.
- [FACT owner-decisions] D10 and D14 preserve selected AISL labels/tables and require exact migration-history compatibility.
- [FACT owner-decisions] D11 requires weekend freezes for extractions that move data models.
- [FACT owner-decisions] D13 blocks AISL Relay adoption until four clean weeks of DTC production evidence exist.

Limitations: Decisions specify target invariants, not the most efficient implementation order.

Related: [target architecture](target-architecture.md), [execution plan](execution-plan.md).
