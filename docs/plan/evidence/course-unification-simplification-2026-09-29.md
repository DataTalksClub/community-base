# Course experience unification and code simplification proposal

Date: 2026-09-29. Researched in parallel by three Sol agents, one for each repository,
and reconciled by the orchestrator. Revised following the owner's clarifications:
"don't change anything in ui and don't remove features. I want code simplifications", and
"I worked for quite some time on aisl courses and I want DTC to have the same experience".

Status: the cross-site unification remains a proposal with focused implementation slices
tracked below. AISL's first cleanup is independently verified and locally committed; DTC's
crypto consolidation passed review and CI but its development deployment failed. The public
renderer is released, and AISL's isolated adoption includes a tagged dependency update.
No database schema changes belong to these simplification slices.
AISL's established course experience is the reference to preserve and bring to DTC. The work
does not design a new course experience or remove features. Existing phase issues remain
unchanged; their broader scope is not implicitly authorized by this proposal.
The active implementation constraint is no visible UI changes in either site. Experience
unification proceeds through shared equivalent behavior; remaining differences stay documented.

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
- Preserve data, stable identities, history and side effects, including notification timing.
- Remove implementation code only after proving that its behavior has an equivalent replacement,
  or that the code is genuinely unreachable and supports no feature or external contract.

Keep intentional policy differences explicit: DTC has no paid tiers, while AISL retains its
access and enrollment integrations. These differences do not require separate implementations
of the common course experience. Public presentation remains site-owned under D18; share the
underlying behavior so bringing AISL's experience to DTC does not create another large code fork.

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
| AISL #1843 | One identical module-unit sync call replaces two branch copies; 14 net application lines removed in its isolated worktree | Engineer passed 114 focused tests before/after, 5,377 affected Django tests with 10 skips and 993 core browser tests; independent QA is running, then PM acceptance |
| DTC #438 | Removes the 490-line answer-crypto duplicate and rewrites callers to the public API already pinned in v0.5.10; five changed files, no pin change | QA and PM accepted `8065533`; merge `f143a19` pushed and CI passed; development migration failed before service updates, issue reopened |
| Package C3.2a / #316 | Pure public persona renderer extracted and documented; existing private aliases preserved; PR #317 merged as `7e5c5f8`; release PR #318 merged as `be31364` and v0.5.14 published | Release PR checks passed under P16 and published wheel verified; latest main consumer run still pending; this extraction alone is not a net site deletion |
| AISL #1844 | Three duplicate persona-rendering helpers replaced by the public API in an isolated worktree, with exact v0.5.14 pin | Byte-exact catalog/provider baselines and 49 post-edit focused tests passed; site gates, independent QA and PM acceptance remain |
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
and public re-export were verified. The new main commit's package and plan checks have passed;
its separate consumer run remains pending. This release does not waive donor migration gates
or complete broader onboarding adoption. AISL #1844 owns only the pure renderer replacement,
its focused tests, and the exact package pin and lock update.

DTC #438's [development deployment](https://github.com/DataTalksClub/website/actions/runs/36522190231)
passed its tests, exact-commit CI verification and image publishing, then failed during schema
migration with task exit 21 before either service changed. Its underlying exception is not in
the workflow log. The configured investigation role is denied `logs:GetLogEvents` for the named
development migration stream; the redacted traceback has been requested. No migration, model,
schema or pin changed in #438, but that alone does not establish the cause. Do not propose a
database fix or declare deployment success without the missing evidence.

AISL's parser commits remain local while Home/mobile ownership and integration sequencing are
reserved. Shared dirty main checkouts remain untouched. DTC #439 remains uncommitted and frozen
until #438's deployment prerequisite is resolved.
