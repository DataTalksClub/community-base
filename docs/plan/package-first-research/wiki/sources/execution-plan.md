# Seven-phase unification issue plan

Locator: `/home/alexey/git/community-base/docs/plan/`

Summary: Current implementation and adoption sequence across four repositories.

- [FACT execution-plan] C0.3 requires settings API endpoints and scope tests registered through the API foundation defined by C0.4.
- [FACT execution-plan] C0.4 verifies `/api/v1/settings`, which is owned by C0.3, while both currently depend only on C0.2.
- [FACT execution-plan] C1 jobs/mail can be locally exercised with sync/memory backends and fakes, but their full Relay behavior depends on R1.2-R1.4 and sandbox/deployed checks.
- [FACT execution-plan] C3.1 can build shared account behavior locally, but its exact `replaces` migration must wait until AISL A3.1 removes site-only user fields.
- [FACT execution-plan] C4.1 directly depends on A4.1 seam cutting before P4 extraction.
- [FACT execution-plan] C6.1 intentionally depends on completed AISL Relay adoption and therefore cannot move into the package-first build wave.
- [INFERENCE execution-plan,target-architecture] Package implementation and adoption-readiness acceptance must be separated for kept-label apps and external Relay contracts.

Limitations: The current parser derives dependencies from prose and does not fully represent prerequisite versus acceptance relationships.

Related: [target architecture](target-architecture.md), [quality gates](quality-gates.md).
