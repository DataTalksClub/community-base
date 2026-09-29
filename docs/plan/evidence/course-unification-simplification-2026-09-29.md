# Course experience unification and code simplification proposal

Date: 2026-09-29. Researched in parallel by three Sol agents, one for each repository,
and reconciled by the orchestrator. Revised following the owner's clarifications:
"don't change anything in ui and don't remove features. I want code simplifications", and
"I worked for quite some time on aisl courses and I want DTC to have the same experience".

Status: the cross-site unification remains a proposal with focused implementation slices
tracked below. Three AISL cleanups are independently verified and shipped to development; DTC's
crypto consolidation passed review and CI but its development deployment failed. The public
renderer is released, and AISL's isolated adoption includes a tagged dependency update.
No database schema changes belong to these simplification slices.
AISL's established course experience is the reference to preserve and bring to DTC. The work
does not design a new course experience or remove features. Existing phase issues remain
unchanged; their broader scope is not implicitly authorized by this proposal.
The active implementation constraint is no visible UI changes in either site. Experience
unification proceeds through shared equivalent behavior; remaining differences stay documented.

## Current delivery state

This summary supersedes historical local-only or pending-release statements in the evidence below.

- AISL #1842/#1843/#1844 landed through the receiving owner and passed development deployment.
- DTC #438 and the #440 drain correction are on main; exact CI is green, development deployment
  remains red at migration exit 21, and the public development site returns 503. The earlier reset
  attempt failed before SQL. The requested scoped IAM log access remains pending; no second reset
  ran. #439 remains on its explicit operational hold.
- Package v0.5.15 is published with the homework error-input fix; DTC still pins v0.5.10.
  The proposed pin update has a documented checkbox-draft message difference to resolve first.
- Aplexer PR #23 messaging and worker fixes passed hosted CI. The maintainer's mouse changes have
  since been added as combined head `6a71a69f850a42956ba4bf434b5f7e4599d260e9`; that exact head's
  CI passed. Final main integration is awaiting the maintainer; it owns installation and preservation
  of the separate config overlay.
- C5.4 has a concrete backend-only separation plan. The proposed first slice preserves Unit identity
  during source moves. The existing draft owner has received the coordination request; no source
  changes have been made to that draft or to the transferred AISL worktrees.
- Full course unification remains incomplete. No visible site UI or feature was removed to obtain
  the reported reductions. AISL data-preservation and donor-adoption gates remain in force.

## Objective and constraints

Bring AISL's established course experience to DTC and reduce duplicated code, unnecessary
indirection and maintenance effort across community-base, AISL and DTC. Preserve the work
already done on AISL and every existing feature on both sites.

- Preserve both sites' course pages, styling, labels, controls, navigation and interactions.
- Make DTC's course experience follow that AISL reference, using shared behavior behind
  site-owned presentation. Do not introduce a third design or speculative UX improvements.
- Retain DTC's additional features and their complete workflows when integrating the reference
  experience. Preserve current route/API contracts through site adapters.
- Preserve public, member and staff APIs, CLI commands and integration contracts.
- Preserve access, enrollment, progress, homework, assessment, review and certificate behavior.
- Preserve source-authoring capabilities, accepted input formats, sync behavior and staff workflows.
- Preserve AISL data, stable identities and history. Preserve behavior and side effects,
  including notification timing, in both sites. The DTC rebuild exception is recorded below.
- Remove implementation code only after proving that its behavior has an equivalent replacement,
  or that the code is genuinely unreachable and supports no feature or external contract.

Keep intentional policy differences explicit: DTC has no paid tiers, while AISL retains its
access and enrollment integrations. These differences do not require separate implementations
of the common course experience. Public presentation remains site-owned under D18; share the
underlying behavior so bringing AISL's experience to DTC does not create another large code fork.

### Database rebuild boundary

The owner clarified: "for DTC website we can nuke the Db and recreate it. for aisl we can't".
DTC adoption may therefore use a fresh database instead of retaining obsolete migration and
compatibility code solely to preserve disposable DTC data. This does not permit removing
features, changing visible UI, or skipping fresh-install and workflow verification. AISL
adoption still requires preserving existing data and its migration history.

The immediate operational use is limited to the failed DTC development deployment in
[#438](https://github.com/DataTalksClub/website/issues/438#issuecomment-5890507372):
rebuild `dtc_website_dev` through a reviewed development-only path. The separate
`dtc_relay_dev` database and shared RDS instance remain intact. No production or AISL
database operation is included. Record fresh migrations, development deployment and
any required public content bootstrap separately; authorization is not evidence of success.

The bounded development recovery is tracked in
[#440](https://github.com/DataTalksClub/website/issues/440). It adds an explicit first-attempt
manual dispatch to the existing development deploy path, with target checks, website writer
drain, transactional schema reset, and the normal migration/promotion checks. A failed reset
or subsequent deployment must leave website services stopped instead of restoring old images
against the new schema. Independent testing and acceptance precede the live operation.

For later DTC curriculum adoption, revise D5.1 / site #414 and D5.2 / site #415 explicitly
before implementation. Their present acceptance criteria still require historical row and
identity preservation. The proposed replacement for an approved disposable target is:

1. Retain the adoption-ready C5.3 release and fresh package migration gates.
2. Replace old DTC row backfills and equal-count checks with fresh schema creation and import
   of approved public course, cohort and homework sources; verify source-defined dates,
   self-paced cohorts and idempotent reimport.
3. Verify all current routes, APIs, Studio operations, homework, peer review and certificate
   issuance/download using representative new data. Data disposal does not remove a feature.
4. Retain D7.3 parser retirement and D7.4 source conversion, authoring, route, sitemap and
   content-freeze checks. Resetting a database does not make source compatibility unnecessary.
5. Keep AISL's donor inventory, lossless migration rehearsal, row preservation and production
   cutover gates. Do not carry DTC's disposable-data exception into package guarantees for AISL.

This is a proposed revision to the later adoption criteria, not a declaration that #414,
#415 or their migration gates are complete. The immediate #440 operation remains scoped above.

The independent PM review also identified old learner-ID/submission preservation language in
D5.3 / site #436. Amend that prerequisite together with D5.1 and D5.2 for the explicitly scoped
fresh target; do not silently override it downstream. Keep the dependency chain
C5.4 -> D5.3, then C5.3 + D5.3 -> D5.1 -> D5.2. An in-place target retains its preservation
requirements. Historical count equality and original certificate-row preservation become
`Not applicable: authorized fresh DTC development target`, rather than reported passes.

Fresh adoption still needs all six DTC source repositories, flat and nested curriculum,
source identities and cohort dates, and repeat-import checks with no duplicates. Protected
learner flows use synthetic records. The existing development public CMP bootstrap imports
only an audited public artifact into the current site models; it is not proven compatible
with package-owned storage and excludes learner and operational data. Establish the new
source/import contract before using it for adoption. A green empty-schema deployment cannot
stand in for imported content or course-workflow evidence.

### Next shared curriculum prerequisite

The current-main audit at package `f35acecd2a95f34920433c71b7c0b649c0eeec4e` identified
[C5.4 / #306](https://github.com/DataTalksClub/community-base/issues/306), drafted in
[PR #311](https://github.com/DataTalksClub/community-base/pull/311), as the next independent
course implementation prerequisite. This is existing work to reconcile, not a reason to add
another parser. Its head is `09d7940f3fa54f32d6ba05806f02e74531bb2bca` in
`/home/alexey/git/cb-course-hierarchy`; ownership has been requested before source changes.

The P18 preview tree `cc835eee909e777cc87187c313f9e0b7b4630450` has three version conflicts:
`community_base/__init__.py`, `pyproject.toml`, and `uv.lock`. Main is v0.5.14; the draft still
declares v0.5.13. Preserve current release metadata during reconciliation and follow the normal
release process later. Its consumer failures remain unresolved and require an on-call verdict;
the preview is neither integration nor verification evidence.

The draft supports recursive mixed module/unit order, YAML homework, and course-wide stable
unit identity. It also changes public package routes, API projections and rendered syllabus
markup, including a completion badge. Whether those templates are currently served by either
site was not established. Do not merge it as an invisible refactor: separate or reconcile
those changes with this session's UI and interface preservation constraints before adoption.
Required evidence includes existing flat-course HTML and route compatibility, correct mixed
ordering, preserved progress and coursework identities when a unit moves, rejection before
writes for invalid source data, and no correct answers in learner projections. Run package and
both consumer gates separately after the implementation is reconciled.

Current D5.1 depends on both D5.3 and C5.3. C5.4 feeds the A5.3/D5.3 adapters; it does not
replace C5.3's C3.7/C4.3 donor compatibility prerequisites. AISL's outstanding donor-equivalence
and development-copy rehearsals remain required despite DTC's fresh-schema allowance.

## Coding standards and deletion objective

Follow the current `coding-standard.md` in each repository. All three were read for this
proposal, including newly introduced local standards. They govern new and materially changed
handwritten code even where the inspected remote source predates them.

- Search for the existing owner and consolidate only behavior with the same semantics.
- Keep views/API handlers thin; give each business rule one domain owner and each related
  state transition an explicit transaction boundary.
- Keep new functions at or below 30 lines and files at or below 300 lines. Do not grow an
  oversized function/file; split materially changed code along cohesive responsibilities.
  Document only the tool/framework/cohesion exceptions the standards permit.
- Use explicit control flow, guard clauses and intent-revealing names. No ternary expressions;
  comprehensions are limited to one simple loop without filtering or nesting.
- Keep data shaping in Python. Reuse site-owned template partials with explicit context;
  extracting a partial must preserve its rendered behavior and established component ownership.
- Identify an authoritative behavior test before refactoring. Add missing coverage first and
  demonstrate it passes before and after. Presentation changes are outside this implementation.
- Preserve specific exception handling, server authorization, sanitization and redaction.
  Prevent avoidable N+1 queries and keep growing collections paginated.

| Repository | Configuration authority | Verification tools |
|---|---|---|
| community-base | `community_base.config.get/is_enabled`, owning app `settings_keys.py` | `make lint`, `make test tests/<path>`, quality gates and consumer checks |
| AISL | `get_config/is_enabled`, `integrations/settings_keys.py` | `make lint`, inspect `scripts/affected_tests.py`, `make test-affected` |
| DTC | Typed helpers in `website/settings/` | `uv run --frozen python scripts/ci.py lint`, current verification selector and required evidence, quality, Django, browser and container checks |

Optimize for net code removed across all three repositories, fewer copies of each rule and
fewer indirections. Count replacement code and permanent adapters against deleted code.
Moving a thousand lines into the package is not a thousand-line reduction. Splitting an
oversized file improves structure but is not deletion; arbitrary fragmentation violates the
standards. Readable explicit loops may add lines locally while eliminating duplicated policy.
Do not delete features, behavior tests or useful diagnostics to improve the count.

## Evidence and limitations

The remote main refs below were checked with `git ls-remote` on 2026-09-29, approximately
01:21 UTC. Findings refer to these commits unless explicitly marked working tree.

| Repository | Remote main inspected | Local checkout at investigation |
|---|---|---|
| community-base | `7d5c5da74fbca881f5a5352b9449c001ed047162` | Detached `859b54c`, behind main, extensive local edits |
| AI-Shipping-Labs/website | `de0a857320f828d89ad2ad88f894a0813d32595a` | `0043e0c9d`, 37 commits behind main, substantial local edits |
| DataTalksClub/website | `cfc21a90b0b9a856dcfe7c6385a6bb39c8974ed0` | `6175c237`, behind main, substantial local edits |

The cross-site findings are source and plan analysis. Their research did not include an
application test suite, browser walkthrough, migration rehearsal, deployment verification or
production access. Verification of the subsequent issue-1842 cleanup is recorded separately.
Refresh the baseline
before implementation; the shared working trees contain other people's unfinished changes.

The roadmap reviewed is remote main, which already includes C5.2j, C5.2k, C5.4, A5.3 and D5.3.
Older analysis documents are dated evidence, not measurements of current code.

### Updated committed AISL reference

A later read-only delta review compared the initial AISL reference with current main
`9505beb904fd255607619d073c8ae6b0d3c7be28`, while DTC main was
`f143a19b7d5ef7b713c7b8139d01619f333961b6`. The six intervening AISL commits are visible in
[the committed comparison](https://github.com/AI-Shipping-Labs/website/compare/de0a857320f828d89ad2ad88f894a0813d32595a...9505beb904fd255607619d073c8ae6b0d3c7be28).
Use this committed reference for future parity fixtures; the original table above remains the
dated baseline of the first audit. Uncommitted Home/mobile work is still outside the reference.

| Committed responsibility | Current AISL behavior | Equivalence constraint |
|---|---|---|
| Home composition | Syllabus search, Current module card, and a separate next-live-session block when outside the current module replace the earlier next-action and separate deadline/live/help composition | Preserve this current AISL output; do not recreate the earlier composition or change DTC markup |
| Current module | Cohort schedule selects the module; without a calendar, selection follows the first incomplete core lesson | Keep schedule, completion and cohort selection policies explicit |
| Module progress | Aggregates core-unit completion, saved homework questions and one project deliverable; actions advance from lesson to deliverable to next module | DTC currently uses submission-based cohort progress; replacing it with question-draft progress would change behavior |
| Project selection | `cohort_projects` prefers cohort-specific attempts when any exist, otherwise unscoped course attempts | Test both sets present, fallback, no cohort and resulting progress; the old inclusive cohort-or-unscoped query is not equivalent |
| Sessions | Excludes ended series from the Home next step and exposes recording/recap actions for past sessions | Preserve series eligibility, action selection, URLs and timing in existing site policies |
| Module overview | Reuses the Home session/work row partials | This delta does not replace the reader shell/navigation or parser |

The final delta commit changes production-version metadata only; this source audit does not
independently prove a deployment. Earlier file counts and line references remain historical.

Additional backend candidates are pure ordered module selection/next-core traversal, module
progress aggregation over normalized completion facts, and next-session/action selection over
normalized schedule rows. Keep site collectors and policy adapters, including AISL's
required-before-bonus ordering and DTC's current submission progress. Each candidate needs
current-output parity tests and net-deletion accounting before adoption; none authorizes a
visible change, source-format conversion or schema cutover.

## Current overlap

AISL imports package Course, Module and Unit models while retaining a local course parser,
cohorts, enrollment, progress, access, homework and presentation. Its latest Home and reader
work must keep working without any appearance or interaction change.

DTC pins `v0.5.10` and installs curriculum, coursework and homework_steps. Curriculum and
coursework tables are import-only until its planned D5.2 cutover; its local domain code remains
live. DTC already adopted the shared homework stepper through #432 and has a member Home at `/`.
Reuse those existing capabilities while integrating AISL's established course experience.

## AISL reference and DTC parity comparison

Capture the latest intended AISL experience before implementation, distinguishing committed,
released and unfinished local work. The inspected main includes Course Home tabs, the module
reader shell, Home entry links and checklist skipping. These are reference behaviors to verify,
not proposals to redesign AISL. Resolve which local changes belong to that reference through
the existing site workflow; do not overwrite them or silently treat them as deployed.

| Area | AISL reference to compare | Preservation requirement |
|---|---|---|
| Course entry and Home | AISL's established learner entry and course Home organization | Keep DTC's member dashboard and all course actions reachable |
| Syllabus and reader | AISL's established hierarchy presentation, module context, breadcrumbs and navigation interactions | Preserve DTC cohort selection, flat canonical URLs and source identities |
| Homework | AISL's established save/resume and submission/review interaction using the shared stepper | Keep DTC validation, scoring, deadline policy and classic fallback |
| Learner state | Consistent completion, draft, submitted and review presentation where applicable | Keep distinct assessment lifecycles and all existing state semantics |
| Additional DTC features | Integrate with the adopted course experience | Preserve projects, peer review, leaderboards, certificates, registration, calendar, gallery and Wrapped |

Compare the reference with DTC's rendered journeys to identify common behavior and differences.
The table is a comparison map, not permission to change DTC's presentation. Consolidate equivalent
behavior behind each site's existing interface. Record differences that require visible changes
as unresolved parity work; this task's no-visible-UI constraint applies to both sites. Keep all
DTC-specific workflows and their existing placement.

Both sites therefore combine shared primitives with substantial local implementations. The
opportunity is to consolidate the repeated implementation behind their existing interfaces.
Installing more package apps without removing replaced code would increase the maintenance surface.

Evidence: AISL `content/models/course.py`, `content/models/cohort.py`,
`content/models/enrollment.py`, `content/models/homework.py`,
`content/services/homework_step_reader.py`, `content/sync_parsers/families/courses.py`;
DTC `website/settings/base.py:139`, `courses/views/homework.py:114`,
`courses/views/homework_steps.py`, `courses/services/member_home.py`.

## Prioritized refactoring candidates

The deeper, quantified [code retirement inventory](code-retirement-inventory-2026-09-29.md)
names exact files, known callers, replacement symbols, gross versus net estimates and
equivalence blockers. Its strongest immediate candidate is DTC's 490-line answer-crypto copy:
the package version already pinned by DTC has the same implementation plus one helper.
AISL also had an obsolete dispatcher; the first cleanup below removes 33 application lines
after completing its caller inventory.
These can precede broader tree/parser refactoring and do not require a UI or storage change.

| Priority | Candidate | Code simplification | What must remain identical |
|---|---|---|---|
| 1 | Repeated course tree traversal and lookup | Extract common ordered traversal and indexing functions; reuse from existing site services | AISL reference behavior, DTC cohort/route policies and stable source identity |
| 1 | Large site course views and import functions | Separate data loading, pure computation and side effects; remove repeated queries and branches | Template context, responses, transactions, authorization and side effects |
| 1 | Repeated homework and project state calculations | Reuse package calculations where equivalent; keep small policy adapters where behavior differs | Existing labels, states, deadlines, accepted answers and submission semantics |
| 2 | Local course parsing and import machinery | Reuse the shared document toolkit, validation and persistence primitives; remove duplicate implementations incrementally | All currently accepted source formats, identity matching, errors and sync results |
| 2 | Site homework adapters | Remove repeated conversion/validation logic already handled by the shared stepper | Site question/final fields, URLs, cohort selection, classic fallback and access rules |
| 2 | Repeated Studio/API service logic | Have existing handlers call the same domain service | Existing routes, request/response formats, staff permissions and staff UI |
| 3 | Compatibility wrappers and import aliases | Rewrite internal callers to one owner and remove wrappers only when all dependencies are accounted for | Public interfaces, persisted task names and migration history |
| 3 | Duplicate progress, enrollment and coursework storage | Adopt shared storage only through the existing compatibility and migration process | Every data value, relationship and feature, with unchanged site presentation |

Priority 1 offers useful reductions before a schema or source-format migration. Priority 3 is
more invasive and should not be the first refactor merely because it could delete more lines.

### Course tree and view logic

The package computes related tree shapes in `curriculum/models.py:198`, `:311`,
`curriculum/services.py:166`, public views and `curriculum/views.py:309`. The sites also
perform their own lookup and presentation preparation.

Extract ordinary functions for the genuinely common traversal, indexing and data loading.
During internal refactors, keep current view functions, URL dispatch and templates as callers.
If a common internal value is useful, adapt it to each view's existing context. Preserve DTC's
rendered course presentation while sharing equivalent services with AISL. A presentation
difference remains a documented parity gap under the current no-visible-UI constraint.
Do not introduce a registry, page-builder framework or persisted navigation model.

Before consolidating, compare behavior on nested modules, cohort placements, bonus units,
checklists and empty/archived cohorts. Where behavior differs, retain the difference in a
small explicit adapter. Changing course-wide progress to cohort-wide progress is not a refactor.

### Parsing and import

DTC's three repository-reader modules contain 2,596 lines on the inspected main:
`content_sync/course_repository.py` (1,608), `_v2.py` (795) and `_layout.py` (193).
The separate `_registration.py` (158) creates source registrations and needs its own replacement;
the earlier 2,754-line family total must not be treated as wholly disposable reader code.
`courses/services/curriculum_import.py` contains 1,497,
`curriculum_source.py` 229 and `course_family_identity.py` 53. AISL also retains a substantial
local parser in `content/sync_parsers/families/courses.py` despite using package models.

These are overlapping responsibilities, not a promise that all those lines can be deleted.
Start by extracting duplicate parsing, identity matching, validation and upsert operations into
the existing package layers. Keep site-only metadata and policies in adapters. Compare normalized
results and resulting database changes for identical inputs before replacing a caller.

A whole parser can retire only when the shared path accepts every input and preserves every
outcome the site currently supports. Source-format conversion belongs to the separately planned
D23/A7.3/D7.4 work; it is not required or authorized as a shortcut in this refactoring task.
Until that work actually lands, keep support for the live source formats.

The course ingest and webhook transport remain live callers:
`content_sync/course_repository_ingest.py:397` and `api/views/course_repository_webhooks.py:45`.
Rewire them only after the replacement reader is equivalent.

### Homework, projects and policies

Keep the current responsibilities: curriculum owns course primitives; homework_steps owns drafts
and interaction independent of assignment/scoring storage; coursework owns assessment services.
The optional stepper is useful while the sites retain different assignment storage.

C5.2j already provides homework state and accepted snapshots; C5.2k provides existing project
lifecycle rows. Reuse their pure calculations only where they preserve current site behavior.
Do not replace site markup, change badge labels or merge homework and project lifecycles.

A site adapter can disappear only after its question/final fields, URLs, access, cohort selection
and submission behavior have an equivalent home. Storage migration alone is insufficient.
Keep DTC's classic form fallback, AISL's access/grant rules and both project review modes.

### Wrappers and adjacent legacy code

AISL's `integrations/services/github.py`, `content_sync.py` and `content_sync_queue.py`
bridge persisted task names, source rows and logging. Simplify internal call chains first.
Retirement requires a task/source inventory and preservation of staff log functionality.

DTC's `scripts/build_public_projection.py` is 1,317 lines on the inspected main, not the old
plan's 3,377. Thirteen content parsers still import it as `builder`. Extract shared helpers or
remove its duplicated course parsing; do not delete the whole module. Likewise,
`courses/services/local_course_seed.py` still supplies local test data.

`course_management` carries mail, middleware and observability; `cadmin/legacy_urls.py` remains
mounted; `review_import` has workflow and CLI uses. They are not empty merely because their
names sound historical. Remove only code whose responsibilities have moved without behavior loss.

AISL purchase and Studio product-creation endpoints currently return 410. Preserve their existing
route/response contract in this task; a deprecated endpoint is not automatically dead code.
Historical purchase grants and webhook reconciliation remain functional requirements.

Keep the existing D13 constraint on SES/django-q retirement. Payments, sprints, CRM, book club,
site article models and DTC editorial functionality are not removal targets.

## Relationship to existing plans

The two deliverables are a course unification plan and internal code simplification toward shared
behavior. Visible UI changes and feature removal are excluded. The following maps those
deliverables to existing work; it does not amend or authorize every step of those issues.

| Existing work | Applicable refactoring scope | Boundary |
|---|---|---|
| C5.2j / C5.2k | Reuse equivalent learner-state and project computations | Preserve each site's current markup and behavior |
| C5.4 | Reuse common source/graph/read primitives | New source conventions and changed visible hierarchy are separate work |
| A5.3 / D5.3 | Remove duplicate hierarchy processing and share equivalent course behavior | Preserve both sites' UI, DTC route/cohort policies and every feature |
| A5.1 / D5.1 | Existing model/field inventories and migration groundwork | Keep site views/templates; full storage adoption still requires C5.3 and rehearsals |
| A5.2 / D5.2 | Existing deployment and migration constraints | Preserve both sites' presentation; no feature loss hidden in a route/view switch |
| A7.2b / D7.3 | Existing parser inventories identify duplicate implementation | Preserve live input support until the separately planned content conversion lands |
| A7.3 / D7.4 | External format-cutover dependencies for eventual parser retirement | Do not fold content conversion into a behavior-preserving cleanup |

The canonical DTC dependency remains D5.1 -> D7.3 -> D7.4. A refactor or a scratch fixture
proving one helper does not close any of those adoption issues. C5.3 remains the adoption-ready
schema gate. D22's deferred Studio/API registry unification remains deferred.

## Findings that must stay separate from refactoring

The research found possible behavior defects: AISL tab routes missing section arguments on the
inspected main (a local change supplies them), package top-level-only module lookup, limited
nested projections and an archived-cohort empty-placement fallback contrary to D40.

These are compatibility obstacles and separately tracked bug/feature work, not justification
for silently changing behavior during cleanup. If a proposed shared replacement cannot preserve
a site's existing behavior, keep the current implementation until the prerequisite is resolved.
Record known defects in the baseline instead of treating their fixes as simplification evidence.

## Execution order

1. Choose one duplicated responsibility and record the exact baseline commit and active callers
   in all three repositories. Account for concurrent local work before selecting the implementation
   checkout. Inventory the current observable behavior using existing tests and representative fixtures.
2. Extract the smallest common computation or service without changing callers' interfaces.
   Use explicit adapters for real site policy differences. Prefer existing package modules over
   a new framework, class hierarchy or configuration system.
3. Replace one caller at a time in the internal refactor, leaving templates, URLs, CSS, JavaScript
   interactions and response contracts unchanged. Preserve query/transaction and side-effect
   behavior. Use a tagged package release for real site adoption changes under P15.
4. Compare the old and replacement outputs on representative inputs, including errors and edge
   cases. Validate rendered output when a view's context changes internally. Keep comparison
   scaffolding in tests or temporary tooling, not as permanent dual runtime execution.
5. Remove the replaced code and its redundant internal wrappers in the same reviewable slice
   where safe. If persisted callers or data require staged retirement, name the remaining callers
   and the precise condition for removing the bridge.
6. Report net code reduction, removed duplicate owners and adapter size alongside verification.
   Stop the abstraction from spreading if adapters become as complicated as the code they replace.
7. Consider shared storage adoption after these lower-risk reductions, through the existing
   donor-compatibility, migration, rollback and deployment processes. It must preserve the current
   site interfaces and all features.

In parallel with the refactoring inventory, capture the AISL reference and map every DTC feature
to its existing workflow. Compare common course journeys and verify all DTC-specific journeys.
Share equivalent behavior as the prerequisites become available. Document the remaining visible
differences without changing them under this task's current constraint.

Each slice belongs to one repository and its established review process. The package uses PRs;
DTC follows its engineer/tester/PM gates and local merge flow. Data expansion, reader/writer
switch and table removal remain distinct steps where P6 requires them.

## Acceptance: preserved AISL experience, DTC parity and full functionality

For internal refactors, the criterion is less code with the same externally observable behavior.
For shared behavior adoption, retain AISL's established semantics where they already match DTC,
with all DTC features preserved. Do not claim complete experience parity from internal refactors
when visible or behavioral differences remain.

| Surface | Preservation check |
|---|---|
| AISL course UI | Same text, layout, controls, navigation, visible ordering and interactions; rendered comparisons confirm no redesign |
| DTC course UI | Same text, layout, controls, navigation, visible ordering and interactions; every existing feature remains usable |
| Internal refactors and staff UI | Same output and interactions before/after the refactor; staff interfaces stay unchanged |
| Routes and APIs | Same URLs, methods, statuses, redirects, JSON shapes and authorization; retain stable certificate URLs and calendar ICS identity |
| Source/import | Same accepted inputs, normalized values, stable IDs, validation outcomes and idempotent database changes |
| Enrollment and access | Same course/cohort selection, grants, tier/drip policy, registration snapshots and personalized caching |
| Progress | Same completion values, timestamps, denominators, checklist/bonus treatment and cross-cohort semantics |
| Homework | Same save/resume, conflict handling, final submit, accepted-answer review, scoring, deadlines and classic fallback |
| Projects | Same GitHub/commit submissions, deadline and pooled review modes, assignments, votes, scoring and results |
| Other course features | Leaderboards, complaints, certificates, Wrapped, sessions, gallery, staff repairs and API/CLI workflows remain available |
| Side effects | Same mail/job intents, transaction boundaries, idempotency and timing; no duplicate effects |
| Data and privacy | Same meaningful values and relationships; merge, export and erasure still reach every moved relation |

For deletions, apply P17's full caller analysis, including all Python import forms, aliased
attribute access, Django string references, templates, task strings and migration dependencies.
A missing grep hit or smaller test count is not evidence that removal is safe.

Run meaningful tests for the changed responsibility, package quality gates and both consumer
checks under P16 where package code changes, using disposable consumer checkouts. Follow each
site's test scope and deployment process. Report package, AISL and DTC results separately.
New checks must execute nonempty cases and demonstrate they catch an actual regression.

Not run here, needs: implementation of the remaining cross-site refactors and DTC adoption,
their behavioral comparison fixtures and rendered-output checks, and migration/deployment
evidence if storage changes. None is inferred from source analysis. The separate AISL cleanup
verification is recorded below.

## First implementation slice

The owner selected AISL-only implementation for now, in a separate worktree because another
agent is working on the shared checkout. AISL issue #1842 tracks the first bounded course
backend cleanup. Its branch is `worktree-agent-1842`; the leased worktree is
`/home/alexey/git/ai-shipping-labs/.claude/worktrees/agent-1842-course-simplification`.
Keep the changes there for coordination; no merge/push into the peer's ongoing work this session.
The peer explicitly reserved course Home, current-module, commitments, module-home, navigation,
Home/module views and the mobile/template work. The course parser/dispatcher is free.

For the later DTC track, start with answer-crypto consolidation against its already pinned package implementation.
Preserve the shared class/exception identity and existing import contract, reuse authoritative
behavior tests, and remove the duplicate body. AISL's obsolete dispatcher has now passed a
caller scan of 2,965 Python files; its removal deletes 33 application lines. Baseline and
post-change focused course-sync checks each passed 34 tests. The engineer's affected Django
stage passed 5,377 tests with 10 skips, and core Playwright passed 993 tests. Independent QA
also passed 5,377 Django tests with 10 skips and 993 core Playwright tests (59 warnings).
Its lint check passed, and `make run` booted successfully with HTTP 200 at `/`.
[Independent QA](https://github.com/AI-Shipping-Labs/website/issues/1842#issuecomment-5883029820)
and [PM acceptance](https://github.com/AI-Shipping-Labs/website/issues/1842#issuecomment-5883036148)
approved the final diff. The engineer committed it locally as `38ced7470695eed3de2d08dc3596f586061dfa2b`
(`Remove unused course sync dispatcher`); the worktree is clean. No merge, push or deployment
was performed. The slice preserves active behavior without entering the traversal refactor,
where required-before-bonus ordering already differs between site and package.

Next, reuse the released project-row calculation when parity is proven, and consolidate
traversal with explicit existing ordering policies. No UI change, feature reduction or
source-format conversion belongs inside these internal refactoring slices. Prepare the AISL
reference and DTC parity inventory alongside them. Share equivalent implementation behind existing
interfaces and retain a clear inventory of any parity gaps that require visible changes.

The owner also requested a separate coordination subtask: involve the AISL peer, document
intra-workspace and cross-workspace aplexer communication, and implement improvements. The
`send --enter` submission fixes and cross-workspace durable replies are committed as `2f09c02`
in a separate aplexer worktree and installed locally. Automatic submission was verified with
actual Codex and Claude sessions. See
[the coordination evidence](aplexer-coordination-2026-09-29.md) and the reusable
`../.agents/skills/a2a-communication` skill. This does not change AISL's application scope.

## Subsequent implementation slices

Snapshot: 2026-09-29. Pending checks below are not completion evidence.

| Slice | Current implementation | Remaining gate |
|---|---|---|
| AISL #1843 | One identical module-unit sync call replaces two branch copies; accepted local commit `8dbf63e` removes 14 net application lines | Engineer and independent QA passed 114 focused tests, 5,377 affected Django tests with 10 skips and 993 browser tests; PM accepted; merge/push remains held by AISL integration ownership |
| DTC #438 | Removes the 490-line answer-crypto duplicate and rewrites callers to the public API already pinned in v0.5.10; five changed files, no pin change | QA and PM accepted `8065533`; merge `f143a19` pushed and CI passed; development migration failed before service updates, issue reopened |
| Package C3.2a / #316 | Pure public persona renderer extracted and documented; existing private aliases preserved; PR #317 merged as `7e5c5f8`; release PR #318 merged as `be31364` and v0.5.14 published | Release PR and exact merged-main checks passed under P16; published wheel verified; this extraction alone is not a net site deletion |
| AISL #1844 | Accepted local commit `ba8f0194` replaces three persona-rendering helpers with the public API and exact v0.5.14 pin; 87 site application lines removed | Independent QA passed 49 focused tests, 3,171 scoped Django tests (9 skips), 3,904 core Django tests (19 skips), 992 browser tests, lint and HTTP 200 boot; PM accepted; integration hold remains |
| DTC #439 | Removes the 145-line answer-check duplicate and updates two production plus eight test imports; scoring and all side effects remain site-owned | Focused before/after checks passed 50 tests and 45 subtests, plus five package/site parity tests; candidate frozen behind reopened #438, with broad verification and review still required |

DTC #438's original engineer run completed successfully, but an aborted tester setup overwrote
some selector artifacts and the evidence-validation log in its default output directory.
The original report now fails digest validation and must not be reused as a valid evidence
envelope. Independent QA used a separate directory and fresh execution for every required gate.
Its validated final report, cited below, supports acceptance; the overwritten historical
artifacts remain invalid and their hashes were not repaired.

The [DTC QA report](https://github.com/DataTalksClub/website/issues/438#issuecomment-5883603403)
records fresh validation of all required components: focused 23 tests with 45 subtests, 4,146
Django tests with 6 skips, 30 browser smoke tests, quality and evidence-validation checks of
670 tests each, and 13 container assertions. No component reused historical evidence.
[PM acceptance](https://github.com/DataTalksClub/website/issues/438#issuecomment-5883618613)
approved the unchanged five-file candidate. The local integration merge's tracked tree exactly
matches that commit; it lives in a separate clean clone under the issue worktree's `.tmp/`.

[Package on-call evidence](https://github.com/DataTalksClub/community-base/pull/317#issuecomment-5883620374)
records 2,271 package tests and 17,714 AISL tests in each baseline/linked run, both with 25 skips.
DTC executed 4,146 tests in each baseline/linked run. Its raw baseline had a missing-history
Gate B error and its linked run had two seal failures caused by the P16 local dependency link;
the normalized P16 comparison found no new package failures. Do not describe those raw DTC
runs as wholly passing. The package PR merged after all required CI jobs returned success.

[Release PR #318](https://github.com/DataTalksClub/community-base/pull/318)
passed package and consumer checks before merging. Tag `v0.5.14` points to merge commit
`be31364880466836dc5ed7e9eb38d10f8243944a`; its tracked tree equals the reviewed release
candidate. The release workflow succeeded, and the downloaded wheel's version, pure renderer
and public re-export were verified. The new main commit's package, plan and consumer checks
passed; the [terminal report](https://github.com/DataTalksClub/community-base/pull/318#issuecomment-5884372497)
records the same raw DTC/P16 qualifications described above. This release does not waive donor migration gates
or complete broader onboarding adoption. AISL #1844 owns only the pure renderer replacement,
its focused tests, and the exact package pin and lock update.

DTC #438's [development deployment](https://github.com/DataTalksClub/website/actions/runs/36522190231)
passed its tests, exact-commit CI verification and image publishing, then failed during schema
migration with task exit 21 before either service changed. Its underlying exception is not in
the workflow log. The configured investigation role is denied `logs:GetLogEvents` for the named
development migration stream; the redacted traceback has been requested. No migration, model,
schema or pin changed in #438, but that alone does not establish the cause. The owner's later
DTC rebuild authorization permits a fresh development schema recovery without claiming that
the original failure was diagnosed. Deployment success still requires fresh verification.

AISL's parser commits remain local while Home/mobile ownership and integration sequencing are
reserved. Shared dirty main checkouts remain untouched. DTC #439 remains uncommitted and frozen
until #438's deployment prerequisite is resolved.

AISL #1843's [independent QA](https://github.com/AI-Shipping-Labs/website/issues/1843#issuecomment-5884422672)
and [PM acceptance](https://github.com/AI-Shipping-Labs/website/issues/1843#issuecomment-5884442412)
approved the one-file parser change. Commit `8dbf63edb6cd02be3984a6170bb40a5ea349dfd1`
contains exactly 12 inserted and 26 removed lines in `content/sync_parsers/families/courses.py`.
The worktree is clean; its active lease and integration hold remain in place. The QA boot check
returned HTTP 200 and its server was stopped before handoff. This is local acceptance, not a
merged or deployed change.

AISL #1844's [independent QA](https://github.com/AI-Shipping-Labs/website/issues/1844#issuecomment-5885408718)
and [PM acceptance](https://github.com/AI-Shipping-Labs/website/issues/1844#issuecomment-5885425654)
approved commit `ba8f0194bfe9f839aadf197b021f18e6d403e4a7`, parent
`9505beb904fd255607619d073c8ae6b0d3c7be28`. Its five-file worktree is clean and remains
local. The original independent browser run passed all 992 cases after waiting for the
mobile-polish capacity holder; it was not restarted or admitted through an override.

The [final combined-main package report](https://github.com/DataTalksClub/community-base/pull/321#issuecomment-5885162769)
verifies `f35acecd2a95f34920433c71b7c0b649c0eeec4e`: plan and CI passed, including 2,271
package tests; both consumer jobs passed under P16. AISL baseline and linked runs each passed
17,714 tests with 25 skips. DTC baseline and linked runs each executed 4,146 tests, retaining
the raw historical-checkout/seal errors and normalized no-new-failure qualification above.
PRs #319 and #321 merged the completed C3.2a status and this proposal's initial evidence snapshot.
Later local evidence updates and issue comments do not imply another package release.

Measured application reduction across the accepted slices is 607 physical lines: DTC #438
removes 490, AISL #1842 and #1843 remove 33 and 14, and the renderer pair removes 70 after
subtracting 17 added package application lines from 87 removed AISL lines. This excludes tests,
documentation and version/lock metadata. It does not count the unaccepted #439 candidate.
Acceptance is not deployment: the three AISL commits remain local, DTC #438's development
deployment remains blocked, and full course-experience parity is not established.

## AISL integration ownership handoff

The course-Home release session adopted branches `worktree-agent-1842`,
`worktree-agent-1843` and `worktree-agent-1844` at the three accepted commits above.
All three worktrees were clean at handoff, with no additional AISL source changes.
The receiving session acknowledged `AISL-TAKEOVER-1842-1844-20260929` in durable
message `01a0ec70-29b6-7100-8ef8-5304f8a9b6a7`, replying to handoff
`01a0ec6f-fd26-7c41-b995-25846b2742c8`. It owns cherry-picking onto current main,
preserving the exact v0.5.14 pin/lock, reviewing behavior and running integration gates.
This session will not edit or push the transferred AISL worktrees. Landing SHA and
development outcome remain pending the receiving session's report; ownership transfer
is not evidence that integration or deployment passed. DTC #438 and #439 remain separate.

### Receiving owner's completed integration report

The receiving owner subsequently closed all three AISL issues and recorded the landed commits:
[#1842](https://github.com/AI-Shipping-Labs/website/issues/1842#issuecomment-5889091003)
as `b8c611216`,
[#1843](https://github.com/AI-Shipping-Labs/website/issues/1843#issuecomment-5889091325)
as `b5882cf1463797de43d1104304c6a10d75c2720f`, and
[#1844](https://github.com/AI-Shipping-Labs/website/issues/1844#issuecomment-5889091725)
as combined tip `ee28c82ca`. The exact v0.5.14 package pin and lock were retained.

The owner's combined-tree verification passed 6,899 selected Django tests (14 skips),
3,904 core tests (19 skips), and 992 browser tests, plus lint and migration drift checks.
After integration rebases, the owner reran 6,998 selected tests, the 3,904 core tests,
five affected browser cases, and finally 56 focused sync tests. The reported development
workflow `36558355740` succeeded and `/ping` returned `20260929-110754-ee28c82`.
These are the receiving owner's reported integration results; this session did not repeat
the tests or change the transferred worktrees. This supersedes the earlier local-only status.

The adopted parser change preserves one blank line and adds parent/leaf overview coverage.
Its application diff removes 13 net lines rather than the original candidate's 14. The landed
combined application reduction is therefore 606 lines, while 607 above describes the original
accepted candidates. DTC's 490-line portion is merged but still awaits successful development
recovery. Package issue #316 is now closed against its merged/released renderer evidence.

## DTC recovery implementation and revised adoption plan

DTC #440's [independent QA](https://github.com/DataTalksClub/website/issues/440#issuecomment-5892100560)
and [PM acceptance](https://github.com/DataTalksClub/website/issues/440#issuecomment-5892163409)
approved the guarded development-only reset capability. Engineer commit
`6b4e88af7086b52debe21536f7354f012c42a675` was integrated and pushed as
`25af29194fd82134ce12cfa84c8d70f229894d02`. The P18 preview and both commits share tree
`f3b5adb89e7c95337016828b8f8ba98405723d61`; the shared main checkout was not modified.

Independent verification passed 688 quality tests, 4,146 Django tests, 30 browser smoke
tests and 13 container assertions. Five PostgreSQL cases and a separate migration-reset-migration
rehearsal passed on disposable local databases. Test skips and expected failures are enumerated
in the QA report; none substitutes for the required reset proof. No render inputs changed.
An AWS stop failure remains an explicit unresolved recovery outcome with observed service counts;
the controller never claims services stopped when it cannot verify that state.

The [integration handoff](https://github.com/DataTalksClub/website/issues/440#issuecomment-5892199314)
assigns a single on-call owner to CI `36582025253` and ordinary Deploy Dev `36582025304`.
CI passed; ordinary deployment failed at the migration step with exit 21. The underlying
migration exception remains unverified. #439 remains frozen pending development recovery.

[Plan PR #322](https://github.com/DataTalksClub/community-base/pull/322), commit `85c6504`,
implements the reviewed D5.3/D5.1/D5.2 criteria amendment and merged as `3449643dc5061676586911efb4a9c0c7d3e7a2c6`.
Its local plan check covers 174 issues; all four required CI checks passed. AISL baseline and
linked suites each passed 17,764 tests with 25 skips. DTC baseline and linked suites each ran
4,146 tests with raw Gate B/seal failures; P16 found no new package failures after normalization.
That consumer verdict does not mean the raw DTC suites were entirely green. DTC issues #414,
#415 and #436 now carry the merged criteria. The fresh
DTC target needs an explicit intended public content inventory and approved import coverage,
not reproduction of discarded historical rows. Existing source sync covers only repository-authored
content; CMP-only campaigns, projects and cohorts are not automatically restored. A missing
import path for a supported feature blocks adoption, while synthetic learner fixtures prove
protected workflows without importing private legacy data.

### Failed drain and development outage

The single confirmed reset dispatch, run `36583816114` at `25af291`, failed during drain.
Its receipt records `reset.mutation_may_have_begun=false`: no schema SQL or reset migration
task ran. Recovery attempted to restore the recorded service definitions and desired counts,
but web remained desired 1, running 0; worker remained at 0. The public development endpoints
returned HTTP 503. No second reset was dispatched.

After the owner reopened AWS Gate, the sole on-call operator obtained
[ECS evidence](https://github.com/DataTalksClub/website/issues/440#issuecomment-5892863037):
the previously running web task stopped cleanly during drain. Replacement tasks using
`website-dev-web:22` cannot pull its missing ECR digest,
`sha256:9ae642f9861d1f5647b8c268a9e5c6b13fb7776381cc59757a34e9e07ffefcfd`.
This explains the outage and failed restoration. The investigator role cannot describe ECR
images. Recovery requires a verified pullable image compatible with the unchanged pre-reset
schema; the current unpromoted image is not assumed compatible. Restoration remains open.

The [follow-up timing evidence](https://github.com/DataTalksClub/website/issues/440#issuecomment-5892968410)
shows ECS declaring the service steady before its old task reached `STOPPED`. This strongly
supports the task-quiescence check as the drain refusal; the controller suppressed the exact
exception, so the attribution remains an inference. A separate read-only diagnostic workflow
candidate was deferred after Gate reopening supplied ECS access.

The scoped fix in `dev-drain-wait-440` captures validated service-owned task identities before
drain, waits for actual termination, then retains the authoritative website-writer check.
The [engineer report](https://github.com/DataTalksClub/website/issues/440#issuecomment-5893324093)
records 48 focused tests, 707 quality tests, 4,146 Django tests, 30 browser smoke tests and 13
container assertions passing, with skips and expected failure qualified in that report.
[Independent QA](https://github.com/DataTalksClub/website/issues/440#issuecomment-5893595557)
and [PM acceptance](https://github.com/DataTalksClub/website/issues/440#issuecomment-5893627698)
accepted the frozen source. All six executable verification components were rerun; none reused
historical evidence. The original full engineer plan was overwritten, so its exact byte-level
difference from the tester plan is not proven. The source hashes, manifest and recorded plan
fields matched, and the complete fresh tester evidence passed independently.

Engineer commit `49ae06f29f1c2014fe006c120781120dbbc119dd` was integrated and pushed as
`19e7393489b7158c30bae39f93915a1219f2c757`. The accepted candidate, P18 preview and merge
share tree `59ebed549d1548e16e901bbab2f44ec65e4e6be3`. The
[integration report](https://github.com/DataTalksClub/website/issues/440#issuecomment-5893668834)
assigns one on-call owner to CI `36592972904` and ordinary Deploy Dev `36592972929`.
[The terminal report](https://github.com/DataTalksClub/website/issues/440#issuecomment-5893918445)
records exact CI success and ordinary deployment failure at migration exit 21 before service
promotion. The new image was published but not promoted. The migration log read is still denied
by IAM despite Gate reopening; scoped access is tracked in
[aws-infra #62](https://github.com/DataTalksClub/aws-infra/issues/62).

The [corrected diagnostic addendum](https://github.com/DataTalksClub/website/issues/440#issuecomment-5894011899)
confirms the actual migration task has the proper hostname environment. A temporary hostname
hypothesis came from an unused builder and was withdrawn without code changes (#441 closed).
A synthetic missing-static-manifest error disappeared after collecting static assets; it is not
evidence of the live exception. No second reset or recovery promotion has run. The development
outage remains unresolved, and #439 stays on hold.

### Package form-error preservation before the next DTC pin

[PR #325](https://github.com/DataTalksClub/community-base/pull/325), head `99fedb25d992c99d663ba548a69c7d09f188771d`,
merged as `eab5b24f240315b2a35ef3eb866cb8f3eb446226`. It fixes #324: final homework fields display attempted input after invalid URL and stale
revision errors, while persisted answers and revision remain unchanged. The two regression
tests failed before the two-line correction and passed afterward. The package suite passed
2,273 tests against a measured baseline of 2,271. The
[on-call report](https://github.com/DataTalksClub/community-base/pull/325#issuecomment-5893309863)
records all four required CI checks passing. AISL baseline and linked runs each passed 17,764
tests with 25 skips. Both DTC runs executed 4,146 tests with the recorded raw Gate B/link-seal
failures; normalized new package failures were zero. The merge tree is the reviewed P18 tree
`57b718a95782e5a2a40fb61fdff4211dd4a04cbe`.
The DTC pin stays at v0.5.10 until the fix is merged, released and verified through the site
adoption process. Neither package capability nor this bug fix establishes full course parity.


[Release PR #326](https://github.com/DataTalksClub/community-base/pull/326) prepares v0.5.15
at `9289fae17c001ec546c026939f32ae3696d97524`. It changes only release metadata and the
changelog. Local package checks passed 2,273 tests; all 56 migration paths and blobs match
v0.5.14. D33 permits this release train to carry the unchanged provisional migrations, with
the existing adoption warning retained. [Required CI passed](https://github.com/DataTalksClub/community-base/pull/326#issuecomment-5894116216),
and the PR merged as `82d2c1aea982a0b241b55ea2219b5e54482fd638`; the actual tree matches
the reviewed P18 result. Tag [v0.5.15](https://github.com/DataTalksClub/community-base/releases/tag/v0.5.15)
was published by successful Release run `36596355284`. The downloaded wheel has SHA-256
`8328171d100fa67e4efd3439b2819847b3184d590173f26f5af04ba78d1c3858`; its version, attempted-field
fix and unchanged migration payloads were verified. The adoption-provisional warning is in the
changelog and release notes. #324 is closed; [STATUS-only PR #327](https://github.com/DataTalksClub/community-base/pull/327)
records C5.2ja completion and is still awaiting its own gates. No DTC pin was updated.

PR #326's AISL consumer runs captured `a004fdfb4d0f7486f0c22d21b017ef7bb2ceff39` and each
passed 17,794 tests with 25 skips. DTC captured `25af29194fd82134ce12cfa84c8d70f229894d02`,
before its later main advance; each raw suite ran 4,146 tests with the documented Gate B/seal
failures, 16 skips and one expected failure. P16 normalized new failures were zero. Subsequent
main/tag consumer checks have their own on-call observer and are not implied by this PR result.


### DTC package-pin compatibility audit

A read-only comparison of DTC `19e7393489b7158c30bae39f93915a1219f2c757` with package
`v0.5.10..9289fae17c001ec546c026939f32ae3696d97524` found that the site's own
`courses/templates/homework_steps/_stepper.html` overrides the package template. The new
package state labels, closed-review sections, public-links controls and project-row rendering
therefore do not automatically enter DTC's pages. Existing assignment descriptors retain
compatible defaults; the site still enforces eligibility through its fresh database check.

There is one concrete visible behavior difference to resolve before claiming pin equivalence:
new homework state comparison sorts checkbox selections, while v0.5.10 compares their lists
directly. Reordering otherwise equal selections now suppresses the pending-draft banner.
Keep the current pin until this is addressed under the no-visible-change requirement. This
audited difference does not justify changing either site's templates or broadening this refactor.

Before adoption, DTC-specific regressions must verify attempted final-field values on 400/409,
unchanged persisted drafts/revisions/submissions, and the checkbox-order status message using
its actual template override. Existing homework browser flows and desktop/mobile screenshots
remain required. Package tests alone do not establish these site results. The frozen #439
answer-check deletion uses the existing v0.5.10 API and needs no pin update.


### Reconcile C5.4 without adopting visible changes

A second read-only review compared PR #311 head `09d7940f` with main `eab5b24`.
None of its three implementation commits is independently suitable for this task:
`af3c1b5` changes graph construction and source acceptance, `cfbde84` combines persistence
with routes/API/HTML, and `9623458` activates homework rewriting alongside schema additions.
Newer main homework, project-row and persona changes must survive reconciliation.

The first reviewable slice is course-wide Unit identity preservation during source moves.
Extract only `curriculum/importing.py` lookup/reparenting and deferred stale cleanup from
`cfbde84`, adapted to the existing graph. They must land together: module-by-module deletion
can erase a moved Unit before its destination is visited. Keep all current parser entry points,
schema, routes, APIs and rendering. Required evidence moves a Unit in both traversal directions,
including unchanged content, preserving its PK and progress/homework/submission links; repeat
import stays unchanged, genuine removals still work, and duplicate identities reject before writes.
Implementation ownership has not been released by the existing draft owner.

Later slices, each separately reviewed:

| Slice | Capability | Preservation boundary |
|---|---|---|
| Source trees | Parse physical repository trees using the existing document reader and identity checks | Preserve existing parser entry points and `ModuleGraph(units=..., children=...)` callers |
| Recursive graph | Mixed sibling ordering, ancestor rules and backend projection | Keep one stored graph representation; retain existing flat-input acceptance and return contracts |
| Tree import | Apply recursive modules and units transactionally | Preserve identities; do not activate homework synchronization yet |
| Structured homework parsing | YAML descriptors and Markdown companion resolution | Do not add fields to every existing serialized document or expose correct answers |
| Bound homework persistence | Final fields, question labels and explicit homework import | Reject UUID/slug conflicts; establish scoring ownership before clearing or changing any answer envelope |

The draft's public view, URL, API serialization and template changes stay outside these slices.
Its graph constructor replacement and mandatory explicit order would break current callers or
valid inputs. Its homework importer unconditionally clears answer envelopes; that behavior must
be reconciled before activation. New materially changed code must meet the current function/file
limits through cohesive responsibilities, without arbitrary fragmentation. Ownership agreement,
package tests and both consumer gates remain prerequisites to integrating an implementation.


### Latest AISL reference and self-paced coursework follow-up

A fresh committed-source comparison on 2026-09-29 records AISL main
`e1749fbcff95256a361151267a1af8860944f4f7`, 59 commits after the earlier `9505beb9` reference.
This updates the source reference, not the initial audit's historical measurements. Read-only
comparison did not modify AISL or establish a new live-browser verification result.

The intervening work includes mobile presentation, cohort selection and current-module changes,
cohort event-series diagnostics/linking, and self-paced calendar presentation. The exact committed
self-paced change is [3c809dda](https://github.com/AI-Shipping-Labs/website/commit/3c809dda9007c1bcdb9bcb1b74e0c35fc093ddd0).
Its `is_self_paced_view` requires a self-paced selected cohort and no preferred dated enrollment;
merely possessing the automatically created self-paced enrollment is insufficient. In that view,
commitment rows retain homework/project status while clearing date presentation, event rows are
empty, and the sessions route redirects to Home. Preserve the dated-enrollment precedence in any
future shared behavior. This task does not copy those presentation changes into DTC.

[Package #323](https://github.com/DataTalksClub/community-base/issues/323) records separate shared
coursework gaps: local SES template keys, duplicate pooled-review messages, backlog batch formation,
self-paced date handling and immediate answer reveal. They are not solved by v0.5.15, nor by AISL's
presentation change. Changes to notification policy, scoring, scheduling or reveal need their own
reviewed contracts; do not silently include them in a behavior-preserving cleanup.

One existing compatibility defect has an isolated next step:
[C5.2ga / #329](https://github.com/DataTalksClub/community-base/issues/329) aligns template-key
validation so coursework's existing dotted purposes work through both shared mail backends.
Relay already accepts dots; `ses_local` rejects them before its override loader or file template.
The slice preserves purpose names, templates and notification policy, uses fake SES in tests,
and makes no site, provider or UI changes. Its implementation and consumer gates are still pending.
