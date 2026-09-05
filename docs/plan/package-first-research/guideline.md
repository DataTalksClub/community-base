# Package-first implementation plan

Status: approval requested.

## 1. Outcome

Implement all shared product behavior, extension seams, integration clients, tests, and adoption
tooling in `community-base` before either website adopts the package. After package capability is
complete, prepare donor schemas and seams, finalize migration compatibility, publish an
adoption-ready release, and port each site through its existing process.

This changes scheduling and issue boundaries. It does not change decisions D1-D14, package/site
ownership, Relay ownership, migration safety, freezes, or production proof.

## 2. Current behavior and evidence

- C0.1 and C0.2 are merged, verified, and marked done.
- `scripts/plan.py next` currently offers C0.3 and C0.4.
- C0.3 requires C0.4’s API registry and scope enforcement.
- C0.4’s verification incorrectly uses C0.3’s `/api/v1/settings` route.
- The current tracker accepts only unsuffixed IDs even though the process prescribes splits such as
  `C2.3a`.
- The dependency parser scans prose, so A3.1’s “must land before C3.1” text is incorrectly treated
  as A3.1 depending on C3.1.
- Kept-label accounts and events migrations cannot be certified until AISL reaches the matching
  schema. Tagged migrations are append-only.
- C6.1 must remain after AISL Relay adoption because transitional backends are required until D13.

Evidence and provenance are indexed under `sources/index.yaml` and `wiki/sources/`.

## 3. Execution policy

Every applicable capability has two independently tracked milestones:

| Milestone | Meaning | Evidence |
|---|---|---|
| Package capability ready | Behavior exists in this repository and passes package-local acceptance | package tests, fresh migrations, wheel checks, synthetic adapters, fixture contracts |
| Adoption compatible | External contracts and donor/site migration paths are proven | Relay conformance, donor inventory, squash equivalence, development-copy rehearsal, site CI/deploy |

Whole phases retain their existing definition of done. A phase is not complete merely because its
package milestone is complete.

During the package-first stage:

1. Select the next ready `community-base` implementation issue.
2. Keep site and Relay issues `todo`; never mark them `skipped` to satisfy dependencies.
3. Record external checks under “Not run here, needs:” rather than claiming them passed.
4. Do not tag any commit containing a provisional kept-label migration.
5. Use one PR per split issue and small coherent commits within it.

## 4. Plan-correction PR

Before C0.4, make the plan itself executable in one reviewable PR.

### Tracker changes

- Support IDs matching `[CADR][0-9]+.[0-9]+[a-z]?` in headings, dependencies, and status rows.
- Parse one dedicated `Depends on:` metadata line containing only IDs or `nothing`.
- Stop deriving dependencies from later explanatory prose.
- Reject duplicate IDs, cycles, missing dependencies, invalid statuses, and generated-column drift.
- Add `next --repo community-base` or an equivalent explicit package-first selector.
- Add tests for suffixes, A3.1’s prior false edge, cycles, duplicates, and stable STATUS generation.

### Documentation changes

- Update `AGENTS.md`, `README.md`, `docs/PROCESS.md`, the plan index, phase files, playbooks,
  architecture, and quality gates to distinguish package capability from adoption compatibility.
- Preserve all existing checks, assigning each to the split issue that can truthfully produce its
  evidence.
- Correct stale claims that both sites already consume the package.
- Keep D1-D14 unchanged.

Verification:

- Tracker unit tests pass.
- `uv run python scripts/plan.py check` passes.
- `uv run python scripts/plan.py next --repo community-base` selects C0.4.
- Regenerating STATUS produces no diff.

## 5. Ordered package implementation

### Milestone A: foundation

1. C0.4 API foundation, depending on C0.2.
   - Own APIKey, bearer authentication, scopes, route registry, error envelope, safety rules,
     OpenAPI generation/checking, and superuser key management.
   - Add the `apispec` dependency explicitly.
   - Verify 200/401/403 against a registered fixture endpoint, not settings.
2. C0.3 configuration, depending on C0.4.
   - Own registry metadata, typed values, encrypted secrets, resolution order, stamp cache, audit
     rows, import/export, standalone Studio page, and real settings API routes.
   - Verify `/api/v1/settings` here, including read/write scopes and masking.
3. C0.5 publishes `v0.1.0` after full foundation acceptance.

Whenever an issue introduces a package key or hook, extend `kernel.conf.DEFAULTS`, the kernel
README, architecture key inventory, and tests in the same PR. Document the narrow standard-Django
settings exceptions needed for `AUTH_USER_MODEL`, `LOGIN_URL`, secret encryption, and declared
fallbacks; arbitrary settings reads remain prohibited.

### Milestone B: jobs and mail

Split implementation from real Relay conformance:

1. C1.1a: durable jobs model, registry, transactions, leases, runner, sync/django-q backends,
   signed ingress, commands, and standalone staff pages.
2. C1.1b: Relay client protocol and FakeRelay contract tests. Real lease/completion conformance
   remains dependent on R1.2.
3. C1.2a: durable mail projection, memory behavior, preference hooks, link bridge, monotonic
   callbacks, standalone pages, and APIs.
4. C1.2b: Relay send/catalog/callback/reconciliation clients and FakeRelay tests. Real conformance
   remains dependent on R1.3 and R1.4.
5. C1.3: transitional SES-local backend with byte-normalized donor rendering fixtures.
6. C1.4: exported deterministic test helpers used by the package itself.
7. C1.5 publishes `v0.2.0` when package-local acceptance passes. Site adoption additionally
   depends on the relevant real Relay conformance issues.

Required package evidence includes transaction rollback, idempotency, lease fencing, retry/backoff,
signature/replay rejection, monotonic delivery transitions, optional extras, and installed-wheel
command/template discovery.

### Milestone C: Studio and content sync

1. C2.1a: Studio shell, registry, assets, route ownership, generic search/dashboard, and
   impersonation security.
2. C2.1b: mount config, API, jobs, and mail screens after those apps exist.
3. C2.2: generic user list/detail/export/tags/notes and extension registries. Keep create/import/
   merge with C3 accounts.
4. C2.3: content-sync engine, depending on jobs and the Studio shell; include fixture-repository
   idempotency, soft deletion, webhook security, API, and staff surfaces.
5. C2.4 publishes `v0.3.0` after package-local acceptance.

### Milestone D: identity and community behavior

Build the final shared behavior locally without claiming donor compatibility:

1. C3.1a: target User/MemberProfile schema and provisional initial migration.
2. C3.1b: authentication, allauth adapter, account settings helper, and public templates.
3. C3.1c: verification, aliases, email change, merge, privacy, timezone, import, mail preferences,
   self API, and staff create/import/merge.
4. C3.2a: questionnaires and optional AI behavior.
5. C3.3: configurable onboarding flows and all step types.
6. C3.4a: Slack/community behavior with optional Calendly boundary.
7. C3.5a, C3.5b, C3.5c: notifications, comments, and voting separately, followed by a shared
   integration check.

Initial migrations for kept-label apps remain provisional and untagged. Every copied donor test is
classified as moved, adapted, or intentionally site-owned in a behavior coverage matrix.

### Milestone E: events behavior

Remove A4.1 as a prerequisite to local package adaptation while retaining it for compatibility.

1. C4.1a: target events/hosts/series models and domain services.
2. C4.1b: authenticated and anonymous registration, verification lifecycle, series occurrence
   behavior, reminders, and feedback.
3. C4.1c: ICS/Zoom/banner/writeup integration boundaries and job handlers.
4. C4.1d: public pages, both URL styles, Studio pages, APIs, templates, and tests.

The events initial migration remains provisional and untagged until AISL seam/schema preparation
and exact `replaces` verification complete.

### Milestone F: curriculum and coursework

Depend on implementation interfaces rather than adoption tags.

1. C5.1a: curriculum graph, access inheritance, enrollment/progress/certificates.
2. C5.1b: AISL and DTC import formats through content-sync parsers.
3. C5.1c: public, Studio, and API surfaces.
4. C5.2a: homework, questions, submissions, scoring, and statistics.
5. C5.2b: projects, criteria, peer review, and evaluation.
6. C5.2c: leaderboard, complaints, registration campaigns, testimonials, wrapped statistics,
   reminders, and certificate workflow.
7. C5.2d: complete workflow acceptance with coursework installed and omitted.

Curriculum/coursework use new `cb_` labels, so their migrations can be finalized locally.

### Milestone G: adoption toolkit

Before touching adopters, add package-owned material that makes porting mechanical:

- Two synthetic site configurations: registered-only and tier/purchase access.
- Composition matrix covering minimal, full, optional AI, django-q/SES-local, and Relay modes.
- Installed-wheel tests for migrations, templates, static assets, commands, URL names, scopes,
  handlers, schedules, signals, and optional dependencies.
- PostgreSQL CI for locks, leases, constraints, and migrations; SQLite remains the fast default.
- Donor model/migration/test inventories with captured commit SHAs.
- Per-app README covering settings/defaults, app order, URLs, hooks/signals, templates, scopes,
  handlers, dependencies, ownership, and migration assumptions.
- Migration rehearsal scaffolding using synthetic data, clearly separate from development-copy
  evidence.

## 6. Compatibility and release milestone

After all package behavior above is implemented:

1. Perform AISL/DTC preparatory issues through their own repository processes:
   - AISL user contraction and extension fields.
   - DTC user rename/extensions and FK reconciliation.
   - AISL kept-label seam/schema preparation for accounts, questionnaires, community,
     notifications, comments, voting, and events.
   - Site-specific hooks/adapters needed by the already-built package contracts.
2. Record exact donor commit SHA, migration names/dependencies, model state, test counts, and
   excluded site behavior.
3. Finalize each provisional package squash against the prepared donor state.
4. Put genuinely new shared schema in appended migrations after the equivalent squash.
5. Run donor equivalence, reversibility, synthetic PostgreSQL, and development-copy rehearsal.
6. Convert C3.6 and C4.2 from obsolete intermediate release tags into identity/events
   compatibility checkpoints.
7. Publish one adoption-ready `v0.6.0` under C5.3 after every provisional kept-label migration is
   finalized. Never publish `v0.4.0`/`v0.5.0` commits that contain provisional migrations.

Once a migration is tagged, preserve its `replaces` marker. Remove P4 step 10 unless a future
explicit migration policy supplies an append-only alternative.

## 7. Site adoption and Relay operations

After `v0.6.0`, execute existing A/D issues in dependency order, adding missing site-local edges.
Foundation, jobs/mail, Studio/content sync, accounts/community, events, and learning are still
separate adoption PRs and freezes; one large-bang site migration is not allowed.

Real Relay issues and acceptance remain external:

- R1.2 tasks/leases/completion.
- R1.3 versions/catalog/preview/test-send.
- R1.4 callbacks/reconciliation.
- R1.5 preferences/double opt-in.
- R6.2 history import and R6.3 campaign parity.

Add an explicit package issue for Relay-proxied campaign pages and contact/preference client
interfaces before A6.3; no current C issue owns them. Site-specific audience/tier mapping stays in
site hooks.

DTC’s Relay production adoption starts D13’s four-week clock. AISL stays on django-q/SES-local
until the clock and status contract pass. C6.1 and `v1.0.0` remain after A6.4 and remove the
transitional backends only then.

## 8. Verification matrix

| Area | Package capability evidence | Later external evidence |
|---|---|---|
| Config/API | typed resolution, encryption, audit, cache, 200/401/403, OpenAPI | same JSON shape in both development sites |
| Jobs/mail | transaction, leases, signatures, fakes, rendering fixtures | real Relay sandbox/production contracts |
| Studio/templates | route ownership, permissions, CSS reproducibility, template contract | site overrides and deployed rendering |
| Kept-label models | target-schema tests, provisional migrations, donor snapshots | exact squash plan, row counts, rehearsal, freeze |
| New-label models | fresh/reverse migrations and synthetic copies | site data-copy counts and rehearsal |
| Learning | both import fixtures and full workflow | donor data mapping and deployed course paths |
| Packaging | full/minimal matrices and installed wheel | pinned site CI and development deployment |

Every PR still runs the issue verification, universal gates, applicable migration/extraction gates,
and plan check. A failed external contract remains a stop for its integration issue without
blocking independent package-local work.

## 9. Failure modes and safeguards

- Migration drift: no domain tag until all kept-label baselines are final; store donor SHA and
  inventories; append only after tag.
- False Relay confidence: FakeRelay proves client logic only; dedicated real conformance gates
  remain mandatory.
- Hidden site coupling: boundary tests plus two synthetic site adapters and optional-app matrices.
- Oversized extractions: use letter-suffixed issues and one coherent capability per PR.
- Lost production evidence: phase completion remains separate from package readiness.
- D13 delay: explicitly accept that package-first postpones the start of the four-week clock.
- Scope creep: payments, plans, CRM, site content, sponsors, navigation, audit extensions, and
  public site design remain site-owned unless an owner decision changes them.

## 10. Approval and first action

Approval means accepting:

1. Package capability and adoption compatibility as separate milestones.
2. C0.4 before C0.3.
3. All shared behavior built here before site adoption.
4. Provisional kept-label migrations remain untagged until donor preparation.
5. C3.6/C4.2 become compatibility checkpoints and `v0.6.0` becomes the single domain
   adoption-candidate release.
6. Tagged `replaces` markers are not removed.

After approval, the first implementation is the plan-correction PR in section 4. The first product
implementation after that is C0.4 API, followed by C0.3 Config.

Status: not distilled

Research must be distilled here before approval.
