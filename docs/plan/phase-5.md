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

## C5.3 Release 0.6.0

Repository: community-base. Depends on: C3.7, C4.3, C5.2e, C5.1e, C5.2h. Playbook P15.

This is the single adoption-ready domain release. Do not publish provisional `v0.4.0` or
`v0.5.0` releases containing kept-label migrations.

## A5.1 Map AISL courses to the shared apps

Repository: AI-Shipping-Labs/website. Depends on: C5.3.

Steps
1. Mapping document in the pull request: every field of `content.Course`, `Module`, `Unit`,
   `Cohort`, `CohortEnrollment`, `Enrollment`, `UserCourseProgress`, `CourseCertificate`,
   `ProjectSubmission`, `PeerReview` to its shared target.
2. Data migration (P6): courses with no cohort get one `self_paced` cohort; `Enrollment` rows
   attach to it; `CohortEnrollment` rows become `Enrollment` rows on their cohort.
3. `CourseAccess` and Stripe product creation stay in AISL; implement `COURSE_ACCESS_GRANTS`.
4. Workshops keep their own models and pages; `WorkshopInstructor` references `events.Host`.
5. Register the curriculum parser for the content repository; delete the local course dispatcher.
6. Delete local models, views, templates, Studio pages, API views for courses.

Verification
- P14 rehearsal: counts of courses, modules, units, enrollments, progress rows and certificates
  equal before and after; `sync_content --from-disk` after the change reports zero changes.
- `make test-affected` -> pass.

## A5.2 Freeze weekend: AISL courses cutover

Repository: AI-Shipping-Labs/website. Depends on: A5.1. Freeze required: yes. Playbook P13. Production checks: course catalog, one gated unit for a Basic member (allowed) and
a Free member (paywall), progress toggle persists, purchase flow grants access.

## D5.1 Map DTC course platform data to the shared apps

Repository: DataTalksClub/website. Depends on: C5.3.

Steps
1. Mapping document: `courses.Course`, `Cohort`, `Module`, `Unit`, `Enrollment`, `UnitReadState`
   and every coursework model to the shared apps; `LearnerProfile` stays.
2. Data migration (P6) rehearsed on the development copy; `course_family_catalog.py` mapping
   applied; certificates preserved with their urls.
3. Route compatibility: `courses/urls.py` patterns re-pointed at package views; the
   `_docs/compatibility/course-route-contracts.json` test must still pass; `cadmin` legacy
   redirects re-pointed.
4. Delete `courses`, `studio_courses`, `course_management`, `cadmin`, `review_import`,
   `compatibility` shells where empty.

Verification
- compatibility test passes; `uv run pytest -q` -> pass; counts equal.

## D5.2 Freeze weekend: DTC courses cutover and self-paced mode

Repository: DataTalksClub/website. Depends on: D5.1. Freeze required: yes. Playbook P13 on the development environment. Checks: cohort page, homework submission, leaderboard,
project peer review, certificate download, one self-paced course created in Studio with a unit
visible to a registered member.

Done when
- [ ] spec 04 updated: the package owns curriculum and coursework; DTC keeps `LearnerProfile`
  and route compatibility
