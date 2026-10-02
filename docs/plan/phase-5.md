# Phase 5: curriculum and coursework

Goal: one curriculum model with cohort-based and self-paced modes and GitHub import of both
existing formats; the course-platform coursework stack (homework, projects, peer review,
leaderboards, certificates) as an optional app that both sites can enable (decision D8).

Freeze: AISL one weekend (A5.2), DTC one weekend (D5.2).

This phase has the largest model merge. It is split so that the shared apps are built and tested
against the package test project first, then each site migrates with a mapping that is rehearsed
on a development copy before the freeze.

Exit criteria:

- Neither site defines a `Course`, `Module` or `Unit` model:
  `grep -rn "^class \(Course\|Module\|Unit\)(" --include=*.py ~/git/ai-shipping-labs ~/git/dtc-website | grep -v migrations` -> nothing.
- AISL course pages, progress, drip, tier gating and purchase access work in production.
- DTC cohorts with homework, projects, leaderboards and certificates work in the development
  environment with the imported data.

## C5.1a Curriculum models and access

Repository: community-base. Depends on: C4.2.

Read first
- `~/git/ai-shipping-labs/content/models/course.py`, `cohort.py`, `enrollment.py`,
  `instructor.py`, `content/access.py`, `content/services/course_units.py`,
  `specs/05-content-courses.md`.
- `~/git/dtc-website/courses/models/cohort.py`, `curriculum.py`, `curriculum_import.py`,
  `_docs/specs/04-courses-and-cohorts.md`.

Model design (`label = "cb_curriculum"`):

| Model | Fields (summary) | Origin |
|---|---|---|
| `Course` | slug, title, description and html, cover and banner urls, `required_level`, `default_unit_required_level`, status, discussion url, tags JSON, testimonials JSON, github repo url, docs url, faq url, hashtag, visible, provenance (`SourceProvenanceModel` fields), instructors M2M to `events.Host(kind=instructor)` | AISL + DTC |
| `Cohort` | course FK, slug, title, `mode` cohort or self_paced, start and end dates, registration url, `curriculum_format`, hashtag, finished, visible, `max_participants`, provenance | DTC `Cohort` + AISL `Cohort`; every course has at least one cohort; a self-paced course has one open-ended cohort with `mode=self_paced` |
| `Module` | cohort FK, slug, title, sort order, overview and html, provenance | both |
| `Unit` | module FK, slug, title, sort order, video url, body and html, homework text and html, timestamps JSON, `is_preview`, `required_level`, `available_after_days`, content hash, provenance | AISL fields + DTC provenance |
| `Enrollment` | user, cohort, enrolled and unenrolled at, source, display name, leaderboard and public profile flags, certificate name, total score, certificate url | AISL `Enrollment` + DTC `Enrollment` |
| `UnitProgress` | user, unit, completed at | AISL `UserCourseProgress` + DTC `UnitReadState` |
| `Certificate` | enrollment, url, issued at, hash | AISL `CourseCertificate` + DTC certificate fields |
| `CurriculumImportRun` | as DTC | DTC |

Steps
1. Models above with one initial migration for the new `cb_curriculum` label.
2. Access service: `can_access(user, unit)` with the unit level inheritance from the unit
   override, the course default and the course `required_level`; purchase access through hook
   `COURSE_ACCESS_GRANTS(user, course) -> bool` (AISL implements with `CourseAccess`).
3. Domain services: enrollment ensure/unenroll, progress toggle, drip-lock decision
   (`available_after_days` against the cohort start date), next/previous unit in reading order.
4. Markdown rendering for description, overview, body and homework html.

Verification
- `uv run pytest tests/curriculum` -> pass.
- `uv run python testproject/manage.py makemigrations --check --dry-run` -> no changes.

## C5.1b Curriculum import

Repository: community-base. Depends on: C5.1a.

Read first
- `~/git/ai-shipping-labs/integrations/services/github_sync/dispatchers/courses.py`,
  `_docs/course_yaml.md`.
- `~/git/dtc-website/content_sync/course_repository.py` (curriculum parts),
  `courses/services/curriculum_source.py`, `courses/services/curriculum_import.py`.

Steps
1. Shared source graph dataclasses (course, cohorts, modules, units) as the one graph type both
   parsers produce.
2. Parser for the AISL `course.yaml` layout: `course.yaml`, `module.yaml`, unit markdown
   frontmatter, access values, sort-order filename prefixes.
3. Parser for the DTC repository curriculum adapter: `course.yaml`, `SITE.md`, module
   manifests, unit frontmatter, `cohorts/<identifier>/cohort.yaml`; homework manifests stay
   unread until C5.2.
4. Graph importer that upserts `cb_curriculum` rows with provenance and records a
   `CurriculumImportRun`; register both parsers as `content_sync` parsers from the app.

Verification
- `uv run pytest tests/curriculum` -> pass.
- `testproject`: import an AISL course.yaml fixture and a DTC course repository fixture ->
  courses, cohorts, modules and units rows match the fixtures, provenance set, re-import is
  unchanged, removal soft-deletes.

## C5.1c Curriculum public pages and member APIs

Repository: community-base. Depends on: C5.1b.

Read first
- `~/git/ai-shipping-labs/content/views/courses.py`, `content/services/course_units.py`,
  `api/views/course_enrollments.py` member shape, `specs/05-content-courses.md` pages.

Steps
1. Public pages: catalog, course detail with cohorts, module overview, unit page with sidebar;
   template contract.
2. Progress toggle API and cohort enroll and unenroll API (session authenticated, CSRF kept).
3. Member API endpoints for courses list, course detail with syllabus and progress, and unit
   detail.

Verification
- `uv run pytest tests/curriculum` -> pass.
- `testproject`: import the AISL content fixture and a DTC curriculum fixture -> both render;
  drip lock respected for a cohort started today with `available_after_days=7`.

## C5.1d Curriculum Studio and staff APIs

Repository: community-base. Depends on: C5.1c.

Read first
- `~/git/ai-shipping-labs/studio/` course pages, `api/views/course_certificates.py`,
  `course_enrollments.py`, `course_instructors.py`, `enrollments.py`.

Steps
1. Studio under `Courses`: courses, cohorts, modules, units (read-only when source-managed),
   instructors, enrollments, certificates issue.
2. Staff API endpoints from AISL `api/views/course_enrollments.py`, `course_certificates.py`
   and `course_instructors.py`. The sprint endpoints in `enrollments.py` stay in AISL:
   sprints belong to `plans`, which is not extracted.
3. Move the remaining curriculum tests from AISL `content/tests/` course tests and DTC
   `courses/tests/` curriculum tests.

Verification
- `make test tests/curriculum` -> pass.
- `testproject`: import the AISL content fixture and a DTC curriculum fixture -> both render;
  drip lock respected for a cohort started today with `available_after_days=7`.

## C5.1e Curriculum ownership: course-owned modules, cohort placement, and nesting

Repository: community-base. Depends on: C5.1d.

Design: `docs/plan/evidence/c5.1e-shared-curriculum-adoption.md`. Evidence for the ownership
finding is posted on `community-base#253`
(https://github.com/DataTalksClub/community-base/issues/253#issuecomment-5697834824). This issue
implements `community-base#252` (nesting, `kind`, `is_bonus`) directly on the corrected
course-owned shape rather than on the cohort-owned `Module` merged in C5.1a-C5.2e, per the
owner's decision recorded on both issues: `community_base.curriculum` has never been tagged
(latest release `v0.3.9`; `C5.3` is still `todo`), so this is a pre-release correction, not a
migration of a shipped contract, and breaking the merged-but-unreleased shape is accepted.

Goal: `Module.course` FK (replacing `Module.cohort`), `Module.parent` (nullable self-FK, max
depth two), `Module.is_bonus`, `Module.available_after_days`; `Unit.kind`
(`lesson`/`homework`/`event`), `Unit.session_position`, `Unit.is_bonus`; a new optional
`CohortModule` placement model; `Cohort.curriculum_format` deleted. A cohort with no
`CohortModule` rows shows the full course tree in module order (AI Shipping Labs' case, zero
extra rows); `CohortModule` rows curate a subset or order for a cohort that needs it
(DataTalks.Club's case).

Read first
- `docs/plan/evidence/c5.1e-shared-curriculum-adoption.md` (this issue's design, in full).
- `community_base/curriculum/models.py`, `parsers_aisl.py`, `parsers_dtc.py`, `source.py`,
  `importing.py`, `views.py`, `services.py`, `api_views.py`, `studio_views.py`, `studio_forms.py`.
- `~/git/ai-shipping-labs/content/models/course.py` (the model this design targets: `Module`
  line 318 has `course` FK line 321 and `sort_order` line 326; `Unit` line 374 has `module` FK
  line 377, `sort_order` line 382, `available_after_days` line 417).
- `AI-Shipping-Labs/website#1674` (the site's local, in-flight implementation of `#252` against
  its own model; field names must match exactly, see design doc section 7).
- `community_base/coursework/*.py` only imports `Cohort`, `Course`, `Enrollment`, `Certificate`
  from `curriculum.models` (verified by grep in the design doc) — confirm this still holds before
  starting; if it has changed, the coursework blast-radius claim in the design doc is wrong and
  this issue's steps need to account for it before touching `Module`/`Unit`.

Steps
1. Model changes per design doc section 2: `Module.course` FK (drop `Module.cohort`),
   `Module.parent`/`is_bonus`/`available_after_days`; `Unit.kind`/`session_position`/`is_bonus`;
   new `CohortModule` model; delete `Cohort.curriculum_format`. Regenerate
   `community_base/curriculum/migrations/0001_initial.py` in place (untagged, so append-only does
   not apply yet, per `docs/02-architecture.md` rule 5) rather than adding a second migration.
   Every new non-nullable column ships with `db_default` (`Unit.kind` default `"lesson"`,
   `is_bonus` fields default `False`); nullable columns (`Module.parent`,
   `Module.available_after_days`, `Unit.session_position`) need none.
2. Slug uniqueness by construction: `cb_module_course_parent_slug_unique` on
   `(course, parent, slug)`, replacing `cb_module_cohort_slug_unique`.
3. Source graph rewrite (`source.py`): `CourseGraph.modules` becomes the owned tree (recursive
   via a `children` field on `ModuleGraph`); `CohortGraph.modules` (owned subtree) becomes
   `CohortGraph.module_refs: tuple[str, ...] | None` (ordered top-level module identifiers a
   cohort places; `None` means the full course tree in module order).
4. `parsers_aisl.py`: parse nested module directories recursively
   (`01-module/01-submodule/01-unit.md`), numeric prefix stripped from the slug at every level,
   mixed children-and-units rejected at import time naming the offending directory. AISL's single
   self-paced cohort always emits `module_refs=None`.
5. `parsers_dtc.py`: same recursive nesting for shared (course-owned) module manifests; a
   cohort's `flow` entries populate `module_refs` when present.
6. `importing.py`: `_module`/`_unit` upserts key off `course` instead of `cohort`; add
   `_cohort_module` upsert for `CohortModule` rows when a cohort's graph carries `module_refs`.
7. `services.py`: rewrite `get_all_units_ordered`, `get_next_unit`, `get_prev_unit`,
   `decide_unit_drip` to the depth-first order and `available_after_days` cascade
   (`Unit.available_after_days` -> leaf `Module.available_after_days` -> parent
   `Module.available_after_days`) specified in `#252`/`#1674`. Progress helpers exclude
   `is_bonus` (module or unit) from the denominator and include `kind="event"`.
8. `views.py`/`api_views.py`/`studio_views.py`/`studio_forms.py`: switch every
   `cohort.modules`/`Module.objects.filter(cohort=...)` to `course.modules.filter(parent=None)`
   (default) or a `CohortModule`-driven query (curated). Public URLs drop the cohort segment for
   module/unit pages (`/courses/<slug>/<module_slug>[/<unit_slug>]`), matching AI Shipping Labs'
   real site paths (confirmed in `#1674`).
9. Update `tests/curriculum/` fixtures and the 113 existing tests
   (`test_models.py` 20, `test_import.py` 10, `test_services.py` 23, `test_views.py` 22,
   `test_studio.py` 10, `test_staff_api.py` 10, `test_sync.py` 7, `test_access.py` 11) for the new
   ownership shape; add nesting-specific tests per the task's quality bar, including two
   submodules under one module each containing a unit slugged `section-overview`, both syncing
   cleanly.
10. Update `community_base/curriculum/README.md` for the new model table, the `CohortModule`
    placement default, and the dropped `Cohort.curriculum_format`.

Verification
- `uv run pytest tests/curriculum` -> pass.
- `uv run python testproject/manage.py makemigrations --check --dry-run` -> no changes.
- `uv run pytest tests/test_boundaries.py` -> pass (no site imports).
- `testproject`: import an AISL course.yaml fixture with a nested `01-module/01-submodule/`
  directory and a DTC course-repository fixture with cohort-curated module placement -> both
  render; two submodules each containing a unit slugged `section-overview` sync cleanly with no
  collision; a course with no `CohortModule` rows shows its full tree in module order.

Done when
- [ ] `Module.course` FK replaces `Module.cohort`; `Cohort.curriculum_format` is deleted.
- [ ] `Module.parent`, `Module.is_bonus`, `Module.available_after_days`, `Unit.kind`,
  `Unit.session_position`, `Unit.is_bonus` exist with database-level defaults where non-nullable.
- [ ] `CohortModule` exists; a cohort with no placement rows shows the full course tree.
- [ ] Both parsers import nested module directories with numeric-prefix ordering.
- [ ] Depth-first reading order implemented once, used by navigation and progress.
- [ ] `docs/plan/phase-5.md` C5.1a-d's donor table note is not needed (no other doc references
  `Module.cohort` outside this issue's own changes) -- confirmed by grep before closing.

Docs
- `community_base/curriculum/README.md`.
- `docs/plan/evidence/c5.1e-shared-curriculum-adoption.md` (already written; update only if a
  step above produces evidence that changes its conclusions).

## C5.1f Pre-work checklist items

Repository: community-base. Depends on: C5.1e.

Goal: a learner who has enrolled sees a pre-course checklist (read the docs, set up the
environment, install tools) as a real module in their course journey, not a static page.
Package capability only in this issue -- no site wiring (owner instruction; see "What this issue
does not do" below).

Read first
- `community_base/curriculum/models.py` (`Unit`, `UnitProgress`, `Course._countable_units`).
- `community_base/curriculum/services.py` (`is_completed`, `mark_completed`, `unmark_completed`,
  `completed_unit_ids` -- the existing per-unit completion pattern this issue reuses).
- `community_base/curriculum/studio_forms.py` `UnitForm` (kind is already a plain `ModelForm`
  field; a new choice needs no Studio form change).
- `community_base/onboarding/models.py` -- confirmed out of scope: `OnboardingFlow` is one flow
  per member (account-level, kind `profile|questionnaire|ai_chat|plan|custom`), not per-course or
  per-cohort, so it cannot carry a course's pre-work checklist.

Design: no new model. A pre-work checklist is an ordinary `Module` (for example a course's first
module, titled "Before you start") whose `Unit` rows use a new `kind`. This reuses `Unit`'s
existing shape end to end: `title` is the item's short title, `body`/`body_html` carries the
description and an optional link (rendered markdown, consistent with every other unit), and
`UnitProgress` (via `services.is_completed`/`mark_completed`/`unmark_completed`) already gives
per-learner, per-item completable/checkable state with no parallel tracking model. `is_bonus`
(already meaning "optional, not required") doubles as the item's required/optional flag --
introducing a separate `is_required` field would duplicate that meaning on the same row.

A dedicated `ChecklistItem` model was considered and rejected for this first slice: it would
duplicate `Unit`'s title/body/sort_order/is_bonus fields and `UnitProgress`'s completion
tracking for no behavioral gain, contradicting the instruction to reuse `UnitProgress`'s pattern
rather than invent a parallel one.

Steps
1. `models.py`: add `UNIT_KIND_CHECKLIST_ITEM = "checklist_item"` to `UNIT_KINDS`
   (`("checklist_item", "Checklist item")`). No new field, no new constraint.
2. `Course._countable_units()`: exclude `kind=UNIT_KIND_CHECKLIST_ITEM` alongside the existing
   `is_bonus` exclusions, and update its docstring. Pre-work items are a separate readiness
   checklist, not lesson/homework/event course progress; without this exclusion a required
   checklist item would silently change existing `total_units()`/`completed_units()` percentages.
3. `services.py`: add `get_checklist_items(module) -> list[Unit]` (units of `module` with
   `kind=UNIT_KIND_CHECKLIST_ITEM`, ordered) and a frozen dataclass `ChecklistItemState(unit,
   is_required, is_completed)` plus `get_checklist_state(user, module) -> list[ChecklistItemState]`
   built on the existing `completed_unit_ids` batched read.
4. Migration: `uv run python testproject/manage.py makemigrations curriculum` (new migration
   file; `curriculum`'s only migration remains untagged but this is a pure additive choices
   change, not the kind of rewrite C5.1e regenerated in place).
5. No parser change: `parsers_aisl.py` `_UNIT_KINDS` and the DTC parser's accepted kind set stay
   `{lesson, homework, event}`. Checklist items are Studio/API-authored only in this slice;
   teaching either import format to emit them is separate follow-up work, not this issue.
6. No public template, public view, or public API change. `views.py`/`api_views.py` already
   render units generically with no kind-specific branching, so a checklist-kind unit renders
   like any other unit if a caller reaches one -- acceptable for this package-only slice since
   neither site's real course pages can reach `cb_curriculum.Unit` at all yet (see the phase
   exit criteria: `A5.1`/`A5.2`/`D5.1`/`D5.2` are still `todo`; only when a site adopts the
   package's curriculum app do learner-facing checklist templates/views become that site's own
   follow-up work).

What this issue does not do
- No dtc-website or ai-shipping-labs template, view, or registration-flow change (each site's
  own process and review, once curriculum is adopted there).
- No Studio dedicated checklist page (the generic Unit Studio form already covers authoring).
- No import-pipeline support for checklist items.

Verification
- `uv run pytest tests/curriculum` -> pass.
- `uv run python testproject/manage.py makemigrations --check --dry-run` -> no changes.
- `uv run pytest tests/test_boundaries.py` -> pass (no site imports).
- New tests: `Course.total_units()`/`completed_units()` unaffected by adding checklist items to a
  module; `get_checklist_state` reflects `UnitProgress` completion and `is_bonus` as
  required/optional; a required and an optional checklist item both toggle independently via the
  existing `mark_completed`/`unmark_completed` services.

Done when
- [ ] `Unit.kind` accepts `checklist_item`.
- [ ] `Course._countable_units()` excludes checklist items from the progress denominator.
- [ ] `get_checklist_items`/`get_checklist_state` exist and are tested.
- [ ] No parser, public template, public view, or public API behavior changed for existing kinds.

Docs
- `community_base/curriculum/README.md`: document the new kind and the checklist services under
  the existing `Unit`/`UnitProgress` rows.

## C5.1g Structured code annotations in unit bodies

Repository: community-base. Depends on: C5.1f.

Goal: a unit body can attach notes to lines of a fenced code block, and a malformed payload fails
the import instead of reaching a reader. GitHub issue DataTalksClub/community-base#255. The
capability is live on AI Shipping Labs (`content/utils/code_annotations.py`,
AI-Shipping-Labs/website#1589); this issue lifts it into the package so DataTalks.Club gets it too
and there is one implementation.

Read first
- `content/utils/code_annotations.py` in `../ai-shipping-labs` -- the reference implementation and
  the authoring contract.
- `community_base/curriculum/rendering.py` (`render_markdown`, `strip_leading_title_h1`).
- `community_base/curriculum/models.py` `Unit.save`.
- `community_base/curriculum/parsers_aisl.py` `_parse_unit`, `parsers_dtc.py`
  `_lesson_frontmatter`.
- `docs/01-decisions.md` D18 -- public design systems stay per site.

Design: the package owns meaning, each site owns appearance. `code_annotations.py` holds the
parser and the structured representation and emits no HTML; the default markup is an overridable
template; the styling is the adopting site's. The authoring contract is not redesigned -- it is
the one specified on #1589, so a body authored for one site behaves the same on the other.

Steps
1. `community_base/curriculum/code_annotations.py`: port the fence scan, the strict YAML loader,
   the payload schema, the range validation and the association rules. Return
   `ParsedUnitBody(markdown, blocks)` where a block carries the language, the `CodeLine` rows with
   their highlight state, and the `CodeAnnotation` notes.
2. Add `build_render_plan`, which swaps each annotated fence for an opaque token, so the rendered
   block is identified exactly rather than matched by position.
3. `curriculum/templates/curriculum/annotated_code_block.html`: default markup, structural hooks
   only, no colour or spacing. A site overrides it at the same path.
4. `rendering.render_annotated_markdown`: render the stripped markdown through the existing
   `render_markdown` (which sanitizes) and substitute each token. No second markdown path and no
   second sanitizer.
5. `Unit.save`: render bodies through `render_annotated_markdown`.
6. Both sync parsers: validate a lesson body before anything is written and raise
   `CurriculumParseError` naming the source file.

What this issue does not do
- No change to the authoring syntax.
- No stylesheet: D18 keeps public design systems per site.
- No removal of the AI Shipping Labs local copy; that site cannot consume the package curriculum
  app yet and deletes its copy when it adopts it.
- No content adoption in either content repository.

Verification
- `uv run pytest tests/curriculum` -> pass, including the new `tests/curriculum/test_code_annotations.py`.
- `uv run pytest tests/test_boundaries.py` -> pass.
- `uv run python testproject/manage.py makemigrations --check --dry-run` -> no changes.
- A fixture exercising the syntax end to end: a synced unit whose body carries a payload renders
  highlighted lines and the note list, and a malformed payload fails the sync.

Done when
- [ ] The authoring contract matches #1589, accepting and rejecting the same bodies.
- [ ] The parse result is a structured representation with no HTML in it.
- [ ] The default markup ships as an overridable template and carries no design system.
- [ ] `Unit.save` renders annotations, and an invalid body leaves the persisted unit untouched.
- [ ] Both sync parsers fail closed on a malformed payload, naming the file.

Docs
- `community_base/curriculum/README.md`: the authoring contract, the package/site split, where the
  CSS lives, and the AI Shipping Labs follow-up.

## C5.2a Coursework models

Repository: community-base. Depends on: C5.1d.

Read first
- `~/git/dtc-website/courses/models/homework.py`, `project.py`, `stat_display.py`,
  `testimonial.py`, `wrapped.py`, `validators/`,
  `_docs/specs/04-courses-and-cohorts.md` "Target model".

Steps
1. New app `community_base.coursework` (`label = "cb_coursework"`) with the models from the
   C5.2 list: `Homework`, `Question`, `Submission`, `Answer`, `HomeworkStatistics`,
   `Project`, `ProjectSubmission`, `ProjectVote`, `ReviewCriteria`,
   `ProjectCriteriaAssignment`, `PeerReview`, `CriteriaResponse`,
   `ProjectEvaluationScore`, `ProjectStatistics`, `LeaderboardComplaint`,
   `RegistrationCampaign`, `CourseRegistration`, `Testimonial`, `WrappedStatistics`.
2. Cohort, enrollment and user references point at `cb_curriculum.Cohort`,
   `cb_curriculum.Enrollment` and `settings.AUTH_USER_MODEL`. Provenance fields follow the
   curriculum pattern; keep validators in a migration-stable module.
3. Drop `validate_url_200` and other synchronous external URL checks per spec 04
   ("synchronous arbitrary URL validation is removed from request paths").
4. Port the shared statistics display helpers.

Verification
- `uv run pytest tests/coursework` -> pass.
- `uv run python testproject/manage.py makemigrations --check --dry-run` -> no changes.

## C5.2b Homework scoring and statistics

Repository: community-base. Depends on: C5.2a.

Read first
- `~/git/dtc-website/courses/homework_answer_checks.py`, `homework_answer_resolution.py`,
  `homework_score_calculation.py`, `homework_question_stats.py`,
  `deadline_reminder_*.py`, `_docs/specs/04-courses-and-cohorts.md`
  "Preserved learner behavior".

Steps
1. Submission service: create/update submission, answer checking and scoring per question
   type, FAQ and learning-in-public scoring.
2. Answer resolution for question answer envelopes (encrypted sources stay site-side; the
   package consumes resolved envelopes).
3. Homework statistics computation (min/max/avg/median/quartiles per score and time field).
4. Deadline reminder job handlers and mail purposes registered through the jobs and mail apps.

Verification
- `uv run pytest tests/coursework` -> pass; a submitted homework scores correctly, statistics
  compute, and a deadline reminder job handler runs synchronously.

## C5.2c Projects and peer review

Repository: community-base. Depends on: C5.2b.

Read first
- `~/git/dtc-website/courses/project_assignment.py`, `project_assignment_selection.py`,
  `project_review_scores.py`, `project_score_calculation.py`, `project_scoring.py`,
  `project_submission_scoring.py`, `votes.py`.

Steps
1. Project submission service with github/commit capture and learning-in-public scoring.
2. Peer review assignment (required and volunteer reviews), criteria responses, evaluation
   score rollup, review and submission scoring, project statistics.
3. Project votes.
4. AISL mapping documented: the AISL light `ProjectSubmission`/`PeerReview` become a `Project`
   per cohort with the same criteria text (A5.1 applies it).

Verification
- `uv run pytest tests/coursework` -> pass; a project flow assigns reviews, collects criteria
  responses, computes evaluation and total scores and statistics.

## C5.2da Leaderboard rollup, preferences and complaints

Repository: community-base. Depends on: C5.2c.

Split from C5.2d; the donor analysis lives in `docs/plan/evidence/c5.2d-leaderboard-donors.md`
and `docs/plan/evidence/c5.2d-donors.md` (step 1 sections).

Read first
- `~/git/dtc-website/courses/leaderboard.py`, `courses/views/course_leaderboard_data.py`,
  `courses/views/course_leaderboard_breakdown.py`, `courses/services/enrollment_flags.py`,
  `courses/random_names.py`.

Steps
1. `coursework/leaderboard.py` write side: `update_leaderboard(cohort)` full recompute of
   `Enrollment.total_score` and `position_on_leaderboard` over active enrollments (integer sums
   of homework and non-volunteer project scores, `(-total_score, enrollment id)` ranking, one
   `bulk_update`), plus cache invalidation.
2. Read side in the same module: visibility filter, `Coalesce` ordering, pagination,
   serialization with `passed_projects`, current-student staleness rebuild; shared by the
   C5.2dc views and member APIs.
3. `coursework/enrollment_flags.py` `set_learning_in_public_disabled`, `random_names.py`
   `ensure_display_name` with a configurable name generator, and the complaint services
   `file_leaderboard_complaint` and `resolve_leaderboard_complaint`.
4. Default the `COURSEWORK_PROJECT_LEADERBOARD_UPDATER` hook to the package updater; it stays
   site-overridable.

Verification
- `uv run pytest tests/coursework` -> pass; recompute ranks with the id tie-break, hidden
  enrollments stay ranked but unlisted, the complaint lifecycle persists reporter and resolver.
- `testproject`: submit homework, score it, call the updater, leaderboard position computed.

## C5.2db Registration campaigns and course registrations

Repository: community-base. Depends on: C5.2c.

Split from C5.2d; the donor analysis lives in `docs/plan/evidence/c5.2d-donors.md` (step 2
section).

Read first
- `~/git/dtc-website/courses/services/registration_campaigns.py`,
  `services/registration_counts.py`, `courses/views/registration.py`,
  `courses/views/registration_form.py`.

Steps
1. `coursework/registration.py` `public_course_registration_count` with the spec 04 semantics:
   baseline only while it names the current cohort, native boundary exclusion, `None` without a
   current cohort.
2. Campaign bindings and state machine: `active_campaign_for_cohort`,
   `next_edition_campaign_for_cohort`, `campaign_slug_in_registration_url`,
   `family_registration`, `stop_registration`, `open_new_cohort` with
   `RegistrationCampaignStateError`.
3. `create_course_registration` service core with the duplicate rule and optional consent,
   plus `campaign_course_is_open` and the existing-registration lookup; the
   `COURSEWORK_REGISTRATION_SUBMITTED` and `COURSEWORK_REGISTRATION_CAMPAIGN_CHANGED` hooks.

Verification
- `uv run pytest tests/coursework` -> pass; count semantics cover baseline carry, boundary
  exclusion and no-current-cohort; the state machine rejects illegal transitions.
- `testproject`: a campaign count reflects baseline plus native rows.

## C5.2dc Learner views, member APIs and certificates

Repository: community-base. Depends on: C5.2da, C5.2db.

Split from C5.2d; the donor analysis lives in `docs/plan/evidence/c5.2d-donors.md` (step 3 and
step 4 sections).

Read first
- `~/git/dtc-website/courses/views/`, `courses/urls.py`,
  `_docs/compatibility/course-route-contracts.json`.

Steps
1. `coursework/submissions.py` `submit_homework`; learner views for the homework form, project
   submission, peer review, leaderboard, score breakdown, complaint, enrollment preferences and
   certificate page; templates under `community_base/coursework/templates/coursework/`
   following the template contract.
2. Member APIs for the learner flows: enrollment preferences toggle with session
   authentication and read-only leaderboard data; `coursework/certificates.py`
   `issue_certificate` with the `COURSEWORK_CERTIFICATE_ISSUED` hook; the remaining
   `COURSEWORK_*` hooks from the donor analysis declared in `kernel/conf.py`.

Verification
- `make test tests/coursework` -> pass.
- `testproject`: submit homework, score it, leaderboard position computed; submit project,
  peer review assignment, evaluation score, certificate issued.

## C5.2e Coursework Studio and Wrapped

Repository: community-base. Depends on: C5.2dc.

Read first
- `~/git/dtc-website/studio_courses/`, `courses/wrapped_statistics/`,
  `courses/services/testimonials.py`.

Steps
1. Studio operations from `studio_courses`: homework and question management, submissions and
   rescoring, projects and criteria, peer review administration, leaderboard recompute,
   complaint resolution, certificate management, registration campaigns.
2. Testimonial management surface.
3. Wrapped statistics read/recalculate surfaces.

Verification
- `make test tests/coursework` -> pass with at least DTC's test count for these modules.
- `testproject`: the coursework Studio flows cover homework rescoring, peer review
  administration and leaderboard recompute on imported data.

## C5.2f Peer review assessment modes: per-submission lifecycle, pooled batch formation and assignment

Repository: community-base. Depends on: C5.2e.

Design settled in issue DataTalksClub/community-base#256 (owner correction and pooled-deadline
decision comments). Read those before changing code; they override the issue body's first draft.

Read first
- `community_base/coursework/models.py` (`Project`, `ProjectState`, `ProjectSubmission`,
  `PeerReview`, `PeerReviewState`).
- `community_base/coursework/review.py` (`assign_peer_reviews_for_project`, `score_project`,
  `select_random_assignment`, `group_peer_reviews`, `score_submission`).
- `community_base/coursework/views.py` (`project_view`, `projects_eval_view`,
  `_eval_submit_context`, `projects_eval_submit`) for every place that reads `Project.state`.
- `community_base/coursework/leaderboard.py` (`completed_project_submissions_prefetch`).
- `community_base/coursework/statistics.py` (`calculate_project_statistics`).
- `community_base/curriculum/models.py` `Cohort.mode` and the `cb_cohort_self_paced_unique`
  constraint (one self-paced cohort per course).
- For reference only, do not copy verbatim: `~/git/ai-shipping-labs/content/services/peer_review_service.py`
  `form_batches_for_course` (round-robin batch assignment) and
  `check_and_update_submission_status` (per-submission completion check). It has no criteria
  model, no volunteer reviewers and no statistics; do not narrow the package to match it.

Design decision: state means something different in pooling mode, not a parallel model

A cohort-wide `CLOSED -> COLLECTING_SUBMISSIONS -> PEER_REVIEWING -> COMPLETED` lifecycle
describes every submission in a project moving through the same phase together. A pool has no
such moment: submissions arrive continuously and are assigned to review batches independently,
so one learner can be reviewing while another is still waiting to submit. `Project.state` keeps
its current four values and current meaning for a `cohort.mode == "cohort"` project (dated,
deadline-driven, unchanged). For a `cohort.mode == "self_paced"` project, `Project.state` narrows
to a binary switch the two values it already has for "open": it starts and stays
`COLLECTING_SUBMISSIONS` (submissions accepted at any time) until an operator sets it to `CLOSED`
(no more submissions or pool formation accepted); `PEER_REVIEWING` and `COMPLETED` are never set
on a pooled project and must be rejected if attempted. `assign_peer_reviews_for_project` and
`score_project` (the deadline-only, whole-project functions) gain a precondition that refuses to
run against a `self_paced` cohort's project, so a Studio operator cannot invoke the wrong mode by
accident.

Per-submission progress -- which the cohort-wide states cannot express for a pool -- moves to a
new `ProjectSubmission.review_state` field (`AWAITING_ASSIGNMENT`, `IN_REVIEW`, `SCORED`), the
same three phases as before but scoped to the learner instead of the project. This field is
maintained for both modes (a cheap, denormalized projection, the same pattern
`Enrollment.total_score`/`position_on_leaderboard` already use over per-submission rows): a
deadline-mode project's `assign_peer_reviews_for_project` and `score_project` set it in bulk for
every submission at the same moment they flip `Project.state`, so deadline-mode behaviour is
unchanged in substance, only mirrored onto the new field. A pooled project's batch-formation and
batch-scoring functions (this issue) set it per batch instead.

Every reader that keyed off `Project.state` to learn whether one submission's peer review is
finished switches to `ProjectSubmission.review_state == SCORED` instead, which is correct and a
no-op change for deadline mode (a submission only reaches `SCORED` at the exact moment
`Project.state` reaches `COMPLETED` today) and is now also correct for pooled mode:
`leaderboard.completed_project_submissions_prefetch` filters on `review_state=SCORED` instead of
`project__state=COMPLETED`; `statistics.calculate_project_statistics` computes over currently
`SCORED` submissions for a pooled project (a live, incrementally recomputed statistic) instead of
requiring `Project.state == COMPLETED`, and keeps its current whole-project gate for deadline
mode. `views.py`'s `eval_closed`, `_eval_submit_context`'s `accepting_submissions`/`disabled`, and
`projects_eval_submit`'s POST guard, which today hard-require `Project.state ==
PEER_REVIEWING`, switch to a per-review check (`review.state == TO_REVIEW` and, for a pooled
review, its batch not yet scored) for a pooled project, and keep the existing project-state check
for a deadline-mode project. `project_view`'s `accepting_submissions` needs no change: for a
pooled project it already evaluates correctly against the narrowed two-value meaning above.

Pooling architecture: batches, not a per-submission queue

A batch is the unit that must resolve together, not each submission independently. Within one
project, `select_random_assignment` builds a full round-robin graph over the batch: every member
reviews `number_of_peers_to_evaluate` others and is reviewed by the same number, all created in
one event with one shared due date. Scoring one member early, before their own outgoing reviews
(a different, independent set of assignments within the same batch) are resolved, would compute
`peer_review_score`/`reviewed_enough_peers` from incomplete data with no later recompute. So the
batch, not the individual submission, is the scoring unit -- symmetric with deadline mode, where
the whole project is the scoring unit for the same reason.

New model `PeerReviewBatch`: `project` (FK, CASCADE), `formed_at` (auto-now-add), `due_at`
(`formed_at + project.pooled_review_window_days` at creation, no default needed: a new table has
no existing rows to backfill), `scored_at` (nullable, set once, guards against double-scoring a
race between the happy-path trigger and the expiry sweep). `PeerReview.batch` (FK, nullable,
CASCADE) links a pooled review to its batch; null for every deadline-mode review.

New field `Project.pooled_review_window_days` (`PositiveIntegerField`, `default=7`). Per-project,
not per-cohort or per-course: every other assignment knob
(`number_of_peers_to_evaluate`, `points_for_peer_review`, `learning_in_public_cap_review`)
already lives on `Project`, and a self-paced cohort's course-level uniqueness
(`cb_cohort_self_paced_unique`) means "per cohort" and "per course" already collapse to the same
thing for pooled courses, so a project-level field is the finer-grained option and costs nothing
extra. Meaningful only when `project.cohort.mode == "self_paced"`; ignored otherwise.

No new mode field on `Project` or `Cohort`. Assessment mode is derived from the already-explicit
`Cohort.mode` (`cohort` | `self_paced`, landed in C5.1e) via a new `Project.uses_pooled_review`
property. This is what makes mode selection "explicit" per the issue: `Cohort.mode` is a
deliberate value an operator sets, not inferred from whether a submission happens to have a
cohort (the AISL donor's approach). A second field on `Project` would risk disagreeing with its
own cohort's mode for no benefit.

Steps
1. Migration: `ProjectSubmission.review_state` (choices `AW`/`IR`/`SC`, default `AW`), plus a
   data migration backfilling existing rows from their project's current `Project.state`
   (`COMPLETED` -> `SC`, `PEER_REVIEWING` -> `IR`, else `AW`) so leaderboard and statistics stay
   correct immediately after the migration. `Project.pooled_review_window_days`
   (`PositiveIntegerField`, `default=7`). `PeerReviewState` gains `EXPIRED = "EX"` (used by
   C5.2g; add it here so the migration lands once). New `PeerReviewBatch` model and
   `PeerReview.batch` nullable FK.
2. `Project.uses_pooled_review` property (`cohort.mode == "self_paced"`).
3. Guard `assign_peer_reviews_for_project` and `score_project` to fail with a clear message
   against a pooled project (new precondition, same `ProjectActionStatus.FAIL` shape as the
   existing preconditions); both set `ProjectSubmission.review_state` for every touched
   submission alongside the existing `Project.state` transition.
4. New module `community_base/coursework/pooling.py`: `try_form_batch(project)` -- when a
   pooled project's `AWAITING_ASSIGNMENT` submission count (`volunteer_review_only=False`)
   reaches `number_of_peers_to_evaluate + 1`, take the oldest that many by `submitted_at`, create
   one `PeerReviewBatch`, reuse `select_random_assignment` for the review graph (seeded per
   project and batch sequence, not the single global `ASSIGNMENT_SEED`, since pooling forms many
   batches per project and a single reused seed would repeat the same relative pairing pattern
   every time), set `review_state=IN_REVIEW` on the batch's submissions. Run under
   `transaction.atomic()` with a row lock on the project (mirrors `assign_peer_reviews_for_project`)
   to serialize concurrent submissions racing to form the same batch. Dispatch
   `try_form_batch` after commit from `projects.submit_project` when the project is pooled.
5. `pooling.py`: `try_score_batch(batch)` -- scores every submission in the batch
   (`score_submission` from `review.py`, reused as-is; it is already submission-scoped) once
   every review in the batch is resolved (`SUBMITTED` or `EXPIRED`, added in C5.2g), sets
   `review_state=SCORED` and `batch.scored_at`; idempotent (no-op if `scored_at` is already set).
   Called from `submit_peer_review` (happy path, batch finishes before its due date) and from the
   C5.2g expiry sweep (timeout path). Extend `submit_peer_review` to reject a submission whose
   review's batch already has `scored_at` set (the review window for that batch is closed), and,
   while touching this function, add the same guard for deadline mode against a `COMPLETED`
   project (an existing gap: nothing today stops a late `CriteriaResponse` write after
   `score_project` has already run and will never re-aggregate it).
6. `views.py`: replace the three `Project.state == PEER_REVIEWING` reads listed above with a
   per-review check that branches on `project.uses_pooled_review`.
7. `leaderboard.completed_project_submissions_prefetch`: filter `review_state="SC"` instead of
   `project__state=ProjectState.COMPLETED.value`.
8. `statistics.calculate_project_statistics`: for a pooled project, compute over
   `review_state="SC"` submissions without requiring `Project.state == COMPLETED`; keep the
   existing gate for deadline mode.

Verification
- `uv run pytest tests/coursework` -> pass; a pooled project accumulates submissions, forms a
  batch at `n+1`, assigns a full round-robin graph, and scores the batch once every review in it
  is submitted, without ever moving `Project.state` off `COLLECTING_SUBMISSIONS`.
- `uv run python testproject/manage.py makemigrations --check --dry-run` -> no changes.
- `uv run pytest tests/test_boundaries.py` -> pass.
- `testproject`: a deadline-mode project's existing assign/score flow is unchanged (same
  `Project.state` transitions, `ProjectSubmission.review_state` now mirrors them); calling
  `assign_peer_reviews_for_project` or `score_project` against a pooled project fails cleanly.

Done when
- [ ] `ProjectSubmission.review_state`, `Project.pooled_review_window_days`,
  `PeerReviewState.EXPIRED`, `PeerReviewBatch` and `PeerReview.batch` exist with database-level
  defaults (or null, for the two nullable FKs) and a data migration backfills existing
  submissions.
- [ ] `Project.state` never reaches `PEER_REVIEWING` or `COMPLETED` for a `self_paced` cohort's
  project; `assign_peer_reviews_for_project` and `score_project` refuse to run against one.
- [ ] `leaderboard.py` and `statistics.py` read `review_state`, not `project.state`, for
  per-submission completion.
- [ ] A pooled batch scores exactly once even if the happy-path trigger and the C5.2g expiry
  sweep race (guarded by `scored_at`).

Docs
- `community_base/coursework/README.md` (create it; none exists today) documenting both
  assessment modes, the batch model and the state-meaning split, since this is the first
  coursework issue an executor cannot understand from the models alone.

## C5.2g Pooled review expiry and coursework email notifications

Repository: community-base. Depends on: C5.2f.

Design settled in issue DataTalksClub/community-base#256, owner decision comment "pooled review
deadline" (2026-09-16): one week, configurable (`Project.pooled_review_window_days` from C5.2f),
clock starts at assignment (batch `formed_at`), not submission.

Read first
- `community_base/coursework/reminders.py` (existing deadline-reminder shape: `send()` with a
  stable idempotency key, `category="coursework"`).
- `community_base/events/jobs.py` (schedule() call shape, P12 in `docs/03-playbooks.md`).
- `community_base/coursework/pooling.py` (from C5.2f: `try_score_batch`).
- `community_base/mail/__init__.py` `send()` signature.

Design decision: what happens when a pooled review window expires, to both parties

No silent stall for either side, and no automatic reassignment (reassigning to a third pool
member just recreates the same indefinite-wait risk one hop later, and the owner's own framing
treats releasing the reviewee as the safety valve).

Reviewee: the moment every review in their batch is resolved -- submitted or expired, whichever
comes first, per review -- `try_score_batch` scores the batch (C5.2f). `score_submission`'s
existing fallback (`calculate_median_score`, used today when a deadline-mode submission has zero
submitted reviews) already handles scoring with fewer than the configured review count: the
median of however many responses exist, including one. No new scoring path is needed. A pooled
learner is therefore never blocked longer than `pooled_review_window_days` past their batch's
`formed_at`, matching what the deadline exists to guarantee.

Reviewer who did not deliver: their `PeerReview` row moves `TO_REVIEW` -> `EXPIRED` (new
`PeerReviewState` value, added in C5.2f's migration) rather than staying `TO_REVIEW` forever,
which would otherwise keep showing as an open task and would need special-casing everywhere
`PeerReviewState.TO_REVIEW` is read. An `EXPIRED` review does not count toward the reviewee's
`peer_review_score` (`group_peer_reviews`/`mandatory_reviews_count` already only count
`SUBMITTED`; no change needed there). The reviewer is not let off silently either: their own
`reviewed_enough_peers` (computed from reviews *they gave*, a separate axis from reviews they
received) can come out `False` if the expired review was mandatory, which already, through the
existing `passed = project_score >= points_to_pass AND reviewed_enough_peers` formula, can cost
them passing their own project -- the existing mechanism, no new punitive field. They also get an
email telling them the window closed.

Late submission: accepted only until the batch scores (`batch.scored_at` set, guarded in C5.2f's
`submit_peer_review` change); rejected after, since scoring has already locked in the median over
whatever arrived and there is no later rescoring pass to pick it up (deadline mode has the same
property: one scoring pass, no re-open). An `EXPIRED` review therefore can still be submitted and
still counts, right up until its batch is scored; once scored, it is locked, matching deadline
mode's existing single-pass precedent rather than inventing a new rule.

Steps
1. `community_base/coursework/pooling.py`: `expire_pooled_reviews()`, a durable job handler
   (`coursework.expire_pooled_reviews`) that finds `PeerReview` rows with `state=TO_REVIEW`,
   `batch__scored_at__isnull=True`, `batch__due_at__lt=now`, marks them `EXPIRED`, and for each
   affected batch calls `try_score_batch` once all its reviews are resolved. Schedule every 15
   minutes (`events.plan_reminders`'s cadence, P12).
2. New module `community_base/coursework/notifications.py` for event-driven sends (as opposed to
   `reminders.py`'s scheduled deadline scans): `send_review_assigned_notifications(reviews)`
   groups newly created reviews by reviewer and sends one `coursework.review_assigned` email per
   learner per assignment event (not one per review row, avoiding an N-email burst for a learner
   assigned several reviews at once); `send_pool_ready_notification(batch, submission)` sends
   `coursework.pool_ready` to a batch member once their batch forms; `send_review_received_notification(review)`
   sends `coursework.review_received` to the reviewee when one review lands (both modes);
   `send_review_expired_notification(review)` sends `coursework.review_window_expired` to the
   reviewer whose assignment expired. Each uses `send()` with a stable idempotency key
   (`coursework.<purpose>:<row id>`) exactly like `reminders.py`'s existing three purposes; no
   parallel send mechanism.
3. Wire the calls: `assign_peer_reviews_for_project` and `pooling.try_form_batch` call
   `send_review_assigned_notifications`; `try_form_batch` also calls
   `send_pool_ready_notification` for every batch member; `submit_peer_review` calls
   `send_review_received_notification`; `expire_pooled_reviews` calls
   `send_review_expired_notification`.
4. Extend `reminders.send_peer_review_deadline_reminders` to also select pooled reviews
   approaching expiry (`state=TO_REVIEW`, `batch__due_at` inside the reminder window), reusing
   the existing `coursework.peer_review_deadline` purpose and idempotency-key shape keyed by
   review id and due date, instead of adding a parallel "expiry approaching" job.

Verification
- `uv run pytest tests/coursework` -> pass; a batch whose window expires with 2 of 3 reviews in
  scores on the median of the 2, the third review moves to `EXPIRED`, and the reviewee is never
  left in `IN_REVIEW` past `due_at`; a late submission before scoring counts, one after scoring
  is rejected.
- `uv run pytest tests/mail` (or wherever purpose-registration is asserted) -> the four new
  purposes and the extended deadline-reminder query are covered.
- `testproject`: `manage.py jobs_ingress_selftest`-equivalent smoke for
  `coursework.expire_pooled_reviews` under the configured jobs backend.

Done when
- [ ] Every pooled `PeerReview` past `due_at` and still `TO_REVIEW` becomes `EXPIRED` within one
  scheduler tick, and its batch scores as soon as it is fully resolved.
- [ ] Four new mail purposes exist, each idempotent per row id, reusing `mail.send()`.
- [ ] The existing three `reminders.py` purposes are unchanged; the peer-review deadline
  reminder now also covers pooled `due_at`.

Docs
- `community_base/coursework/README.md` (from C5.2f): notification purposes and the expiry job.

## C5.2ga Unify coursework mail template-key validation

Repository: community-base. Depends on: C1.3, C5.2g. Freeze required: no.
Related: DataTalksClub/community-base#329; scoped correction for gap 1 of #323.

Goal

Make the existing coursework mail purposes work through both shared mail backends with one template-key contract, preserving current templates, messages, delivery policy and site UI. This addresses gap 1 of #323; it does not implement that issue's new self-paced behavior or change notification counts.

Read first

- `community_base/mail/service.py`, `relay.py`, `backends/ses_local.py` and the mail README.
- `community_base/coursework/notifications.py` and `reminders.py`.
- `tests/mail/test_ses_local.py`, `test_relay_catalog.py` and the coursework notification tests.
- `docs/01-decisions.md`, `docs/02-architecture.md`, and the owner's current `coding-standard.md` in the shared checkout (read-only; this standard is not yet in main).

Steps

1. Reproduce rejection of the existing dotted coursework purposes through the local SES file-template path with a fake SES client, before changing implementation.
2. Reuse one safe template-key policy for both mail backends. Preserve existing public imports and backend-specific exception contracts. Avoid site-specific key translations, renaming purposes or introducing a second catalog.
3. Keep existing subject/body rendering, override-loader behavior, delivery idempotency and security boundaries intact. Reject unsafe paths and invalid keys before file access, loader execution or provider calls as appropriate.
4. Document the shared key contract and focused compatibility correction.

Verification

- `uv run pytest tests/mail tests/coursework`: pass, with all existing coursework purposes sent through local file templates using only fake SES.
- Demonstrate the new relevant regression fails on the unchanged implementation and passes after the fix.
- Verify unsafe path separators, traversal/leading-dot forms and overlength keys remain rejected, and existing valid underscore/hyphen keys still work.
- `uv run pytest tests/test_boundaries.py`: pass; package quality gates and plan check pass.
- Run and report both site consumer suites separately under P16. No live emails, cloud mutations or site pin changes.

Done when

- [ ] Existing coursework purposes render and deliver through fake SES using file templates.
- [ ] Both mail backends share one key contract while preserving backend-specific failures.
- [ ] Existing rendering, idempotency, override and unsafe-key checks remain covered and pass.
- [ ] Package and both consumer checks are reported separately; adoption needs a later tagged release.

Docs

- `community_base/mail/README.md`, `CHANGELOG.md`, phase-5 issue entry and `docs/plan/STATUS.md`.

No template, route, schema, scoring, date policy, pooled batch behavior, notification count or site UI changes belong to this slice. Other #323 gaps remain open. AISL and DTC are unchanged until separately reviewed adoption.

## C5.2h Certificate eligibility, learner-requested issuance, and banner-generator artifact seam

Repository: community-base. Depends on: C5.2f.

Read first
- `community_base/coursework/certificates.py` (`issue_certificate`, today staff/API-key only:
  `coursework/studio_views.py::certificate_issue`, `curriculum/api_views.py::issue_certificate`).
  There is no eligibility check and no automatic issuance anywhere in the package today; both
  exist only in the AISL donor (`content/services/peer_review_service.py`
  `check_certificate_eligibility`, `issue_certificates_for_course`), which never got ported.
  "Certificate on request rather than automatic" is therefore a package feature addition, not a
  behaviour change within the package -- the behaviour change is on the AISL site, which retires
  its own local automatic issuance in A5.1.
  Its `pdf_url` field is never populated by anything (grep confirms only the model and its
  migration reference it); the package's `curriculum.Certificate.url` field is already
  generically named and needs no rename regardless of the artifact-format answer below.
- `community_base/events/integrations/hooks.py` and `community_base/events/settings_keys.py`:
  the established pattern for a site-supplied external-service seam the package must not import
  directly (`EVENT_BANNER_GENERATOR`, resolved through `community_base.kernel.hooks.Hook`
  /`_callback`, default `None`). Use the same shape for the certificate artifact generator rather
  than inventing a new configuration mechanism.
- `community_base/coursework/api_views.py` for the session-authenticated member-API route shape
  (`update_enrollment_preference`).
- `community_base/curriculum/models.py` `UnitProgress`, `Cohort.effective_modules`,
  `Cohort.min_projects_to_pass`.

Open questions for the owner (do not decide these; implement whichever answer comes back)
1. Learners who already meet the certificate conditions under AISL's current automatic issuance:
   recommend leaving their existing `CourseCertificate` rows alone (grandfathered) and applying
   the new request-based rule only going forward, per the issue's own suggested default. Since
   nothing today populates an artifact for any of them (`pdf_url` is unconditionally empty),
   recommend their certificate page keeps working with no artifact unless the learner chooses to
   request one under the new flow, in which case the request should succeed immediately (they
   already qualify) and simply attach the generated artifact to their existing certificate row
   rather than being refused as "already issued". This is an AISL-side migration decision
   (A5.1), but the package's request endpoint should not special-case "already has a certificate"
   as a rejection, so it needs the answer before A5.1 can rely on it.
2. Certificate artifact format: PDF, image, or both. `Certificate.url` is a single URL field
   either way, so the model needs no change for either answer; the banner-generator seam
   (`COURSEWORK_CERTIFICATE_GENERATOR` below) is designed to return one URL and one `format`
   value so it does not need redesigning once this is answered, but the site adapter's own call
   to banner-generator (a site concern, outside the package) does differ by answer.

Steps
1. `certificates.py`: `certificate_eligibility(enrollment) -> CertificateEligibility` (`eligible:
   bool`, `reasons: list[str]`), generalizing the donor's four conditions to the package's model:
   every unit in `cohort.effective_modules()` completed (`UnitProgress`); at least
   `cohort.min_projects_to_pass` submissions with `passed=True`
   (`ProjectSubmission.volunteer_review_only=False`); for a pooled project, the learner's own
   `reviewed_enough_peers` also true on those submissions (their outgoing reviews, not just
   incoming). Mode-agnostic: works the same for a cohort or a self-paced course, since the
   package never had a mode-specific automatic-issuance path to preserve.
2. `COURSEWORK_CERTIFICATE_GENERATOR` setting in `kernel/conf.py` `DEFAULTS` (default `None`),
   `community_base/coursework/integrations.py` mirroring
   `events/integrations/hooks.py::generate_banner` exactly: `generate_certificate_artifact(enrollment,
   certificate)` resolves the configured callable, raises `ImproperlyConfigured` if unset
   (matching `process_recording`'s precedent -- a learner-triggered request with no generator
   configured is an operator error worth surfacing loudly, not a silent no-op like
   `generate_banner`'s), validates the returned URL with the existing `_safe_url` shape. The
   site's callable owns its own endpoint and token entirely (for AISL: `BANNER_GENERATOR_FUNCTION_URL`/
   `BANNER_GENERATOR_AUTH_TOKEN` read through AISL's own `IntegrationSetting`/`get_config`); the
   package never sees them, satisfying "must not import from any site application."
3. `request_certificate(enrollment)` service: checks `certificate_eligibility`; if eligible,
   calls `generate_certificate_artifact`, then the existing `issue_certificate(enrollment,
   url=...)`. Member API route `POST courses/<slug:course_slug>/cohorts/<slug:cohort_slug>/certificate-request`,
   `authentication="session"` (same shape as `update_enrollment_preference`), returning the
   eligibility reasons on refusal.
4. Studio: an eligibility column/badge on the existing `certificates.html` list
   (`coursework_studio_certificates`) so staff can see who qualifies without issuing for them.

Verification
- `uv run pytest tests/coursework` -> pass; an ineligible enrollment's request is refused with
  reasons; an eligible one calls the configured generator and issues a certificate with its
  returned URL; an unconfigured generator raises `ImproperlyConfigured` rather than issuing a
  certificate with no artifact.
- `uv run pytest tests/test_boundaries.py` -> pass (no site imports; the generator is reached
  only through the `COURSEWORK_CERTIFICATE_GENERATOR` dotted-path hook).

Done when
- [ ] `certificate_eligibility` reuses existing package fields (`min_projects_to_pass`,
  `passed`, `reviewed_enough_peers`, `UnitProgress`) with no site-specific rule baked in.
- [ ] `COURSEWORK_CERTIFICATE_GENERATOR` follows the `EVENT_BANNER_GENERATOR` pattern exactly:
  declared in `kernel/conf.py`, resolved through a dotted path, package-side code never
  references an endpoint URL or token.
- [ ] The two owner questions above are posted back to issue #256 and answered before A5.1 (map
  AISL courses) starts, since A5.1 needs the already-qualified-learners answer to write its data
  migration.

Docs
- `community_base/coursework/README.md` (from C5.2f): eligibility rule, the request endpoint,
  and the `COURSEWORK_CERTIFICATE_GENERATOR` seam with a worked example matching
  `events/README.md`'s style.

## C5.2i Shared inline homework steps and resumable drafts

Repository: community-base. Depends on: C5.1c. Freeze required: no. Related: DataTalksClub/community-base#292, AI-Shipping-Labs/website#1778, DataTalksClub/website#432.

Goal: ship an optional `community_base.homework_steps` app that either site can install alongside
`curriculum` to show Introduction, one question per step, and Review & submit inside a homework
unit. AISL currently installs `curriculum` but owns its `content.Homework`, `Question`, `Submission`
and `Answer` rows. DTC currently serves site-owned `courses` homework rows and routes while its
coursework cutover remains in #415. The stepper must not require `community_base.coursework`.

Read first
- `docs/01-decisions.md` D2, D8 and D18; `docs/02-architecture.md` app boundaries.
- `community_base/curriculum/views.py::_bound_homework_context` and its unit template.
- `community_base/coursework/submissions.py::submit_homework` and `homework_form_context`.
- `../ai-shipping-labs/content/models/homework.py` and its homework unit POST service.
- `../dtc-website/_docs/specs/04-courses-and-cohorts.md` assessment ownership.

Steps
1. Add a standalone optional Django app with a draft row uniquely keyed by authenticated user
   and an opaque, site-supplied assignment key. Store answers and any host-defined final-form
   fields by stable key, plus a revision; seed an initial draft from already submitted answers
   when editing an existing submission, so a final submit supplies the full answer set;
   do not FK drafts to either site's homework, coursework, cohort or submission model. A draft write
   updates one answer, validates its question against the server-resolved assignment, and uses a
   revision precondition so stale tabs cannot overwrite newer answers. Bound answer size and shape.
2. Define a Python adapter contract: resolve assignment, course context and ordered questions;
   provide stable assignment/question/option keys, question type and prompt, introduction,
   instructions, host-defined final-form fields, existing submitted answers, read/write/submit
   eligibility and reason, and a
   final-submit callback. Re-check eligibility on every write and final submit. Host code, not a
   client-supplied assignment key, selects the assignment and authorizes the learner.
3. Ship an overridable accessible step partial and shared GET/draft-save/final-submit handlers.
   Plain POST navigation works without JavaScript; progressive autosave may enhance it. Render
   Introduction, one step for each ordered question, then Review & submit. Questions with stable
   IDs remain associated with their draft if content is re-imported or the display order changes.
   Show saved/saving/error status and preserve the typed answer on a failed save.
4. Keep draft persistence separate from all `Submission`/`Answer` writes, scoring, events and
   notifications. Final submit atomically reads the latest draft and delegates to the host's
   existing submission path. Clear the draft only after successful submission; retain it on
   validation, closure or server failure. The host remains authoritative for deadline, access,
   scoring, reveal, resubmission, and notifications. Existing submitted answers prefill a new
   session; the existing non-step form and POST remain functional.
5. Provide the package-owned coursework adapter over its current `Homework` and
   `submit_homework` service, enabled only when `community_base.coursework` is installed. AISL
   implements its own adapter under #1778; DTC uses its site-owned adapter under #432 until #415
   can adopt the package adapter. Public
   page styling and route placement remain site-owned under D18.

Verification
- `uv run pytest tests/homework_steps tests/coursework tests/curriculum` passes with both a
  curriculum-only synthetic site and a coursework-enabled synthetic site. Check collected counts.
- A saved answer survives refresh, moving away and back, reordering, and a second browser session;
  stale revision returns a conflict without changing the saved answer.
- No draft request creates or changes a submission, score or notification. Final submit calls the
  adapter once with the latest authorized answers; failed submit keeps the draft.
- An anonymous or unauthorized request cannot read or mutate another learner's draft; forged
  question and assignment keys are rejected. Closed homework cannot be submitted through a stale
  page. Legacy form POST remains accepted.
- `uv run pytest tests/test_boundaries.py` passes; `uv run python scripts/plan.py check` is OK.
- Run the package quality gates, then test both consuming sites against the package change and
  report package, AISL and DTC results separately. If a consumer cannot install it yet, state
  that explicitly rather than claiming the package run covers it.

Done when
- [ ] The optional app installs and renders with `curriculum` but without `coursework`.
- [ ] Each question saves and resumes independently of final submission, with stale-write safety.
- [ ] Final submission uses the host adapter and preserves existing policy and legacy routes.
- [ ] The coursework adapter and the standalone adapter contract are documented for both sites.
- [ ] Package and both consumer gates are reported separately.

Docs
- `community_base/homework_steps/README.md`, `community_base/coursework/README.md`, `CHANGELOG.md`.

## C5.2j Shared learner homework state and accepted-submission snapshot

Repository: community-base. Depends on: C5.2i. Freeze required: no. Related:
DataTalksClub/community-base#301, AI-Shipping-Labs/website#1778,
DataTalksClub/website#432.

Goal: give either host a model-independent learner state and accepted-submission snapshot for
homework navigation and review. A saved draft is not an accepted submission, and an identical
draft seeded from an accepted submission is not pending work.

Read first
- `community_base/homework_steps/types.py`, `views.py`, `coursework.py`, and `services.py`.
- `community_base/homework_steps/README.md` and `docs/02-architecture.md`.

Steps
1. Extend the generic assignment descriptor with normalized availability and an optional accepted
   snapshot containing answers, final fields, and the accepted time. Keep existing descriptor
   fields working for v0.5.10 adapters.
2. Provide a pure six-state mapping and a read-only per-learner helper suitable for both a host
   navigation row and the shared homework page. It must never create a draft; compare the complete
   normalized draft and accepted snapshots rather than inferring edits from draft existence or
   revision.
3. Reuse one state fragment in package templates. On closed/scored assignments, show accepted
   answers and time as the primary review; label any saved unsent draft separately and omit submit
   controls. Do not render cohort counts or another learner's data.
4. Map package coursework availability and `Submission.submitted_at` into the descriptor without
   importing coursework from the optional app path. Preserve draft-help and retired-choice fallback
   behavior.
5. Document the generic host contract and the coursework adapter contract.

Verification
- `uv run pytest tests/homework_steps tests/coursework tests/curriculum` passes with the optional
  app both installed and absent; report collected counts against the same-checkout baseline.
- Synthetic tests cover all six labels, an identical seeded draft, a first saved answer without a
  submission, and closed/scored homework without an accepted submission.
- Closed/scored review tests prove that accepted values and time stay primary, a differing saved
  draft is visibly separate, and there is no submit control.
- The nav helper is read-only and returns the same value and accessible label as the page fragment.
- `uv run pytest tests/test_boundaries.py`, package quality gates, and
  `uv run python scripts/plan.py check` pass.
- Test both consuming sites against the change and report package, AISL, and DTC results
  separately. Do not claim consumer coverage from the package suite.

Done when
- [ ] Both hosts can render one package-owned learner-state fragment in navigation and beside
  their due line using the same per-learner value.
- [ ] Accepted answers and time remain the primary review after closure or scoring; unsent drafts
  remain clearly separate.
- [ ] Existing v0.5.10 adapter behavior, draft help, and stale-choice fallback remain compatible.
- [ ] Package and consumer gates are reported separately before release or adoption.

Docs
- `community_base/homework_steps/README.md`, `community_base/coursework/README.md`, `CHANGELOG.md`.

## C5.2ja Preserve attempted homework final fields on review errors

Repository: community-base. Depends on: C5.2i. Freeze required: no. Related:
DataTalksClub/community-base#324. This fix needs the `handle_stepper` and review-form contract
released in C5.2i. The snapshot code that introduced the regression shipped in v0.5.11, while
C5.2j remains in progress for its other acceptance obligations; this repair does not complete them.

Goal: keep attempted final-field values in the open review form after a validation error or stale
draft revision, while preserving saved data, closed reviews, routes and markup.

Read first
- `community_base/homework_steps/views.py`, `services.py`, and `templates/homework_steps/_stepper.html`.
- `tests/homework_steps/test_flow.py` and `community_base/homework_steps/README.md`.

Steps
1. Reproduce the lost input on invalid URL and stale revision responses with behavior tests.
2. Use attempted final fields for open review form rows when supplied by the error handlers.
3. Preserve accepted-snapshot selection for closed reviews and leave failed writes unapplied.
4. Document the form-value contract and regression fix.

Verification
- `uv run pytest tests/homework_steps` passes after both new tests fail against the old view.
- Invalid URL returns 400 and stale revision returns 409; each form shows its attempted value and
  the saved draft remains unchanged.
- Existing submitted, closed, read-only, save and submit tests pass.
- Package quality gates, boundary test, `uv run python scripts/plan.py check`, and both consumer
  suites pass with separately reported results.

Done when
- [ ] Both failures are reproduced against the old view and pass after the fix.
- [ ] Open error forms retain attempted values without persisting failed writes or changing closed
  review behavior.
- [ ] Package and both consumer checks pass.
- [ ] A tagged fix is available before DTC raises its package pin.

Docs
- `community_base/homework_steps/README.md`, `CHANGELOG.md`.

## C5.2k Per-project learner row: CMP's project lifecycle presentation

Repository: community-base. Depends on: C5.2g. Freeze required: no. Related:
DataTalksClub/community-base#312, AI-Shipping-Labs/website#1696 (A5.1 adopts it),
DataTalksClub/website (replaces its forked copy).

Goal: move the course management platform's learner-facing per-project presentation, the row of
the course page Projects table, into `community_base.coursework` unchanged in behaviour, so both
sites render a project's stage, badge, pill surface, link and deadline from one owner. The owner
decided on 2026-09-28 to keep CMP's established model and labels: this issue does not redesign
the lifecycle and does not model it on `homework_steps/state.py`.

Read first
- `~/git/course-management-platform/courses/views/course_projects.py`
  (`update_project_with_additional_info`) and `courses/templates/courses/course.html` (Projects
  table).
- `~/git/dtc-website/courses/views/course_projects.py`, `courses/coursework_badges.py` and
  `courses/templates/courses/course.html` (Projects rows).
- `community_base/coursework/models.py` (`Project`, `ProjectState`, `ProjectSubmission.review_state`,
  `PeerReview`), `community_base/coursework/README.md` "Assessment modes".

Steps
1. Add a pure function that takes a `Project`, the learner's `ProjectSubmission` or `None`, and
   the learner's completed required review count, and returns a frozen row: stage, submitted,
   badge label, CMP badge class, pill surface (`past`, `your_move`, `done`, `result`), score, link
   target (`submit`, `eval`, `results` or none) and the deadline to show with its kind. Labels
   stay exactly as CMP and DTC have them: `CL` Closed; `CS` Open / Submitted; `PR` Not submitted /
   Review / Review completed once completed non-optional `SU` reviews reach
   `number_of_peers_to_evaluate`; `CO` Not submitted / Passed ({score}) / Failed ({score}).
2. Pooled mode, as the models define it: a pooled project's `state` is only `CS` or `CL`, so a
   submitted learner's stage comes from `ProjectSubmission.review_state` (`AW` as `CS`, `IR` as
   `PR`, `SC` as `CO`), and the review deadline is the learner's batch `due_at` when known. A
   closed project reads Closed in both modes.
3. Add a per-cohort builder that loads the learner's submissions with the completed-review count
   and pooled batch deadline in a constant number of queries, and accepts a site URL resolver so
   the site keeps its routes.
4. Ship an overridable row include for a course page Projects table using only `cb-` hooks.
5. Document the contract in `community_base/coursework/README.md` and `CHANGELOG.md`.

Verification
- `uv run pytest tests/coursework` passes; tests cover every state by submitted combination in
  both modes, the review-completed threshold at, below and above `number_of_peers_to_evaluate`,
  that optional and unsubmitted reviews do not count, and a constant query count as projects grow.
- `uv run pytest tests/test_boundaries.py tests/test_template_contract.py` passes;
  `uv run python scripts/plan.py check` is OK; package quality gates pass.
- Test both consuming sites against the change and report package, DTC and AISL results
  separately. A consumer that cannot take the change until a release is said to be so.

Done when
- [ ] One package function returns the CMP row for every state and submitted combination.
- [ ] Pooled projects derive their stage from `review_state` without changing deadline mode.
- [ ] A row include renders the row with `cb-` hooks only.
- [ ] Package, DTC and AISL results are reported separately; DTC adoption is prepared against a
  tagged release.

Docs
- `community_base/coursework/README.md`, `CHANGELOG.md`.

## C5.2l Self-paced coursework: one review email per batch, batch sweep, optional dates, homework reveal on submit

Repository: community-base. Depends on: C5.2g, C5.2i, C5.2k. Freeze required: no. Related:
DataTalksClub/community-base#323 (owner-approved), AI-Shipping-Labs/website#1696 (A5.1 adopts it).

Goal: close gaps 2 to 5 of #323 against the owner's self-paced spec: no deadlines, homework
answers visible right after submit, and project submissions accumulated until n+1 are waiting,
at which point every batch member gets one email asking them to review n peers. Gap 1 (dotted
mail template keys on `ses_local`) is C5.2ga, owned separately, and is not part of this issue.

Read first
- `community_base/coursework/pooling.py`, `notifications.py`, `projects.py`, `project_rows.py`.
- `community_base/coursework/submissions.py`, `scoring.py`, `review.py`, `reminders.py`.
- `community_base/homework_steps/types.py`, `coursework.py`, `views.py` and `_stepper.html`.
- Issue #323 "Gaps" 2 to 5 and its acceptance list.

Steps
1. Emails: in pooled mode `try_form_batch` sends exactly one `coursework.pool_ready` email per
   batch member, carrying the review count, the batch due date and one direct link per assigned
   review. It no longer also sends `coursework.review_assigned`, which stays the deadline-mode
   email. Review links come from a new `COURSEWORK_REVIEW_URL_BUILDER` hook whose default
   reverses the package route `coursework_projects_eval_submit` against `SITE_URL`.
2. Sweep: `form_pooled_batches(project)` forms every batch the waiting submissions allow (loop
   while at least n+1 wait). `submit_project` calls it after commit, and a durable job
   `coursework.form_pooled_batches`, scheduled every 15 minutes like
   `coursework.expire_pooled_reviews`, runs it for every open pooled project.
3. Dates: `Homework.due_date`, `Project.submission_due_date` and `Project.peer_review_due_date`
   become nullable. Model validation still requires them for a dated cohort. A pooled learner's
   project row has no deadline until they are in a batch, then the batch `due_at`. Every reader
   of these fields tolerates `None`, and deadline-mode behaviour is unchanged.
4. Homework reveal: `Homework.reveals_on_submit` (`cohort.mode == "self_paced"`). Submitting such
   a homework scores it for that learner, refreshes the leaderboard, and locks resubmission; the
   learner sees their homework as scored. `homework_steps` gains an optional host-supplied
   per-question result descriptor (correctness, correct answer, explanation), rendered on the
   Review step and on each question step. The coursework adapter supplies it on submit for a
   self-paced homework and only after scoring for a dated one.

Verification
- `uv run pytest tests/coursework tests/homework_steps` passes, including: a pooled batch of 4
  sends exactly 4 emails, each with 3 review links and the batch due date; 3 submissions form no
  batch, the 4th forms one, the 5th waits; 8 waiting submissions form two batches from one sweep
  run; a missed batch is formed by the scheduled handler; a self-paced project and homework save
  without dates while a dated one still requires them; a pooled row shows no deadline before
  assignment and the batch `due_at` after; a self-paced homework reveals results right after
  submit and a dated one reveals nothing before scoring.
- `uv run python testproject/manage.py makemigrations --check --dry-run` -> no changes.
- `uv run pytest tests/test_boundaries.py`; `uv run python scripts/plan.py check` is OK;
  package quality gates pass.
- Test both consuming sites against the change and report package, DTC and AISL results
  separately.

Done when
- [ ] A pooled batch of n+1 sends exactly n+1 review-request emails with direct review links.
- [ ] Every possible batch forms per trigger, and a scheduled sweep forms missed batches.
- [ ] Self-paced projects and homework need no due dates and show none before assignment.
- [ ] Self-paced homework is scored and revealed on submit; dated homework reveals only after
  scoring.
- [ ] Package, DTC and AISL results are reported separately; a tagged release precedes adoption.

Docs
- `community_base/coursework/README.md`, `community_base/homework_steps/README.md`, `CHANGELOG.md`.

## C5.2m Coursework adoption gaps: project module, optional commit id, optional Studio and member API

Repository: community-base. Depends on: C5.2l. Freeze required: no. Related:
DataTalksClub/community-base#350, AI-Shipping-Labs/website#1696 (A5.1 projects slice, phase 2).

Goal: close the package gaps that block AISL from adopting `community_base.coursework` for course
projects (findings F3, F4 and F5 of the #1696 projects plan). CMP and DTC behaviour is unchanged
by default.

Read first
- `community_base/coursework/models.py` (`Project`, `ProjectSubmission`, `Homework.module`).
- `community_base/coursework/projects.py` (`submit_project`).
- `community_base/coursework/apps.py` and `community_base/curriculum/apps.py`
  (`events_dependent_surfaces_active`).
- `community_base/kernel/conf.py`.

Steps
1. Add a nullable `Project.module` FK to `cb_curriculum.Module` (`SET_NULL`,
   `related_name="projects"`), mirroring `Homework.module`.
2. Add `Project.commit_id_field` (default `True`). `ProjectSubmission.commit_id` becomes
   `blank=True`, and `ProjectSubmission.clean` requires it only when the toggle is on, so
   `submit_project` (which calls `full_clean`) enforces it. With the toggle off, `submit_project`
   stores no commit id and the package project page hides the input.
3. Gate the Studio section registration and the member `api_views` import in
   `CourseworkConfig.ready()` on `COMMUNITY_BASE["COURSEWORK_STUDIO_ENABLED"]` and
   `COMMUNITY_BASE["COURSEWORK_MEMBER_API_ENABLED"]`, both default `True`. The gate cannot key on
   `community_base.accounts` being installed: DTC does not install it and keeps today's
   registration.
4. One migration, `cb_coursework.0006`, after `0005_authored_homework_metadata`.

Verification
- `uv run pytest tests/coursework` passes, including `tests/coursework/test_adoption_toggles.py`.
- `uv run python testproject/manage.py makemigrations --check --dry-run` -> no changes.
- `uv run pytest tests/test_boundaries.py`; `uv run python scripts/plan.py check` is OK.
- Report package, DTC and AISL consumer results separately.

Done when
- [ ] A project can belong to a module and survives the module's deletion.
- [ ] A project with `commit_id_field=False` accepts a link-only submission; the default still
  requires a commit id.
- [ ] With both settings `False`, a site without `community_base.accounts` boots with no
  coursework Studio section and no coursework member API routes.
- [ ] Released as `v0.5.19`, after `v0.5.18`.

Docs
- `community_base/coursework/README.md`, `CHANGELOG.md`.

## C5.2n Shared embeddable project submission form

Repository: community-base. Depends on: C5.2m. Freeze required: no. Related:
AI-Shipping-Labs/website#1696 (owner requirement comment 5907906743), CMP
`courses/templates/projects/project.html`.

Goal: one project submission form for CMP, DataTalks.Club and AISL, owned by `cb_coursework` and
embeddable inside a host's own reader or syllabus unit. It ports CMP's "Submission details": GitHub
link, commit id with a "Where do I find the commit ID?" disclosure, learning in public links, time
spent, an optional certificate name and a status line, each field with a help tooltip. The FAQ
contribution field is not part of the shared form (owner decision 2026-09-30); a host adds it through
the extension point.

Read first
- `community_base/coursework/projects.py` (`submit_project`, `clean_learning_in_public_links`).
- `community_base/coursework/views.py` (`project_view`) and `templates/coursework/project.html`.
- `community_base/coursework/templates/coursework/_homework_form.html` (the embeddable homework
  form this mirrors).
- CMP `courses/views/project_submission_edit.py` and
  `courses/templates/include/learning_in_public_links.html`.

Steps
1. `project_accepts_submissions(project, now)` and `submission_editable(project, submission, now)`
   in `projects.py`: edits are allowed while the project collects submissions and before
   `submission_due_date`, and a pooled submission locks once it leaves `AW`.
2. `submit_project(..., before_save=callable)` runs a host callback on the populated submission
   before `full_clean`.
3. `project_forms.py` (with `project_form_fields.py`): `ProjectSubmissionForm` (fields shaped
   by the project toggles and the enrollment's `disable_learning_in_public`; GitHub repository link, 7 to 40 hex commit id, links
   de-duplicated and capped, hours as a number of at least zero; locked after the deadline),
   and, in `project_submission_flow.py`, `build_project_submission_form`,
   `process_project_submission` and `ProjectSubmissionOutcome`.
   The save keeps stored `problems_comments` and `faq_contribution_url`, which the form does not
   show, and fires `COURSEWORK_PROJECT_SUBMITTED` / `COURSEWORK_PROJECT_DELETED` on commit.
4. `COMMUNITY_BASE["COURSEWORK_PROJECT_CERTIFICATE_NAME_FIELD"]` (default `True`) plus the
   `certificate_name_field` form argument, so a site (AISL: off) or a course can hide the field.
5. Extension point: a subclass declares extra fields and writes them in `apply_extra_fields`; the
   partial renders them after "Time spent", or includes the subclass's `extra_fields_template`.
6. `coursework/_project_submission_form.html` (with `_form_help.html` and
   `community_base/coursework_project_form.js`) uses only structural `cb-` classes and
   `data-project-*` attributes. The package project page includes it.
7. No migration: the `faq_*` columns stay untouched (C5.2o retires them).

Verification
- `uv run pytest tests/coursework` passes, including
  `tests/coursework/test_project_submission_form.py` and `test_project_submission_flow.py` (with
  a host-added FAQ field).
- `uv run python testproject/manage.py makemigrations --check --dry-run` -> no changes.
- `uv run pytest tests/test_boundaries.py tests/test_static_asset_references.py`;
  `uv run python scripts/plan.py check` is OK.
- Report package, DTC and AISL consumer results separately.

Done when
- [ ] The shared partial renders GitHub link, commit id, learning in public links, time spent and
  the status line, and the certificate name only when enabled.
- [ ] Invalid input re-renders with field errors; edits lock after the deadline.
- [ ] A host subclass adds, validates and saves an extra field without forking the partial.
- [ ] Released after C5.2m (`v0.5.19` or later), coordinated with the release owner.

Docs
- `community_base/coursework/README.md`, `docs/02-architecture.md`, `CHANGELOG.md`.

## C5.2o FAQ contribution redesign and retirement of the `faq_*` project fields

Repository: community-base. Depends on: C5.2n. Freeze required: no. Related:
AI-Shipping-Labs/website#1696 (owner decision 2026-09-30).

Goal: replace pull-request-based FAQ contributions with the owner's redesign (not through a pull
request), then retire `Project.faq_contribution_field` and `ProjectSubmission.faq_contribution`,
`faq_contribution_url` and `project_faq_score`. Until then the columns stay, imported CMP and DTC
data keeps its values, the shared form never renders them, and DataTalks.Club adds its FAQ field in
`dtc-website` through the C5.2n extension point.

Read first
- `community_base/coursework/projects.py`, `scoring.py` and every reader of the `faq_*` fields.
- DataTalks.Club's FAQ subclass of `ProjectSubmissionForm`, once it exists.

Steps
1. Owner designs the new FAQ contribution flow; record it here before building.
2. Build it; move DataTalks.Club off its form subclass field.
3. Inventory the `faq_*` values in CMP and DTC data, decide their archive, then drop the columns
   in one migration with a documented rollback.

Verification
- To be written with the design.

Done when
- [ ] The new FAQ flow ships and no reader of the `faq_*` fields remains.
- [ ] The columns are dropped with a verified data archive.

Docs
- `community_base/coursework/README.md`, `CHANGELOG.md`.

## C5.2p Guard coursework automation with a consumer-resolved runtime switch

Repository: community-base. Depends on: C5.2l, C7.12e, C7.12f. Freeze required: no. Related:
DataTalksClub/community-base#376; AI-Shipping-Labs/website#1696 Phase 5A.

Goal: let a consumer populate shared coursework shadow rows without package automation
forming or scoring pooled batches, expiring pooled reviews, invoking coursework hooks, or
sending coursework reminders before cutover. Preserve current automation for consumers that
do not opt out. Keep this package capability separate from the consumer rollout and from the
later schema/copy stage.

Baseline
- Start runtime implementation after C7.12e/f is officially complete. A pending
  dependency-bearing plan entry may be prepared earlier. Immutable v0.5.23 at
  `bf498039636e01e28831ad03a22bff912b9c5aff` is the corrected runtime baseline.
- Publish C5.2p in a later independently reviewed immutable package release. Do not rewrite,
  retag or append source to v0.5.23, and do not require a separate AISL v0.5.22-only adoption
  before package implementation.

Read first
- `community_base/coursework/apps.py`, `pooling.py`, `projects.py`, `review.py`,
  `reminders.py`, hooks and notifications. `community_base/coursework/settings_keys.py`
  does not exist at the v0.5.23 baseline and is a proposed new file.
- Existing `community_base/mail/settings_keys.py` for the package runtime-key declaration
  convention; do not claim a coursework declaration already exists.
- `community_base/config/registry.py` and `service.py`, especially `declare_if_absent`,
  consumer-first declaration, source precedence and worker reads. The current registry has
  no hidden-definition option, and its complete `definitions()`/`groups()` output feeds the
  staff Studio and configuration API.
- Jobs registry, local schedule dispatch, Relay ingress, due runner, sweep and retry paths.
- Issue #376's accepted guard boundary and AI-Shipping-Labs/website#1696 Phase 5A contract.

Steps
1. Declare `COURSEWORK_AUTOMATION_ENABLED` through the package config registry with boolean
   type, package default `true`, `django_settings_fallback=True`, operator documentation and
   `declare_if_absent`. The package imports no consumer module. A consumer declaration loaded
   first keeps its own metadata and default; a consumer with no declaration retains enabled
   package behavior. The registry service is the sole configuration owner. The definition is
   visible to staff operators under the existing Studio contract and creates no learner UI.
   Do not add a parallel `kernel.conf`, raw-setting owner or generic hidden-definition
   framework. Existing registry rendering is sufficient; add no config template, form or view
   work for this key. Preserve existing resolution order: stored database value, declared
   environment variable, declared Django fallback, then registry/call default.
2. Add one package-owned read-only policy/introspection owner used by every guarded entrypoint.
   Each call resolves the current effective value and returns an immutable contract with
   `enabled: bool`, `guard_version: str` fixed at `"1"`, and tuple-valued
   `guarded_handlers` and `guarded_operations`. Version 1 has these ordered names:
   - handlers: `coursework.form_pooled_batches`, `coursework.expire_pooled_reviews`,
     `coursework.send_homework_deadline_reminders`,
     `coursework.send_project_submission_deadline_reminders`, and
     `coursework.send_peer_review_deadline_reminders`;
   - operations: `try_form_batch`, `form_pooled_batches`, and `try_score_batch`.
   The helper exposes no stored value, secret, database row, consumer state or transport data.
   Consumers use this released contract instead of duplicating flag parsing, guard version or
   guarded-name inventories.
3. Resolve the policy at each call in web and worker processes. Guard `try_form_batch`,
   `form_pooled_batches` and `try_score_batch` before a coursework query, domain write, mail or
   hook. Preserve disabled returns exactly: `None`, `[]` and `False`, respectively. This also
   covers the existing submission and review callbacks that call these operations after the
   learner action commits.
4. Guard the registered formation and expiry handlers before a coursework query, domain write,
   mail or hook. Preserve disabled returns exactly: `{"formed_batches": 0}` and
   `{"expired": 0, "scored_batches": 0}`.
5. Guard all three registered reminder handlers before window evaluation, coursework query or
   mail. Each returns `{"reminders": 0}` while disabled. Cover both deadline and pooled
   peer-review reminder modes.
6. Keep all five handlers and both existing 15-minute pooled schedules registered at either
   flag value. Local or Relay dispatch may create and finish transport bookkeeping while false,
   but no coursework row, state, score, evaluation, marker, leaderboard, hook or mail may
   change.
7. Preserve intentional APIs outside the switch: `calculate_project_scoring`, explicit
   `persist_scored_submissions`, and deadline-mode Studio `score_project`. A later AISL copy may
   call the calculation/persistence pair intentionally; it must not call `score_project` or an
   actor-bearing convenience path.
8. Document the consumer contract, complete package review and gates, run both exact P16
   consumers, then publish and verify a new immutable guard release. AISL Phase 5A adoption is a
   separate site issue and remains open after this package capability is released.

Verification
- Config tests prove package-default enabled, consumer-first false, web and worker reads, and
  the unchanged order: environment `True` beats Django `False` without a stored row; absent
  environment lets Django `False` protect startup; stored database `False` beats environment
  `True`; clearing/re-enabling restores the existing fallback behavior. An unconfigured
  consumer keeps current enabled behavior.
- Policy tests prove `enabled` is resolved on each call, `guard_version` is stable, both ordered
  tuples match the guarded implementation, and the five handler names are registered. A caller
  can inspect the contract without importing a consumer or querying coursework rows.
- With the switch false and enough real `AW` submissions, direct `try_form_batch`,
  `form_pooled_batches`, registered formation dispatch and the submission callback create no
  batch/reviews, make no `AW -> IR` change, and invoke no hook or mail. Returns are exactly
  `None`, `[]` and `{"formed_batches": 0}` as applicable.
- With the switch false and a fully resolved real batch, direct and callback-driven
  `try_score_batch` creates no scores/evaluations, `SC` state, `scored_at`, leaderboard or hook
  effect and returns `False`. The intentional learner review submission itself remains intact.
- With the switch false and overdue real `TR` reviews, expiry returns
  `{"expired": 0, "scored_batches": 0}` and causes no `TR -> EX`, mail, scoring,
  evaluation, submission-state, scored-marker, leaderboard or hook effect.
- Each reminder handler runs against eligible rows and returns `{"reminders": 0}` with no mail.
  Peer-review coverage includes deadline and pooled rows.
- Local dispatch, signed Relay ingress, due execution and retry/recovery of the real registered
  names may update transport state but leave coursework rows, mail and hooks unchanged.
- Default-enabled regressions retain current formation, expiry/scoring, reminder mail, state and
  hook behavior. Tests prove calculation, intentional persistence and explicit deadline-mode
  Studio scoring remain available while automated actors are disabled.
- Focused tests and all package quality gates pass. Independent package acceptance and separate
  P16 results for AI Shipping Labs and DataTalksClub/website identify exact refs and raw
  baseline/linked outcomes before release.
- The release adds no model, migration, site path, dependency pin, learner UI, mail-sender
  integration, generic registry-presentation option, AISL diagnostic endpoint, schema or copy
  implementation. It adds no configuration template, form or view change.

Done when
- [ ] Package default-enabled and consumer-first disabled resolution are proven in web and
      worker contexts, including environment-before-Django fallback, stored override precedence
      and re-enable behavior, with no generic framework reorder.
- [ ] One package policy owner reports the effective value, guard version, five exact handlers
      and three exact operations, and every guarded entrypoint uses that owner.
- [ ] Every automatic formation, pooled-scoring, expiry and reminder entrypoint performs the
      exact successful no-op before coursework domain, mail and hook effects while false.
- [ ] Public return shapes, registration, both pooled schedules and transport bookkeeping
      compatibility remain stable at either flag value.
- [ ] Intentional calculation, persistence and deadline-mode Studio scoring remain usable.
- [ ] Package gates, independent review and both exact P16 consumers pass and are reported
      separately.
- [ ] A new immutable release after v0.5.23 is published and verified. AISL Phase 5A pin,
      diagnostics, false database override, deployment and quiescence proof remain open in
      AI-Shipping-Labs/website#1696.

Runtime scope
- Package config declaration and one cohesive coursework automation policy/helper.
- `community_base/coursework/pooling.py` and `reminders.py` guard calls.
- Focused policy, actor, handler and transport tests; avoid growing existing oversized files when
  a cohesive focused module is clearer.
- No new function over 30 lines, new source/test file over 300 lines, ternary expression, or
  filtered/nested comprehension. Record added, moved and deleted runtime separately.

Docs
- `community_base/coursework/README.md`.
- `CHANGELOG.md` in the later guard release.
- `docs/plan/phase-5.md` and `docs/plan/STATUS.md`.

## C5.2q Preserve 500-character project repository URLs

Repository: community-base. Depends on: C5.2m, C5.2n. Freeze required: no.

Goal
Preserve the existing AISL 500-character project URL contract in shared storage and the
embeddable project form. At package baseline `c3f726f`, both `github_link` model validation
and the explicit form field cap values at 200. Widen only this capacity, keeping existing
URL validation, host rules, controls, routes, authorization and lifecycle behavior.
This is package capability, separate from data adoption and backend retirement.

Read first
- `AGENTS.md`, `docs/PROCESS.md`, `docs/04-quality-gates.md`, architecture and coding standard.
- D1, D8, D15, D18, D33 and D41; playbooks P15 and P16.
- `community_base/coursework/models.py`, `project_forms.py`, `projects.py` and
  `project_submission_flow.py`; all released coursework migrations and their actual leaf.
- `tests/coursework/test_models.py`, `test_projects.py`, `test_project_submission_form.py`,
  `test_project_submission_flow.py` and `project_form_support.py`.
- AISL `content/models/peer_review.py`: `ProjectSubmission.project_url` has `max_length=500`.

Steps
1. Record exact baseline, ownership and migration graph. Verify C5.2m and C5.2n are done;
   check for overlapping URL-width work. Use an isolated worktree and all package extras.
   Record the touched-app baseline before runtime edits. Keep this change outside the
   separately owned C5.2p/v0.5.25 guard release inventory; coordinate later main/tag ordering.
2. Add one bounded behavior test owner covering valid URLs of exactly 200, 201 and 500
   characters, and rejection at 501. Demonstrate old model/form length rejection for 201/500
   before changing capacity, retaining valid 200 controls. Use valid fixed-host URLs and
   assert their exact lengths; unrelated URL/host errors are not length-sensitivity evidence.
3. Set only `ProjectSubmission.github_link` to `max_length=500`. Derive the existing form
   field maximum from that model field metadata, so capacity has one owner. Preserve
   requiredness, validators, default GitHub owner/repository checks, HTTP(S) form validation
   and the existing `github_hosts=None` extension. Do not add fields, schemes, endpoints,
   selectors or hooks. Keep both existing declaration edits at their current physical line
   count; do not grow oversized files or include an unrelated model refactor.
4. Generate one append-only AlterField migration from the actual current graph leaf. At
   baseline the leaf is `0006_project_module_commit_id_field`; reserve the next number
   explicitly before editing. Never modify released migrations or another field. Test fresh
   apply and forward/reverse/reapply with original valid rows at or below 200 characters.
   Round-trip a synthetic 500-character value under the new state, then remove only that
   synthetic row before the narrow-schema reverse. Compare original values and counts.
5. Document rollback limits: narrowing to 200 after longer writes cannot be called lossless.
   Never truncate or shorten input. Retain the widened schema when rolling back application
   code after longer writes, unless a separately rehearsed safe narrowing disposition exists.
   SQLite does not prove PostgreSQL varchar enforcement or populated-copy reversibility.
6. Run package gates and submit one focused PR. Require both P16 consumer verdicts at the
   actual submitted head. The sole on-call observer runs the supported watcher once; the
   orchestrator does not poll Actions. Release/pin work requires a separate coordinated
   immutable release and does not borrow the guard's CI or tag allocation.

Verification
- `uv sync --all-extras`; `make test tests/coursework` before/after -> pass, collected counts
  recorded against this checkout's baseline.
- `make test tests/coursework/test_project_url_width.py` -> model/form validate and preserve
  exact 200/201/500 values; 501 has a length-specific error and no persisted mutation.
  One accepted 500-character form save proves form-to-model integration. The existing input
  maxlength reflects 500; labels/help/fields/templates/layout remain unchanged.
- The same 500-character non-GitHub HTTP(S) link succeeds only through the existing host
  override; malformed/non-HTTP(S) form values and default GitHub path/host violations fail.
  Preserve model URLValidator semantics, which need not equal form scheme restrictions.
- Existing access, locked/deadline, enrollment and commit-toggle tests remain green.
  No project URL API exists at baseline; do not invent an API solely to test this change.
- Migration test -> only the URL field changes; original row values/counts survive forward,
  safe reverse and reapply. Fresh SQLite application passes. Report its PostgreSQL limits.
- `make lint`; `uv run ruff format --check .` -> exit 0.
- `uv run python testproject/manage.py check` -> no issues.
- `uv run python testproject/manage.py makemigrations --check --dry-run` -> no changes.
- On a fresh task-specific database:
  `DATABASE_URL=sqlite:////tmp/c5.2q-fresh.sqlite3 uv run python testproject/manage.py migrate`
  -> all migrations apply; never reuse or remove another session's database.
- `make test tests/test_boundaries.py`; `uv run python scripts/plan.py check`;
  `git diff --check` -> pass.
- On-call: `uv run python scripts/watch-ci.py --pr <N> --repo DataTalksClub/community-base --quiet`
  -> package test, plan and both P16 consumer jobs succeed; record package/site identities,
  raw baseline/linked counts and documented normalized failure-set comparison.
- Not run here, needs: authorized donor inventory, PostgreSQL development-copy rehearsal,
  Phase 5B identity/reverse/quiescence contracts, site policy/reader/writer/UI parity,
  adoption deployment and any applicable freeze. Wider URL storage proves none of these.

Done when
- [ ] Valid 200/201/500-character links round-trip unchanged through model and form.
- [ ] 501-character links fail by length; existing validation/access/lifecycle rules remain.
- [ ] One capacity owner and one append-only migration; no visible layout/control change.
- [ ] Package gates and safe fixture migration checks pass with rollback limits recorded.
- [ ] Both P16 consumer CI verdicts pass on the submitted head; PR merged before STATUS done.
- [ ] Later immutable release and site adoption remain separately coordinated.

Docs
- `community_base/coursework/README.md`, `CHANGELOG.md`, `docs/plan/phase-5.md` and
  `docs/plan/STATUS.md`; PR records baseline/sensitivity/final gates and deferred checks.

## C5.2r Add shared course enrollment history

Repository: community-base. Depends on: C5.1e. Freeze required: no.
Related: A5.1.

Goal: add a distinct shared `CourseEnrollment` owner for a learner's course-level enrollment
signal and soft history. Keep the existing cohort `Enrollment` model, services, database contract,
reverse relations, coursework foreign keys, APIs and Studio behavior unchanged. Ship model and
Python service capability only: no UI, template, route, HTTP API, Studio registration, importer,
site side effect, credential API, cohort creation or consumer data copy.

Read first
- Protected `coding-standard.md` as the style authority, read-only.
- `docs/01-decisions.md` D2, D8, D17, D18 and D29; none mandates one physical enrollment table.
- `docs/02-architecture.md` section 3 and this issue's accepted model-list update.
- `docs/04-quality-gates.md`, especially migration gates, nonempty checks and package consumer
  verification.
- `community_base/curriculum/models.py` `Course`, `Enrollment`, `ENROLLMENT_SOURCES` and the active
  cohort-enrollment constraint.
- `community_base/curriculum/services.py` enrollment helpers and their unauthenticated/idempotent
  behavior.
- `community_base/coursework/models.py` enrollment foreign keys; they remain typed to cohort
  `Enrollment`.
- AISL `content/models/enrollment.py` at the accepted donor commit for the field and history
  contract. This issue uses synthetic fixtures and does not copy donor data.
- The accepted storage-design evidence. Cohort eligibility and credential allocation are later
  adoption questions, not prerequisites for this fresh capability.

Design
- Add `CourseEnrollment` in `community_base.curriculum`; do not rename or alter `Enrollment`.
- Pin the donor field contract exactly:
  - implicit `BigAutoField` primary key under `CurriculumConfig.default_auto_field`;
  - non-null `user` FK to `settings.AUTH_USER_MODEL`, `on_delete=CASCADE`;
  - non-null `course` FK to `Course`, `on_delete=CASCADE`;
  - `enrolled_at = DateTimeField(auto_now_add=True)` with no nullable/default/index override;
  - `unenrolled_at = DateTimeField(null=True, blank=True)` with no default or explicit index;
  - `source = CharField(max_length=20, default="manual")`, non-null and non-blank, using the exact
    stored/display choices `manual` / `Manual`, `auto_progress` / `Auto (first lesson complete)`,
    and `admin` / `Admin (Studio)` from the existing package constants;
  - no extra donor field or generic policy metadata.
- Use distinct reverse names: `user.curriculum_course_enrollments` and
  `course.course_enrollments`. Keep `user.curriculum_enrollments` and `cohort.enrollments`
  unchanged for cohort membership.
- Order newest first by `enrolled_at`. Add an active-only unique constraint for `(user, course)`
  where `unenrolled_at IS NULL`; proposed constraint name `cb_course_enroll_active_uq`.
  The two foreign keys retain Django's normal FK indexes; add no speculative index beyond the
  partial unique index supplied by the constraint.
- Preserve donor display behavior: `__str__` returns
  `<user> -> <course.title> (active|unenrolled)`, and `is_active` is true exactly when
  `unenrolled_at` is null. Choice display text is part of the tested contract.
- Preserve the two model types and PK namespaces. A cohort `Enrollment(pk=N)` and a
  `CourseEnrollment(pk=N)` may coexist. Coursework, leaderboard state and shared `Certificate`
  continue to reference only cohort `Enrollment`.
- Add only explicit Python lookups/mutations in `curriculum.services`:
  `get_active_course_enrollment`, `is_course_enrolled`, `ensure_course_enrollment`,
  `unenroll_from_course`, `course_enrollment_history`, and
  `active_course_enrollment_count`.
- Use these concrete contracts:
  - `get_active_course_enrollment(user, course) -> CourseEnrollment | None`;
  - `is_course_enrolled(user, course) -> bool`;
  - `ensure_course_enrollment(user, course, source=SOURCE_MANUAL) -> tuple[CourseEnrollment | None, bool]`;
  - `unenroll_from_course(user, course) -> bool`;
  - `course_enrollment_history(user, *, course=None) -> QuerySet[CourseEnrollment]`, returning
    all active and inactive rows for the user, optionally narrowed to one course, in model order;
  - `active_course_enrollment_count(course) -> int`.
  Unauthenticated user lookups return `None`, `False` or an empty queryset consistently with the
  existing cohort helpers; count takes a course and does not inspect a user.
- `ensure_course_enrollment` returns `(row, created)`, does not refresh `enrolled_at` or overwrite
  the first source, and creates a new row after an earlier row was unenrolled.
  `unenroll_from_course` soft-closes only the active course row and is false/idempotent when none
  exists. These services never call or change cohort enrollment helpers or rows and emit no CRM,
  analytics, tags, notification, access or other site side effects.
- Do not add an HTTP endpoint, public/staff serializer, Studio destination, admin action,
  template, parser/import hook, certificate relation or synthetic self-paced cohort.
- Follow the coding standard: new functions at most 30 lines and new source/test files at most
  300 lines. Use cohesive focused modules rather than growing the existing oversized model file;
  preserve current model exports and source constants without a broad model rewrite. Record
  runtime lines added, moved and deleted separately from tests and migrations. This package
  capability alone does not establish net simplification or authorize deleting site code.

Steps
1. Add focused model/service lifecycle contract tests first. In the first idempotence or re-enrol
   history test, import the existing curriculum modules and resolve the named model/service
   attributes inside the test body with an explicit capability assertion. The exact parent source
   must collect and run a nonzero test before failing that assertion; after implementation the same
   test continues to its lifecycle assertions. Record that red result. A collection error, zero-test
   run or unrelated setup failure is not red proof. Do not add or retain a standalone presence-only
   test.
2. Add `CourseEnrollment` with the exact fields, source choice values/display labels, reverse
   names, ordering, string display and active partial uniqueness above. Reuse the existing source
   constants without changing cohort `Enrollment`.
3. Add the six explicit service functions above. Keep their queries model-specific; no generic
   “enrollment of either type” resolver and no implicit cohort selection. Leave every existing
   cohort service body and signature untouched.
4. Generate one new additive curriculum migration from the actual migration leaf. The migration
   number and filename are deliberately unreserved until implementation. Do not edit, replace,
   squash or renumber an existing migration; do not alter the existing `Enrollment` table,
   constraints or foreign keys.
5. Add a migration regression fixture that starts at the previous package migration state with an
   existing cohort Enrollment and at least one coursework row referencing it. Migrate forward and
   prove every existing PK, value and FK is unchanged. Reverse while the new table is empty, prove
   only the new table disappears, then migrate forward again. This is synthetic package evidence,
   not P14 or a populated consumer rehearsal. The empty-table reverse proves schema migration
   mechanics only. Once a consumer populates `CourseEnrollment`, application rollback retains the
   applied migration/table, back-copies under A5.1's rehearsed contract and switches the old app
   reader/writer back; it must not drop populated course history by unapplying this migration.
6. Document `CourseEnrollment`, its history semantics, reverse names and service functions in
   `community_base/curriculum/README.md`. State that cohort `Enrollment` remains the coursework and
   certificate type and that sites own public presentation and side effects.
7. Search the package for `Enrollment` foreign keys and public registration. Prove none were
   repointed and that the new model/service is not registered as an API or Studio surface.

Verification
- Red proof before implementation: the first lifecycle contract test runs against the exact parent
  source and fails its explicit capability assertion after the test module collects. After
  implementation, the same test continues to idempotence or re-enrol history assertions. Record the
  command and failure in the pull request; do not use a standalone presence-only test.
- `uv run pytest tests/curriculum` -> pass, including:
  - active uniqueness rejects a second active course row;
  - soft-close followed by ensure creates a second history row and retains the first row's source,
    timestamps and identity;
  - idempotent ensure preserves source and `enrolled_at`;
  - history is user/course scoped and newest first; active count ignores inactive history;
  - source max length, null/default semantics and all three stored/display choice pairs match the
    donor contract; `__str__` and `is_active` preserve its display/state behavior;
  - the same integer PK can exist once in cohort `Enrollment` and once in `CourseEnrollment`;
  - unauthenticated lookup/ensure behavior matches the documented service contract;
  - course ensure/unenrol leaves a same-user/course cohort Enrollment byte-for-byte unchanged and
    invokes no cohort mutation; the existing cohort model, reverse names and service signatures
    retain their current behavior.
- A focused relation test asserts that `Submission`, `ProjectSubmission`,
  `LeaderboardComplaint` and shared `Certificate` still target cohort `Enrollment`; no field can
  accept `CourseEnrollment` as its related model.
- `uv run python testproject/manage.py makemigrations --check --dry-run` -> no changes.
- Fresh migration gate:
  `DATABASE_URL=sqlite:////tmp/cb-c52r.sqlite3 uv run python testproject/manage.py migrate`
  -> all migrations apply from zero. First use a bounded `uv run python` reset of that exact
  task file, refusing symlinks and non-files; no other database is reset.
- Migration regression: previous curriculum leaf -> new leaf -> previous leaf -> new leaf passes
  while the new table is empty,
  with the synthetic existing cohort and coursework identities and values equal at every
  applicable checkpoint. Use the generated migration names recorded by implementation; this draft
  reserves no number.
- `uv run python testproject/manage.py check` -> no issues.
- `uv run pytest tests/test_boundaries.py` -> pass; no site imports.
- Standard package lint/format gates pass after `uv sync --all-extras`; report the collected test
  count against a baseline from the same checkout.
- P16's DTC and AISL jobs each compare the consumer's pinned baseline with the in-progress package
  and report no new failure. The designated on-call engineer observes those jobs. This issue does
  not query CI during planning and does not substitute a package fixture for either consumer.

Done when
- [ ] `CourseEnrollment` owns only course-level enrollment history with one active row per
      `(user, course)` and distinct reverse/PK namespaces.
- [ ] The six model-specific Python services pass their idempotence, history, source and timestamp
      contracts.
- [ ] Existing cohort `Enrollment`, coursework/certificate FKs, public APIs and Studio
      registrations are structurally and behaviorally unchanged.
- [ ] The new migration is additive, fresh-applicable, reversible while empty and drift-free; the
      previous-state regression preserves synthetic existing cohort and coursework rows exactly.
- [ ] The issue and migration documentation distinguish empty-schema reversal from later
      application rollback, which retains a populated extra table until back-copy and rollback
      acceptance permit retirement.
- [ ] Package, boundary and both P16 consumer gates pass with nonempty evidence.
- [ ] No site copy, side effect, UI, credential, eligibility or cutover behavior is claimed.

Docs
- `community_base/curriculum/README.md`.
- `docs/02-architecture.md` model list, if the accepted plan-preparation change has not already
  landed it.

## C5.3 Release 0.6.0

Repository: community-base. Depends on: C3.7, C4.3, C5.2e, C5.1e, C5.2h. Playbook P15.

This is the single adoption-ready domain release. Do not publish provisional `v0.4.0` or
`v0.5.0` releases containing kept-label migrations.

## C5.4 Repository-derived curriculum hierarchy and YAML-backed homework units

Repository: community-base. Depends on: C5.1e, C5.2i, C7.10, C7.11, C5.4a, C5.4b, C5.4c. Related issue:
DataTalksClub/community-base#306.

Goal: the physical course repository defines the shared curriculum tree. `module.yaml` folders
are modules; `homework.yaml` plus `homework.md` folders are structured homework units. A module
may contain direct units and child module folders together. The graph, importer and projection
preserve their single shared sibling order. Stable IDs remain source data; no generated projection
is checked in.

Implementation is split: C5.4a preserves unit identities across module moves, C5.4b preserves
module identities across reparenting, and C5.4c imports YAML homework through explicit cohort
bindings. The remaining mixed hierarchy, ordering, project-reference validation and projection
work stays here. Completing those prerequisites does not complete C5.4 or site adoption.
The existing draft PR #311 remains reference material; its route and markup changes do not belong
to the owner's current no-visible-UI-change simplification work.

Mixed authored siblings require a complete, unique order. Nullable internal
`source_sibling_position` fields on Module and Unit preserve that order separately from public
`sort_order` and cohort placements. Pure legacy siblings retain their existing sort and tie
behavior. Importing site rows without authored source ordinals leaves the new fields null;
replaying those imports preserves existing target metadata. DTC compatibility issue #445 verifies
that contract against a concrete package candidate before this issue's final consumer comparison.

One prefetched traversal owns syllabus, breadcrumbs, reading order, continuation and projection.
Existing flat output, routes and API identities stay unchanged. Cohort placements continue to
curate syllabus output; they do not become a new access restriction on course reader links.
Reader navigation and continuation retain the complete course tree while using the selected
cohort for homework and drip behavior. Generic nested destinations must resolve repeated child
slugs by ancestry without shadowing independently mounted coursework routes. Site routes,
templates and visible behavior remain governed by their later adoption work.
A registered host reader supplies per-project source-relative module references; the shared
resolver validates them before writes in both sync and `check_content --kinds`. Project schema
and storage remain host-owned; no course-level project pointer or implicit extra-field parsing
is introduced.

Steps
1. Implement the generic source convention, schema validation and graph/importer behavior in
   `community_base.content_sync` and `community_base.curriculum`; do not add a site-specific
   path/title exception.
2. Preserve YAML unit identity, ordered question IDs and structured homework fields while the
   Markdown companion remains prose. Keep cohort-scoped homework bindings separate. Accept
   existing authored `correct: 'N'` values only in the course-tree homework unit schema, validate
   and import them losslessly to the existing scoring field, and exclude them from learner-facing
   projections. The distinct cohort-manifest envelope-only rule stays intact. Source answer
   sealing follows when a shared AISL keyring is provisioned.
3. Carry `is_bonus`, authored syllabus-section labels and source-relative project-module
   references through the shared graph and projection. Reject ambiguous IDs/orders and unresolved
   references before import; accept valid mixed unit/module siblings.
4. Update the format and curriculum docs. Release the package change only after package and both
   consumer test gates are reported separately.

Verification
- Package curriculum/content-sync tests, quality gates, migration check and boundary tests pass.
- A fixture with interleaved direct units, homework and child modules renders in the exact source
  order; moving a YAML homework unit while retaining `content_id` updates the existing identity.
- AISL and DTC tests against the package revision are run and reported independently.

## C5.4a Preserve unit identity across module moves

Repository: community-base. Depends on: C5.1e, C5.2i, C7.10, C7.11. Related issue:
DataTalksClub/community-base#335.

Goal: moving a unit between modules of the same course retains its database identity and learner
links through the existing importer. No graph constructor, parser interface, public route,
template, API, model or migration changes belong to this split.

Read first
- `community_base/curriculum/importing.py`, `source.py`, `models.py` and `README.md`.
- `community_base/content_sync/provenance.py`, `FORMAT.md` sections 3.3/3.4 and `documents.py`.
- `tests/curriculum/test_import.py` and `tests/curriculum/utils.py`.
- Existing UnitProgress and coursework Homework/Submission/Answer relationships; read only.
- Issue #335 for the bounded contracts and existing discrepancies; PR #311 as reference only.

Steps
1. Demonstrate current move-related identity loss with valid leaf-module fixtures. Preserve
   existing unchanged imports, true deletion, missing-ID and module-plus-slug fallback behavior.
2. Resolve unit IDs within the current course and reject ambiguous matches there. The documented
   UUID namespace is repository-wide: independent courses/repositories may reuse a UUID.
3. Compare and write the destination `module_id` through the existing writer, retaining the
   original instance's parent until comparison. Preserve stored slugs and global writer semantics.
4. Upsert every unit before course-wide stale-unit cleanup, then perform existing stale-module
   cleanup. Cover both traversal directions and a source module that disappears entirely.
5. Reject incoming duplicate IDs, conflicting final destination claims and retained/unmanaged
   destination collisions before the first import-run/domain write. Preserve valid same-slug
   swaps/cycles and replacement of truly stale source-managed occupants. Reserve known identities
   before fallback so a new unit filling a moved unit's old slot cannot steal the moving row;
   otherwise preserve the existing slug fallback when no identity matches. Any temporary slug
   parking stays inside the transaction, emits no intermediate save signals and is fully restored
   or rolled back.
6. Extract cohesive importer responsibilities where required by coding standards. Update this
   plan and the curriculum README; keep the remaining C5.4 and donor-adoption work unfinished.

Verification
- Focused regressions fail on the old importer and pass after the fix; moves retain Unit,
  UnitProgress, Homework.unit, submission and answer identities/values and reimport is idempotent.
- Invalid/ambiguous inputs leave import-run and domain rows unchanged; independent-course UUID
  reuse, repeated sibling slugs, legacy fallback and true stale deletion remain supported.
- Same-slug swaps/cycles, replacing stale destination rows and filling a moved unit's old slot
  preserve the final identities. No temporary parked value survives success or rollback.
- Curriculum/content-sync tests, full package suite, lint/format, system checks, migration drift,
  fresh migrations, boundary checks and `uv run python scripts/plan.py check` pass.
- Both consumer gates run and are reported independently with captured source revisions and
  qualified raw/normalized results. No site adoption or deployed data preservation is claimed.

Done when
- [ ] The bounded move and compatibility contracts above have authoritative regression evidence.
- [ ] Code/docs are merged and package plus both consumer gates pass.

Existing limits: package UnitProgress is not AISL UserCourseProgress. Deleting an authored module
still nulls its independent Homework.module reference; unit-bound learner links must survive.
Whole-module reparenting is separate. FORMAT's changed-ID/new-row description differs from the
existing same-module slug fallback; this split preserves current behavior and records that
discrepancy rather than changing it implicitly. No release version or site pin changes here.

Docs: `community_base/curriculum/README.md`, `docs/plan/phase-5.md`, `docs/plan/STATUS.md`.

## C5.4b Preserve module identity during reparenting

Repository: community-base. Depends on: C5.1e, C5.2i, C7.10, C7.11. Related issue:
DataTalksClub/community-base#338.

Goal: authored module moves persist the new parent without replacing the module or losing its
units and learner links when the old parent disappears. Preserve visible UI, the existing
two-level source format, stored slugs, public interfaces and cohort placement policy.

Read first
- `community_base/curriculum/importing.py`, `models.py` and `README.md`.
- Existing curriculum import tests and coursework learner-record relationships; read only.
- Issue #338 and the separate unit-move change in PR #336. Module and unit moves have independent
  persistence defects; compute their importer composition with P18 and preserve both test suites.

Steps
1. Reproduce unchanged-content module reparenting and old-parent cascade loss on valid existing
   graphs, in both traversal directions.
2. Compare and write the desired `parent_id` through the existing writer before changing the
   loaded instance's parent. Keep course-scoped source identity and parent-plus-slug fallback.
3. Preserve valid child/top-level promotion and demotion. Complete module upserts before stale
   module deletion, without changing unit ownership, cohort placement or exception policy.
4. Keep the importer and existing oversized functions no larger. Add focused regression evidence
   and document the bounded guarantee; keep mixed hierarchy/YAML/ordering work in C5.4.

Verification
- Original-importer regressions fail at the missing parent write or lost persisted rows; the
  candidate retains module, unit, progress, homework, question, submission and answer identities.
- Parent changes count as updated once and reimport is unchanged. Ordinary fallback, independent
  course identities and cohort placements remain supported; constraint failures remain atomic.
- Curriculum/content-sync and full all-extras package suites, lint/format, checks, migration drift,
  fresh migrations, boundaries and `uv run python scripts/plan.py check` pass.
- Both consumer gates are reported with captured revisions and raw/normalized qualifications.

Done when
- [ ] The bounded module-move contracts have red-before/green-after evidence.
- [ ] Code/docs are merged and package plus both consumer gates pass.

This is preservation capability, not a net-deletion claim. No model, schema, graph constructor,
route, template, projection, site pin or release version changes belong here. Real AISL donor
preservation remains a later adoption rehearsal.

Docs: `community_base/curriculum/README.md`, `docs/plan/phase-5.md`, `docs/plan/STATUS.md`.

## C5.4c Import course-tree YAML homework through explicit cohort bindings

Repository: community-base. Depends on: C5.4a, C5.4b. Related issue:
DataTalksClub/community-base#341.

Goal: a course-tree `homework.yaml` and exactly one `homework.md` companion define a stable
homework unit. Explicit cohort bindings materialize its structured metadata into the existing
cohort-owned assignments and questions without replacing learner records or changing existing
visible UI. The separate cohort-manifest schema stays envelope-only.

Read first
- Issue #341 for the complete source, binding, preservation and verification contract.
- `content_sync/kinds/course.py`, `kinds/layouts.py` and `content_sync/FORMAT.md`.
- `curriculum/source.py`, `parsers.py`, `content_sync_parsers.py` and `importing.py`.
- `coursework/manifests.py`, `importing.py`, `models.py`, `answer_resolution.py`,
  `submissions.py` and `homework_reveal.py`.
- `homework_steps/types.py`, `coursework.py` and existing homework rendering tests.

Steps
1. Define the distinct course-tree source schema and explicit unit-identity cohort binding.
   Preserve legacy bindings; reject ambiguous source ownership, invalid companions, identities,
   questions and answers before writes. Do not infer an assignment for an unbound source unit.
2. Preserve Unit, Homework, Question, Submission, Answer and progress identities on source moves.
   Keep source metadata separate from cohort-specific policy and operator-managed assignment state.
   Persist authored question order additively while preserving legacy order for existing rows.
3. Validate both source forms first, then apply curriculum and coursework inside one transaction.
   Use one combined retained-assignment set so cleanup cannot delete the other source form's rows.
4. Import authored `correct: 'N'` losslessly only through the new source schema. Keep source answers
   out of ordinary learner projections and reuse safe question descriptors. Preserve existing
   policy-controlled scored-result reveal; removing it would violate the owner's feature constraint.
5. Reuse domain owners, preserve existing page markup, and update source-format and app docs.
   Keep mixed hierarchy, combined module/unit order and destinations in C5.4. This split must not
   enable mixed sources that the current projections cannot present.

Verification
- Flat Markdown/YAML fixtures, explicit multiple-cohort bindings and unbound-source behavior pass.
- Source moves and question reordering retain learner records and stable primary keys; repeated
  imports are idempotent. Invalid source forms leave all curriculum and coursework rows unchanged.
- Plaintext course-tree and envelope-only cohort scoring both work. Ordinary HTML/API/projections
  exclude source answers, authorized reveal remains available, and legacy rendered output is stable.
- Package quality gates, touched apps, all-extras suite, boundaries, plan check and applicable
  additive-migration checks pass. Both consumer comparisons report captured refs and raw/normalized
  outcomes independently. Donor rehearsals and site adoption remain separate, unverified milestones.

Done when
- [ ] The complete scoped contract has behavior evidence and independent review.
- [ ] Code/docs are merged and package plus both consumer gates pass.
- [ ] C5.4's remaining mixed-tree/projection requirements and site adoption remain open.

Docs: `content_sync/FORMAT.md`, curriculum/coursework READMEs, `docs/plan/phase-5.md`,
`docs/plan/STATUS.md`.

## A5.3 Future AISL repository hierarchy and URL rollout

Repository: AI-Shipping-Labs/website. Depends on: C5.4, A5.2. Related issue:
AI-Shipping-Labs/website#1830.

This complete visible-product change is blocked under the owner's current instruction to preserve
visible UI and features. It requires a future explicit request for hierarchy and route/redirect
changes, plus accepted source placements from #1675/#1775. It is not a prerequisite for A5.1/A5.2
backend convergence. A7.2b parser adoption, a canonical internal graph or a compatibility adapter
does not complete any visible acceptance criterion here. Retain the complete #1830 scope below
for that future rollout.

Remove the local course-inline flattening and course-specific hierarchy branches. Use the package
parser and projection, retain site-owned policy, and coordinate the 32 first-level Buildcamp source
placements with #1675. Preserve current first-level canonical URLs where source slugs permit;
remove obsolete nested-path behavior except the `/c/<uuid>` share link. Moved units retain their
source IDs and existing homework, submission, draft, scoring and progress records. Migrate
`correct` answer indices losslessly through the import boundary to the existing scoring field;
public projections do not expose correctness. Remove former nested-path redirects except
`/c/<uuid>` share links. Preserve authored
syllabus-section metadata, `is_bonus`, event identity and generic project-to-module association.
The detailed migration inventory and acceptance criteria are in #1830.

Verification
- Synthetic mixed-tree and moved-unit tests pass; `make test-affected` passes against C5.4.
- Package, AISL and DTC checks are reported separately.

## D5.3 DTC: adopt repository-derived course hierarchy and homework units

Repository: DataTalksClub/website. Depends on: D5.3a, D5.3b, D7.3. Related issue:
DataTalksClub/website#436.

Use the package parser and projection for nested directories and structured homework units. Keep
only DTC-owned cohort placement/binding, access and route adapters; re-scope #398/#399 to avoid a
second generic parser or projection. Preserve project references, course features, site-owned
presentation, API shapes and the existing route compatibility contract. The detailed migration
and acceptance criteria are in #436.

This remains the full adoption acceptance milestone. D5.3a proves the source/policy contract;
D5.1 adopts storage and activates the single shared-parser-backed source writer; D7.3 completes
six-source registration/proof and generic reader retirement; D5.3b integrates site projection. Account for every original #436 criterion with their linked evidence and a
green selected development deploy. Source-contract completion alone does not finish D5.3.
Approved scratch/branch sources can prove development acceptance; live authored conversion and
source-ref cutover remain D7.4, with its existing freeze and human-review requirements.

### DTC development data boundary (D5.3, D5.1 and D5.2)

The [owner permits rebuilding DTC data](https://github.com/DataTalksClub/website/issues/438#issuecomment-5890507372)
while requiring AISL data preservation. Before implementation, name the exact target and choose
fresh or in-place adoption. The fresh exception here applies only to an explicitly authorized
disposable DTC development logical database; #440's immediate target is `dtc_website_dev`.
It does not authorize a production, AISL, Relay or shared RDS reset.

Fresh adoption establishes new rows from stable authored identities. Subsequent syncs and source
directory moves must preserve those rows and their newly created learner links. Historical
database IDs and rows from the discarded development schema need not survive. Report their
preservation checks as `Not applicable: authorized fresh DTC development target`, never as passed.
In-place adoption retains the original lossless migration and development-copy rehearsal gates.
Both modes retain every feature, route, API and visible interaction. AISL donor compatibility,
package release requirements and all issue dependencies remain unchanged.

Verification
- Flat and mixed-tree fixtures import and render with package order; homework bindings and learner
  records remain attached.
- Fresh mode: repeated import creates no duplicate source identities; moves with unchanged
  `content_id` retain rows and synthetic submissions, answers, progress, reviews and certificates
  created after import. In-place mode: preserve the existing rows and identities through cutover.
- The route-contract test and affected DTC tests pass; package, AISL and DTC checks are reported
  separately.

## D5.3a Prove the DTC source and policy contract for shared curriculum

Repository: DataTalksClub/website. Depends on: C5.4, C7.12b, C7.12d. Freeze required: no. Related issue:
DataTalksClub/website#446.

Goal: establish executable source and DTC policy expectations against a tagged shared package,
without adopting package storage, changing production readers or converting a live repository.

Read first
- DTC AGENTS/process/spec 04 and current source-format specs.
- #436, #414, `courses/services/curriculum_source.py`, existing source fixtures and route contract.
- Package FORMAT, public course parser, converter and #347 semantic regression evidence.
- `courses/views/shared_course.py`, `curriculum_flow.py`, `course_context.py` and the existing
  mapping document; read the affected contracts, do not reopen a broad inventory.

Steps
1. Inventory the exact public source commits and accepted source shapes for the six repositories,
   plus target-required content absent from them. Record dispositions as decisions still owned by
   D5.1; do not assume a source-only import recreates the public catalog.
2. Add bounded executable fixtures consuming public tagged converter/parser APIs. Establish
   expected source IDs, order, parentage, homework schemas/bindings, section/bonus metadata,
   project references, explicit ignores and route identities from source data.
3. Compare supported legacy flat source expectations with converted graphs; include the newly
   supported mixed/YAML-homework shapes as synthetic contracts. Preserve module boundaries.
4. Record DTC policy mappings separately from generic structure: publication, archive behavior,
   cohort context, homework/project flow, module-local neighbors, access, asset links and URLs.
   Unsupported nonempty cohort `flow` must be refused without mutation by tagged C7.12d;
   source-contract acceptance requires executable refusal evidence and an explicit D5.1 blocker.
   D5.1 still needs a host-owned source/import/projection contract preserving project identity
   and interleaved module/project order before shared writer or storage activation.
5. Name unresolved metadata/storage/behavior gaps explicitly; each required field/feature needs
   a known target owner before this milestone can be accepted. Do not introduce a runtime shim
   or duplicate parser to make the contract look complete.

Acceptance criteria
- [ ] Exact tagged package and source/fixture identities are recorded. No branch/path dependency
      is committed and DTC source guards pass.
- [ ] Flat and mixed source fixtures produce the expected authored identities/parentage/order;
      YAML homework/questions and explicit cohort bindings survive conversion without loss.
- [ ] Course source conversion is idempotent and obeys the accepted #347 partial-refusal policy.
- [ ] Explicit expected DTC canonical slugs/routes and module-local navigation are recorded;
      package default prefix stripping or whole-course neighbors cannot silently replace them.
- [ ] The required public-content inventory and field/policy owner matrix are reviewable. Missing
      import paths/owners are unresolved blockers, not omissions from the contract.
- [ ] Required DTC verification passes; no production reader, schema, database, template or UI
      changes. This is source-contract proof, not imported-data/render/deployment equivalence.

Verification
- Run the selected source-contract and route-baseline tests through the maintained DTC test
  runner and all components selected by its verification plan; record exact counts and source
  identities. Validate converter output with the tagged package parser, not a copied parser.
- Complete independent QA and PM review under the DTC process. Package capability evidence is
  linked separately; imported site rows and deployed reader parity remain D5.1/D5.3b work.

Docs: DTC source-contract/mapping documentation and this plan's STATUS row. Test additions use
existing bounded fixture owners; no new general parser or generated production content files.

## D5.3b Adopt shared curriculum projection behind DTC reader contracts

Repository: DataTalksClub/website. Depends on: D5.1, D7.3. Freeze required: no. Related issue:
DataTalksClub/website#447.

Goal: consume the package curriculum tree/projection behind existing DTC routes and templates,
with the site policy contract proved by D5.3a and package rows imported through D7.3.

Read first
- DTC AGENTS, process, spec 04, course route contracts and D5.3a's accepted policy matrix.
- D5.1 target-model evidence, D7.3 ingest/caller inventory, shared CourseTree/projection APIs.
- Current shared_course, curriculum_flow and course_context callers and their existing tests.

Steps and acceptance criteria
- [ ] Use CourseTree/shared projection for generic hierarchy and ordered traversal; remove the
      replaced site projection bodies after full caller inventory. Keep DTC URL/policy mapping.
- [ ] Existing flat public HTML and API shapes, canonical/compatibility routes, query context,
      access and publication/retirement filtering, empty/error behavior and Studio remain equal.
- [ ] Previous/next remains within published lessons of the current module where that is today's
      contract. Do not substitute the package's whole-course neighbor policy.
- [ ] Flat, nested, mixed and one-unit module fixtures resolve to real supported destinations;
      preserve section/bonus metadata, project references and explicit homework bindings.
- [ ] Repeated sync and moves preserve selected-mode data/link guarantees through actual site
      callers. Use D5.1 data evidence, adding the reader-specific checks rather than claiming a
      second independent full migration.
- [ ] Independent QA verifies route/API semantics and desktop/mobile presentation on the selected
      development target with synthetic learners. Current visible UI is unchanged. If exposing
      new hierarchy cannot fit that contract, record the concrete product decision before edits.
- [ ] Package/site evidence and deployment verdicts are recorded separately; no adoption claim
      rests only on generic package template tests or generated links that were never resolved.

Verification
- Run the maintained DTC verification plan, including affected reader/API/route/Studio tests
  and desktop/mobile evidence; resolve generated destinations through real site views.
- Check representative flat before/after HTML/API contracts, module-local neighbors and
  query counts. Prove nested/mixed and one-unit destinations with approved source fixtures.
- Record independent QA/PM acceptance and green selected development deployment. Scratch-source
  evidence does not complete D7.4 or authorize a live-source switch.

Docs: DTC course/spec/route-policy documentation; STATUS here. No generic package templates or
route mounting replaces DTC presentation. No source conversion or parser duplication.

## D5.3c Preserve ordered cohort module/project flow in converted source

Repository: DataTalksClub/website. Depends on: C5.4, C7.12d. Freeze required: no.

Goal: preserve DTC's authored cohort module/project order through a source-only conversion
contract. A pure typed reader validates `extra.dtc_flow`, and a deterministic DTC pre-pass
normalizes the existing schema-1 fixture in a disposable destination before the package converter
runs. No database, runtime parser, source registration, package pin, route, template or UI changes.

Read first
- DTC AGENTS/process, specifications 01 and 04, coding standard and verification-plan contract.
- `content_sync/course_repository.py`, `courses/services/curriculum_source.py`, the maintained
  `llm_zoomcamp_2026` fixture and the exact existing source IDs.
- Package FORMAT `extra` and cohort rules, the public converter/parser APIs and C7.12d's immutable
  v0.5.21 refusal proof.
- The DTC course-platform mapping, current cohort flow model/importer and project route identity.

Steps
1. Record the actual RED against immutable v0.5.21: direct generic conversion refuses the
   fixture's nonempty flow under rule 3.8 and leaves that cohort scope unchanged. Keep that default.
2. Add a pure, frozen DTC `extra.dtc_flow` state over already parsed package values. Validate exact
   version/item shapes, cohort/module identities, complete module coverage and relative order,
   unique cohort-scoped project slugs and bounded code/path/pointer errors. Parse no YAML twice.
3. Build one complete normalization plan from the existing frozen schema-1 graph before effects.
   In a disposable destination only, move the module subtree and terminal homework to standard
   locations, preserve every stable ID and unrelated byte, write standard module/homework bindings
   plus the full mixed flow, and remove legacy `flow` only after collision and inventory checks.
4. Run the public v0.5.21 converter and parser over that destination. Prove the standard graph and
   DTC state reconstruct the original module/project sequence and a second complete run changes no
   path or digest. Never invent project metadata; current identity remains cohort plus project slug.
5. Keep committed pure tests green with DTC's tracked v0.5.10 dependency. Run the v0.5.21 proof in
   an isolated maintained link, record exact tag/source, then restore dependency files byte-for-byte.
6. Keep each new or materially changed handwritten source and test file at or below 300 lines and
   each new function at or below 30 lines, with no ternary or filtered/nested comprehension. Split
   the pure contract from normalization if the complete behavior cannot meet those limits; the
   pure half alone does not complete this issue or any adoption milestone.

Verification
- Focused source-contract and normalization tests use the unchanged maintained fixture, prove the
  exact IDs/order, bounded refusals, no-write failures, full path inventory and byte idempotence.
- Existing course-repository parser tests pass. Direct unpreprocessed conversion still refuses.
- `uv run --frozen python scripts/ci.py verification-plan`,
  `uv run --frozen python scripts/ci.py verification-run`,
  `uv run --frozen python scripts/ci.py verification-evidence-check` and
  `uv run --frozen python scripts/ci.py verification-report-check` pass with every component
  classified once. Backend-only screenshots and migration evidence are explicitly not applicable.
- An independent Tester recomputes the plan, reruns required components and exact v0.5.21 proof,
  verifies restored pin/lock bytes, then a separate Product Manager accepts under the DTC process.
- Not run here, needs: released C7.12g runtime integration, D5.1 data adoption, D5.3b projection,
  D7.3 runtime cutover, D7.4 live conversion, deployment and visible-route equivalence.

Done when
- [ ] The typed source contract preserves exact cohort/module/project identity and order.
- [ ] Disposable normalization preserves every stable ID and file disposition without metadata loss.
- [ ] The package converter/parser accepts the normalized output and repeat output is byte-identical.
- [ ] Tracked-pin and exact v0.5.21 evidence, DTC verification, Tester and PM gates pass.
- [ ] Runtime, data, deployment and live-source adoption remain explicitly open.

Docs: DTC course-platform shared-app mapping and `docs/plan/STATUS.md` here. No generated converted
fixture or second parser is checked in.

## A5.1 Map AISL courses to the shared apps

Repository: AI-Shipping-Labs/website. Depends on: C5.3, A7.2b, C5.2r.

Adopt shared curriculum/coursework storage and reusable services behind the current AISL policy,
routes and presentation. Preserve every current visible UI interaction and supported feature.
Public course templates remain site-owned under D18. A5.3's future hierarchy and URL rollout is
separate; this issue preserves current redirects and the existing reader projection.
Use an immutable tagged release containing every required curriculum/coursework API. C5.3's
C3.7/C4.3 donor gates remain required; an earlier capability release does not satisfy them.

Steps
1. Mapping document in the pull request: every field of `content.Course`, `Module`, `Unit`,
   `Cohort`, `CohortEnrollment`, `Enrollment`, `UserCourseProgress`, `CourseCertificate`,
   `ProjectSubmission`, `PeerReview` to its shared target.
2. Data migration (P6): copy every active and historical local course `Enrollment` row to
   shared `CourseEnrollment`, independently of cohort membership. Preserve course enrollment
   IDs, source and timestamps under the accepted target inventory and reversible mapping.
   Local `CohortEnrollment` rows map to the unchanged shared cohort `Enrollment` through the
   accepted cohort identities. Keep the existing no-cohort `self_paced` curriculum mapping;
   never select or invent a cohort merely to carry course-level enrollment history. Existing
   shared rows, target-only eligibility, certificate allocation and all donor parity/rehearsal
   gates remain this adoption issue's responsibility; the fresh package capability proves none
   of those populated-copy contracts.
3. `CourseAccess` and Stripe product creation stay in AISL; implement `COURSE_ACCESS_GRANTS`.
4. Workshops keep their own models and pages; `WorkshopInstructor` references `events.Host`.
5. Integrate the shared curriculum parser through the A7.2b source contract. Preserve active
   refresh for unconverted sources until A7.3; do not add a second converted parser or mirrored
   live writer. Identify every dispatcher, command, task and caller that must switch at cutover.
6. Repoint domain services and prepare thin route, reader-context, Studio and API adapters over
   shared storage. Keep public templates, styling and site-specific policy. Preserve enrollments,
   purchases, progress, homework drafts/submissions/answers/scoring, projects, reviews,
   leaderboards, certificate URLs and cohort/self-paced behavior. A missing shared capability is
   a blocker, not permission to remove a feature.
7. Rehearse the writer/reader switch and rollback on a sanctioned populated PostgreSQL development
   copy. Retain replaced backend code until the accepted cutover and A5.2a retirement gates.

Verification
- P14 rehearsal: counts of courses, modules, units, enrollments, progress rows and certificates
  equal before and after; `sync_content --from-disk` after the change reports zero changes.
- Record exact site commit, tagged package, source refs, donor migration inventory and identity-keyed
  before/after counts for all mapped course and learner-state tables. Repeat sync is idempotent;
  rollback/back-copy restores learner state and routes. Fresh/empty databases, fixtures and SQLite
  are capability evidence, not this populated-copy rehearsal. AISL data cannot be reset.
- Verify the same nonempty fixtures before/after for current Home, syllabus, module overview,
  reader, homework, project/review, leaderboard, certificate and Studio surfaces on desktop/mobile.
  Rendered hierarchy/order, navigation, redirects, APIs, permissions, gated content and supported
  actions remain equivalent, including cohort and self-paced states. Screenshots and meaningful
  behavior assertions prove parity; status codes and empty inventories do not.
- `make test-affected` -> pass.

## A5.2 Freeze weekend: AISL courses cutover

Repository: AI-Shipping-Labs/website. Depends on: A5.1, A7.3. Freeze required: yes. Playbook P13. Production checks: course catalog, one gated unit for a Basic member (allowed) and
a Free member (paywall), progress toggle persists, purchase flow grants access.

Switch to one authoritative shared-storage writer and reader using the rehearsed mapping and
rollback. Preserve source refresh, all current UI/routes/features and site policy. Record the
green development deployment and existing P13 owner-operated production checks; agents do not
access production data or credentials. Backend deletion is a separately verified A5.2a step.

## A5.2a Retire replaced AISL course backend

Repository: AI-Shipping-Labs/website. Depends on: A5.2. Freeze required: no.

Goal: delete replaced local course models, parsers, business services, commands, tasks and
compatibility code after shared-storage cutover is accepted, preserving every supported behavior.
Keep site-owned public templates, routes and policy adapters under D18 and D29.
The no-freeze scope is code retirement of responsibilities already cut over. It does not authorize
dropping tables, changing schema or ending the accepted rollback boundary. Any such change needs
its own rehearsed migration and applicable D11 freeze and owner-operated approval gates.

Read first
- AISL `AGENTS.md`, `_docs/PROCESS.md`, coding and testing standards.
- The accepted A5.1 mapping and A5.2 cutover, parity and rollback evidence.
- D11, D18 and D29; playbook P17 and the production cutover playbook.

Steps
1. Inventory each proposed deletion's complete responsibility and replacement owner. Run P17 over
   all Python import forms and alias attributes, tests, scripts and management commands. Also
   inspect dynamic registrations, queued dotted task names, settings, URLs and template references.
   An empty or incomplete inventory is not evidence of safe deletion.
2. Verify the replacement against the accepted populated-copy and rendered/access/navigation/API
   contracts. Confirm converted live sources parse/render once and continue to refresh under A7.3.
   Preserve legacy functionality still owned by other active families.
3. Delete only code with no remaining responsibility; move site-specific behavior to its explicit
   adapter where needed. Preserve the accepted rollback boundary and document retained code.
4. Repeat reference and behavior checks on the deletion candidate. Run the site's required review,
   affected tests and development deployment gates before completion.

Verification
- Independent Tester and PM verify feature/UI/data parity and the complete deletion inventory.
- `make test-affected` passes and the development deployment is green.
- Report runtime lines added, moved, deleted and net change across package and both sites,
  separately from tests and migrations. Adapter additions or code moved into the package are
  not net simplification. DTC adoption and retirement remain required by D5.1/D5.3/D7.3/D5.2.

Done when
- [ ] Replaced backend responsibilities have one authoritative owner and no remaining callers.
- [ ] Current visible UI, routes, features, learner state and source refresh remain equivalent.
- [ ] Independent review, affected tests and development deployment pass for the deletion.
- [ ] Actual runtime deletion and retained site-specific adapters are recorded.

Docs: AISL course mapping and this repository's `docs/plan/STATUS.md`.

## D5.1 Map DTC course platform data to the shared apps

Repository: DataTalksClub/website. Depends on: C5.3, D5.3a, D5.3c, C7.12g.

D5.3a supplies the verified source/policy contract. This issue owns storage adoption, field/data
mapping and repointing existing callers while preserving current flat routes and UI. Prove
nested/YAML-homework persistence and identity at the target-model boundary using shared APIs;
new nested reader projection acceptance is D5.3b and repository-reader retirement is D7.3.
Before shared storage or writer activation, prove the D5.3c ordered-flow contract through released
C7.12g APIs at the runtime persistence/projection boundary. Source-only normalization evidence
does not establish runtime parity. Each adoption uses an immutable tagged release containing all
required curriculum/coursework APIs; C5.3's donor and rehearsal gates remain required.
Activate one shared-parser-backed scheduled/webhook writer against accepted package storage on
the selected development target with approved compatible development source refs. Source updates
must keep working: no legacy jobs writing old/disconnected tables, mirrored writes or second
runtime parser. D7.3 completes six-source registration/proof and generic reader retirement;
D7.4 alone changes final live authored refs under its original freezes. C5.3, all donor gates
and the selected-mode data boundary remain unchanged.

Steps
1. Map every course, cohort, curriculum, enrollment, progress and coursework field and workflow
   to the shared apps, a DTC extension or approved source import. Keep `LearnerProfile` and
   DTC-owned cohort placement, access, registration, routes and presentation.
2. Fresh mode, within the D5.3 boundary: migrate empty PostgreSQL storage using tagged package
   releases and import approved public sources from all six DTC course repositories. Cover flat
   and nested/YAML homework, source/question identities, ordering, cohort dates and project
   references. Every course has a cohort; a course without a source-defined offering gets one
   persisted self-paced cohort with null start/end dates. Reimport creates no duplicates.
   Inventory public content missing from those repositories, including project prerequisites
   and historical offerings; source sync alone does not reproduce the complete public catalog.
   Define the intended fresh target's public content inventory and explicit dispositions for
   old-only content. Required target content and its references need an approved public source
   and compatible importer before adoption can finish; a missing import path for a supported
   feature is a blocker. Discarded historical rows need not be recreated merely to match counts.
3. Prove the target-model contract before using the separately controlled development public
   bootstrap. Its audited artifact imports public data only and its existing command is not
   assumed compatible with package storage. Use synthetic records for protected learner flows;
   do not populate a fresh target from protected CMP or production exports.
4. In-place mode: retain P6 mapping and P14 development-copy rehearsal, applying
   `course_family_catalog.py` where needed; preserve learner rows, scheduled cohort dates and
   certificate URLs, prove reversibility and equal before/after counts.
5. Re-point internal callers while preserving `_docs/compatibility/course-route-contracts.json`,
   APIs, permissions, redirects, Studio and visible behavior. Delete `courses`, `studio_courses`,
   `course_management`, `cadmin`, `review_import` and `compatibility` code only after a complete
   caller/command/task/route inventory proves each removed part has no live responsibility.

Verification
- Fresh mode: migrations and drift checks pass from zero; record safe public source/import
  counts against the defined target inventory, required public relationships, zero courses
  without cohorts, repeat-import and stable-identity evidence. Synthetic learner tests cannot
  substitute for required public source content or its import coverage.
- In-place mode: historical row, cohort-date and certificate-URL preservation, reversibility
  and count equality pass on the development copy.
- Both modes: enrollment, progress, homework save/submit/score/review, projects, peer review,
  leaderboard, registration, certificates and self-paced access pass with synthetic records.
  Route/API/Studio and rendered behavior match existing contracts. `uv run pytest -q` and the
  site's required verification gates pass, followed by a green development deployment.

## D5.2 Freeze weekend: DTC courses cutover and self-paced mode

Repository: DataTalksClub/website. Depends on: D5.1, D5.3. Freeze required: yes.

Use P13 and the site deployment process. Record the target/mode, code and package release,
public import provenance, recovery plan and freeze scope. Fresh development adoption does not
waive coordinated cutover or protection against concurrent content writes. Record any
inapplicable P13 step with its concrete reason; D7.4's source-authoring freezes remain separate.

On the deployed development site, verify cohort pages, registration/enrollment and denials,
homework save/submit/score/review, leaderboard, projects and peer review, certificate download,
progress and one self-paced Studio course with a persisted unit visible to a registered member.
Verify source order, repeat sync, routes, APIs, empty/error states and desktop/mobile presentation.
Use synthetic learner/operator records and verify imported public content separately; a healthy
empty-schema deployment does not prove course adoption.

Done when
- [ ] spec 04 updated: the package owns curriculum and coursework; DTC keeps `LearnerProfile`
  and its site-owned policies, routes and presentation, with all course features preserved.
- [ ] The selected D5.1 mode's evidence and applicable P13 steps are complete.
- [ ] Deployed workflow, source-resync and route/API/presentation checks pass at the recorded
  release and public import identities; no imported course lacks a cohort.
