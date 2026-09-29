# Code retirement inventory

Date: 2026-09-29. Supplement to
`course-unification-simplification-2026-09-29.md` after the owner requested a deeper parallel
audit, maximum code reduction without compromised UX, and adherence to all three coding standards.

This is an implementation proposal, not a deletion approval or completed refactor. Preserve
AISL's established course UX and bring it to DTC; retain all features. Measurements use the
same verified remote main snapshots as the parent proposal. Local working trees moved during
the investigation and contain concurrent work, so implementation must refresh the baseline.

## How to read the sizes

LOC means physical committed source lines, including blanks/comments but excluding test and
migration files. A file size describes exposure; it is not a deletion estimate. Net reduction
is deleted implementation minus replacement code and permanent adapters across all repositories.
The rows overlap where indicated and must not be summed into a total savings claim.

The source comparisons and caller reads are planning evidence. Complete P17's all-import-form
and dynamic-caller inventory on the actual implementation commit before deleting code.
No application tests, browser checks, migrations or deployments were run for the initial inventory.
Subsequent implementation and verification of row 1b are recorded in the
[course proposal](course-unification-simplification-2026-09-29.md#first-implementation-slice).

## Ranked bundles

| Order | Bundle and measured source | Replacement and retained code | Reduction assessment | Blocking condition |
|---|---|---|---|---|
| 1 | DTC `courses/homework_answer_crypto.py`, 490 lines | Package `coursework.answer_crypto`; direct imports or an explicit re-export of the same classes if the old module path must remain | Strong candidate: roughly 450–480 net lines, depending on the explicit export and test-patch contract. Actual diff must confirm | Pinned release equivalence confirmed; complete caller, exception/type identity and error/crypto checks |
| 1b | AISL parser predecessor `_dispatch_courses`, `content/sync_parsers/families/courses.py` | Already registered `CoursesParser`; retain the live parser and its behavior | Implemented in issue #1842 worktree: 33 application lines removed, no replacement application code | Caller inventory covered 2,965 Python files; independent QA passed 5,377 Django tests, 993 browser tests, lint and server boot. Local change only; no merge/deploy claim |
| 2 | DTC project row presentation in `courses/views/course_projects.py`, 144-line file | Pure package `coursework.project_rows.project_row`, released in v0.5.13; retain legacy queries and a small mapping into existing template attributes | Approximately 50–70 lines of repeated state/presentation logic are candidates, not the whole file; net depends on mapping adapter | DTC still pins v0.5.10; a pin update must preserve rendered behavior across intervening homework changes as well as project labels/classes/deadlines |
| 3 | AISL traversal in `content/services/course_units.py:435`, package traversal in `curriculum/services.py:166`; related helpers in `course_home.py` and `curriculum_compat.py` | Keep each current traversal and its query loader; defer a shared traversal API | Follow-up found no credible positive net deletion after preserving AISL's sibling ordering and both loaders. A small AISL-only reuse of one traversal may later remove repeated queries | AISL and package sibling order differs; AISL's `get_syllabus()` prefetch and reader/Home callers are reserved. Characterize order, navigation, progress and query count before any change |
| 4 | Package syllabus/placement/read projections in curriculum models, services, public views and API | Candidate common read helper, only if a larger equivalent responsibility is established | Follow-up at v0.5.14 found only 4–6 common selection lines; extracting that branch would yield zero reduction or growth | Bulk versus single-cohort query behavior and nested/archive projections differ; defer this extraction |
| 5 | DTC three repository readers, 2,596 lines; importer 1,497; source reader 229; family identity 53 | Package document toolkit, parser/import primitives; retain DTC metadata, cohort binding, transport and route adapters | Large delayed retirement candidate. Gross candidate files total 4,375 lines; full net unknown. The separate 158-line registration module is excluded | Accepted live formats, source identity, conversion sequencing and model adoption |
| 6 | AISL `content/sync_parsers/families/courses.py`, 2,586 lines; homework parser 346 | Shared parser/import owner with small site field/policy mapping | Large delayed candidate; partial internal consolidation can precede whole-file retirement | All source variants, rename/identity behavior, homework fields and import side effects preserved |
| 7 | AISL `content/curriculum_compat.py`, 768 lines | Direct use of package fields/services plus explicit site extensions; remove monkeypatching after callers migrate | Large ownership simplification; 768 is a gross upper bound, not immediate savings | Field/lookup/provenance compatibility, init/save behavior, URLs, instructors and progress |
| 8 | DTC homework scoring files, 192 + 78 lines; six project core files, 711; review assignment selector 175; leaderboard 84 | Shared coursework services after storage adoption, or small pure computation extraction before it | Substantial duplicated algorithms; whole-file removal remains gated. Net unestimated | Model identity, locks, observability, errors, cache invalidation and transaction parity |
| 9 | AISL questionnaires `onboarding_ai.py` 812 and `services_onboarding_ai.py` 888 | Existing package counterparts with site LLM/config/notification boundaries | Approximately 1,700 lines of site implementation exposure; full net and adapter size unknown | A3.3/C3.7/C5.3 compatibility, provider/config and persistence/notification equivalence |
| 10 | Site sync bridges, projection helpers, Studio/API duplication and course-platform shells | Single domain service behind existing interfaces; rewrite internal callers then remove empty bridges | Assess per symbol and caller. Directory size is not a deletion estimate | Persisted tasks, commands, tests, workflows, import consumers and live external contracts |

Rows 5 and 6 should not create another shared parser. Use the existing toolkit and retire
duplicate internals as they become equivalent. Source conversion is already separate planned
work; accepted authoring inputs cannot be removed to make a parser look smaller.

## Early bundle: answer crypto

DTC's 490-line module and the package's 510-line main module differ only by the package's
20-line `validate_source_envelope` function in the inspected snapshots. The common implementation
has no Django model dependency. This makes it an unusually strong candidate before storage
migration, UI adoption or source conversion.

The same comparison was repeated against DTC's actual pinned package tag `v0.5.10`
(`0c5045cf`): again, the only difference is the package's additional 20-line helper. A newer
package release is therefore not a prerequisite for this candidate on the inspected DTC pin.
[DTC #438](https://github.com/DataTalksClub/website/issues/438) now tracks this consolidation.
Its implementation deletes the duplicate module and rewrites all callers to the package owner.
Independent QA and PM accepted commit `8065533`; merge `f143a19` reached main and CI passed.
Development deployment then failed during migration before service updates. The issue is
reopened pending the underlying traceback; acceptance does not establish deployment success.

Do not combine this deletion with a package pin bump. Releases v0.5.11 and v0.5.12
include shared homework presentation changes, so a later DTC pin bump must inspect the
complete intervening change range and prove existing rendered behavior is preserved.
The no-visible-UI-change constraint applies to dependency updates as well as site edits.

Known live imports are `courses/homework_answer_checks.py:7` and
`courses/homework_answer_resolution.py:10`; `courses/models/homework.py:240` calls resolution.
Expand this to tests, scripts and dynamic references before removing the path.

One concrete test dependency is `courses/tests/test_homework_answer_crypto.py:48`, which patches
`courses.homework_answer_crypto.secrets.token_bytes`. Preserve that patch target if keeping the
old test interface, or move/update the deterministic behavior test to the new owner. A facade
that preserves production imports but breaks the existing authoritative test is incomplete.

Preserve class identity. `_require_keyring` uses `isinstance(..., HomeworkAnswerKeyring)`;
keeping two class definitions or subclassing the old exceptions is not equivalent to a direct
re-export. Preserve keyring selection, authenticated context, envelope parsing and exceptions.
Do not change DTC's keyring configuration as an incidental part of deduplication.

First DTC implementation slice:

1. Verify the exact package release pinned by DTC contains the equivalent implementation.
2. Locate the authoritative crypto behavior coverage; fill a real gap before replacing code.
3. Rewire imports to the existing owner, preserving any required old import path with direct
   explicit exports. Keep the site resolution/configuration layer.
4. Prove decrypt/encrypt interoperability, malformed-envelope errors, unknown-key behavior,
   authenticated-context mismatch and exception/type identity. Do not assert identical random
   ciphertext from repeated encryption.
5. Run `uv run --frozen python scripts/ci.py lint` and the current versioned verification
   contract's required checks; report actual net deleted lines.

Reuse existing code rather than modifying the oversized package crypto file just to relocate
imports. If the package implementation itself needs material changes, first split its cohesive
keyring, envelope and crypto responsibilities under the 300-line file/30-line function standard.

## Early bundle: project row calculation

Package `coursework/project_rows.py` is 246 lines and its pure `project_row` function is explicitly
independent of storage. DTC's view repeats state-to-label/class/deadline logic. The package's
`project_rows_for_cohort` builder queries package models and is not an equivalent replacement for
DTC's current legacy queries.

Keep DTC's `get_projects_for_course` query/prefetch behavior, `days_until_*` values and the
attributes its existing template reads. Adapt the pure row result into that context. Preserve
Closed/Open/Submitted/Review/Review completed/Passed/Failed labels and the exact review threshold.

Characterize CL/CS/PR/CO with and without submission, required-review counts below/at/above the
threshold, and the rendered row. Tests must include deadlines and link targets, not just badges.
C5.2k landed after the v0.5.12 tag; do not assume a site pin to that version includes it.

## Equivalence blockers discovered

These findings prevent an apparently simple replacement from silently changing the product.

| Candidate replacement | Difference | Required treatment |
|---|---|---|
| AISL course traversal -> current package traversal | AISL partitions child modules and units required-before-bonus, but keeps top-level sort order; package uses sort_order/pk throughout | Defer shared extraction: preserve actual order, query loaders and progress policies; no credible positive net deletion is established |
| AISL homework checks -> current package checks | AISL FLOAT is exact and EXACT_STRING case-sensitive; package allows 0.01 float tolerance and case-insensitive matching | Keep distinct assessment policy or support it explicitly; never change grades to simplify code |
| DTC homework scoring -> current package scoring | DTC uses legacy rows, emits started/failed/scored observability events and invalidates additional cache keys | Preserve model/data, events and cache behavior before retiring the old orchestration |
| DTC project scoring -> current package review service | DTC locks the Project row and handles InvalidCriteriaAnswerError; package lacks equivalent handling in the compared path | Prove transaction/concurrency/error parity; a successful happy-path score is insufficient |
| AISL questionnaires -> package counterparts | Different LLM backend/config wiring and completion-notification boundary | Keep provider identity and notification timing; follow the existing compatibility cutover |
| AISL inline course helpers -> generic navigation | `course_inline.py` encodes existing Buildcamp presentation/URL behavior and has view/template/compat callers | Preserve its visible result and routes before deleting the special-case implementation |

## Large-file restructuring is a separate metric

A read-only follow-up checked the package curriculum at released `v0.5.14`
(`be31364880466836dc5ed7e9eb38d10f8243944a`). `Course.get_syllabus` prepares a bulk,
two-query projection for HTML and API callers; `Cohort.effective_modules` returns one
cohort's module list for Studio and consumers. Their common placement-or-default selection
contains only about 4–6 gross lines. A helper and its calls would consume at least that much
code, so this is not an immediate deletion candidate.

The related `get_all_units_ordered` service walks nested children depth-first for navigation.
The current HTML/API syllabus projects top-level modules and their direct units. Sharing
their traversal would change observable behavior. Likewise, the parser records archived
cohorts with no placements, while the read models interpret no placements as the default
tree. The existing archive import test proves stored rows, not public output.

Before reconsidering a broader extraction, characterize nested, curated-cohort and archive
outputs in HTML and API, plus query counts. Existing model/service tests cover placement
selection and depth-first ordering, but the API progress test is flat. Keep any archive
behavior fix separate from a refactor. This follow-up ran no tests and changed no code;
it narrows row 4 rather than claiming a simplification.

Measured AISL files include course views 1,681 lines, `course_units.py` 888, `course_home.py` 421,
`course_commitments.py` 599, homework step adapter 331 and Studio course views 642.
They are candidates for cohesive splitting when materially changed, not wholesale removal.
The page enrollment and enrollment API already call `ensure_enrollment`; replacing both with
another abstraction would not remove a duplicated business rule.

Measured package files include curriculum models 836, views 413, parser 431 and importer 467;
coursework review 704 and leaderboard 346; homework step views 508. Size-standard compliance
must accompany material changes, but moving methods between files is not a net code reduction.

Retain template/route handlers that own real presentation or integration differences. A thin
adapter is preferable to a generic framework whose options recreate both old implementations.

AISL's course sync bridge bundle is 418 lines (`content_sync.py` 261,
`content_sync_queue.py` 143, `github.py` 14). Known callers include `sync_content` management
command, Studio sync views and API sync sources; the queue persists the dotted function name
`integrations.services.github.sync_content_source`. The 14-line facade must remain while that
name is still used by stored tasks. Removing it early saves little and breaks an actual contract.

Other DTC followups are `core/redaction.py` (283 lines) and the shared `RevisionedModel` logic
within `core/models.py` (633-line file). Redaction has broad callers and a security-baseline
script referencing the old module; compare edge cases and preserve its import contract before
consolidation. The model candidate is the shared revision base, not the whole file: DTC's
AuditEvent append-only queryset has a SET_NULL carveout explicitly excluded by D19. Abstract
base migration serialization and all consuming models need verification. Neither is part of
the course deletion estimate.

The course repository family needs a similar distinction: `course_repository_registration.py`
(158 lines) creates source registration and is not just another reader. Its behavior needs an
equivalent registration owner before it can be removed. Keep `course_repository_ingest.py`
(509 lines) for transport and `content/sync_parsers/course.py` (129 lines) for catalogue-copy
publication until their respective outputs and side effects have replacements.

## Cross-repository duplicate scan

An additional read-only scan parsed committed application Python files from the three inspected
refs, excluding tests, migrations, scripts, documentation and dependency/vendor directories.
It compared function argument/body ASTs after dropping docstrings, ignoring comments/decorators,
for functions spanning at least 20 lines. Counts were 384 package files, 959 AISL files and
668 DTC files; 36 groups matched across repositories.

The largest matches were AISL/package questionnaire functions, DTC/package crypto functions,
`RevisionedModel.save`, and redaction `_copy`. These matches identify investigation candidates,
not proven interchangeable functions: imports, globals, decorators, configuration and model
ownership can still differ. The scan deliberately makes no dead-code claim and no total
deletion estimate. P17 remains necessary on each actual deletion.

## Next bounded AISL parser slice

A further read-only review of the issue-1842 worktree found identical
`_sync_module_units(...)` calls in the parent and leaf branches of
`_sync_module_dir`. Both calls occur immediately after the module upsert, with
identical arguments. Issue #1843 now hoists one call above the branch and removes the leaf
`else`, with no new helper or dependency. Its measured diff removes 14 net application lines.
The parent pending-unit check and child recursion remain after that call;
mixed-content rejection remains before the upsert. The condition checks
an ordinary list, so the hoist does not move a side-effecting condition.

Existing leaf/README, nested-directory and reparenting tests provide the
baseline. Engineer verification passed 114 focused tests before/after, 5,377 selected Django
tests with 10 skips, and 993 browser tests. Independent QA passed the same test counts plus
lint and server boot; PM accepted local commit `8dbf63e`. It remains separate from issue #1842's
accepted diff and is not merged or deployed. Larger apparent duplicates in tree scanning differ in case
sensitivity, hidden-file handling and error reporting; keep those differences.

## Traversal follow-up: defer shared extraction

Read-only comparison used AISL main `9505beb904fd255607619d073c8ae6b0d3c7be28`
and package `v0.5.14` at `be31364880466836dc5ed7e9eb38d10f8243944a`.
AISL `content.services.course_units.get_all_units_ordered` walks its
`Course.get_syllabus()` prefetch and places required child submodules and units
before bonus siblings. Its docstring also claims required top-level modules
precede bonus ones, but the actual `get_syllabus()` orders top-level modules
only by `(sort_order, id)`. Preserve that observed order. The package
`curriculum.services.get_all_units_ordered` loads the tree separately and
keeps `(sort_order, pk)` order at every level. Neither traversal filters
checklist items or applies a visibility filter. Progress denominators differ:
AISL's `non_bonus_units` retains required checklist items, while the package
excludes every checklist item from course progress.

Both expose ordered units to next/previous lookup. AISL also uses its order
for reader position, next unfinished unit and Course Home orientation links.
A shared flattening helper would still need both query loaders and AISL's
required-before-bonus adapter. Replacing the short loops with that helper,
its calls and policy plumbing offers no credible positive net deletion;
an optional package policy would expand an already oversized package function
and bypass AISL's `get_syllabus()` contract. Do not add a dormant API while
AISL course-unit, Home and navigation ownership is reserved.

After that ownership is released, an AISL-only refactor could calculate the
ordered list once in `build_course_unit_navigation_context` instead of calling
next, previous and full-order helpers separately. This may reduce repeated
queries, but requires characterization before an implementation or net-line
claim. Existing authorities are AISL `test_curriculum_nesting_1674.py` for
depth-first, bonus and fixed-query behavior, `test_course_units.py` for
next/previous boundaries, `test_reader_mobile_progress_517.py` for positions,
and package `tests/curriculum/test_services.py::TestReadingOrder`. Add cases
for tied sort keys, bonus top-level modules, empty leaves, checklist items,
missing current units and unchanged rendered navigation before replacement.

## Public renderer prerequisite for questionnaire consolidation

A targeted follow-up compared AISL `questionnaires/onboarding_ai.py` on current main
`9505beb904fd255607619d073c8ae6b0d3c7be28` with its pinned package `v0.5.12`.
The three helpers `_shared_spine_prompts`, `_format_question` and
`_render_persona_catalog` have identical function ASTs: 82 function lines within an
87-line source block. Empty, singleton and multi-persona output probes also matched.
The subsequent implementation measures 89 removed and 2 inserted production lines: 87 net
site lines removed. Added behavior tests and the package API extraction are counted separately.

The prerequisite is now published in
[`v0.5.14`](https://github.com/DataTalksClub/community-base/releases/tag/v0.5.14), tagged at
`be31364880466836dc5ed7e9eb38d10f8243944a`.
[Package C3.2a / #316](https://github.com/DataTalksClub/community-base/issues/316)
established the supported pure API and exact-output tests; the released wheel contains the
public renderer. [AISL #1844](https://github.com/AI-Shipping-Labs/website/issues/1844)
implements direct adoption in its own worktree with an exact tag pin. Byte-exact catalog
and provider-prompt baselines passed before deletion; 49 focused tests passed afterward.
Independent QA also passed 3,171 scoped Django tests (9 skips), 3,904 core Django tests
(19 skips), 992 browser tests, lint and HTTP 200 boot. PM accepted local commit `ba8f0194`;
the clean worktree remains unmerged under the AISL integration hold. The package extraction
adds 17 application lines, so the combined renderer slice removes 70 net application lines,
excluding tests, docs and dependency/version metadata.

The complete onboarding implementation remains live. Site and package LLM backends,
exception identities, configuration and notification timing differ, so replacing the
whole module would change behavior. Preserve those owners while consolidating only the
identical pure rendering responsibility. No visible UI change belongs in either issue.

## Questionnaire service follow-up: retain the adoption boundary

A read-only comparison of AISL `9505beb904fd255607619d073c8ae6b0d3c7be28`
with package `v0.5.14` inspected `services_onboarding_ai.py` (888 site lines,
929 package lines). The largest matching responsibilities admit, fail and apply
turns, persist answers and finalize questionnaires. They use distinct site and
package model classes, managers and foreign keys. Replacing their calls before
model adoption would change which storage implementation owns the operation.
Site tests also assert the local turn/provider exception identities and patch
site service globals; matching function bodies alone do not prove equivalence.

The approximately 94-line bounded-call/iteration overlap is not an available
public replacement: the released package helpers are private and raise package
timeout exceptions, while site catch paths use site exceptions. Small hashing
and timing helpers do not establish a substantial separate retirement slice.
No safe replacement exceeding 100 net lines was identified through the released
API. Retain the C3.7/C5.3 compatibility and A3.3 adoption prerequisites for the
larger service move; finish the separately verified renderer slice first.
This review changed no application code and ran no tests.

## Definition of a completed simplification slice

- The existing behavior and affected UX have an authoritative baseline test.
- Shared behavior has one owner; permanent adapters have a documented site-specific purpose.
- The replacement follows the applicable coding standard, including cohesive size limits.
- The changed callers preserve UI, routes, outputs, policies, data and side effects.
- Old implementation bodies and unnecessary internal wrappers are actually removed.
- The report distinguishes net deletion, code moved, code split and temporary comparison tooling.
- Package and consumer verification is reported separately where required.

Prioritize the crypto slice, then the released project-row calculation where its parity is
confirmed. Defer shared traversal extraction; after ownership release, characterize the smaller
AISL-only opportunity to reuse one ordered list. Prepare the larger
parser, monkeypatch and storage retirements through their existing dependencies. Compare DTC's
course experience with the AISL reference while preserving both sites' visible UI. Share equivalent
services and document remaining parity gaps; maximizing deletion never authorizes visible changes
or dropping a feature.

The follow-up DTC answer-check slice is implemented in an isolated worktree as
[#439](https://github.com/DataTalksClub/website/issues/439). Its 145-line duplicate has a public
owner in the already pinned package. The candidate removes 145 net application lines while
retaining the 78-line score-calculation module and its side effects. Focused before/after checks
passed 50 tests and 45 subtests, plus five package/site parity tests. It remains uncommitted and
frozen behind #438's failed development deployment; broad verification, independent review and
acceptance are still required.

The receiving AISL owner has since shipped #1842, #1843 and #1844 together at `ee28c82ca`
and reported a successful development deployment with combined regression gates. See the
unification proposal's completed integration report for the evidence links. The adopted parser
diff removes 13 application lines after retaining a blank line; the total landed application
reduction across package/AISL/DTC is 606 lines. DTC's merged portion still awaits development
recovery. The owner's DTC rebuild permission is documented in the proposal; AISL data remains
subject to preservation and lossless migration requirements.


## Deployment-builder retirement rejected

A bounded follow-up at DTC `19e7393489b7158c30bae39f93915a1219f2c757` checked whether
`deploy/task_definitions.py` could be removed after it caused confusion during recovery.
It remains live: the active image updater imports its validation and configuration, while
`deploy.cli promote` and the manual CI deployment path still call its normalized builder.
Gateway/recovery code, tests and documented CLI contracts also use it.

The two writers have different responsibilities. The normalized builder requires an exact
fixed environment; the supported image updater preserves unrelated environment entries and
sets its owned fields, including the development hostname. Consolidating them without treating
those differences would change behavior. No deletion is justified by this audit. Removing the
older manual release contract is functional retirement and remains outside this no-feature-loss
work. No source changes or tests were run for this read-only finding.
