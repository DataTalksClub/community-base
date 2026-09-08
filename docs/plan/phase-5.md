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

## C5.2ea Coursework Studio: homework and submissions

Repository: community-base. Depends on: C5.2dc.

Split from C5.2e; the donor analysis lives in `docs/plan/evidence/c5.2e-donors.md` (step 1
sections "Cohort list and cohort admin", "Homework and question management", "Submissions and
rescoring").

Read first
- `~/git/dtc-website/studio_courses/views/homework.py`, `homework_submission_edit.py`,
  `homework_submission_list.py`, `studio_courses/services.py`,
  `studio_courses/deadline_extension.py`, `courses/homework_correct_answers.py`.

Steps
1. Studio section `coursework` registered from the app config, with the cohort list and the
   cohort admin page: homeworks annotated with submissions counts and action flags, support
   metrics over the cohort's enrollments and open complaints.
2. Homework actions: score, rescore (reset to OPEN, then the scoring service), deadline
   extension limited to open homework and the donor's 1/3/7-day options, save correct
   answers per question, fill correct answers from the most popular submission answer,
   clear correct answers.
3. Homework submissions list with search and pagination; submission edit that rewrites the
   answers and learning-in-public links, applies the FAQ-score override, rescores the
   submission and refreshes the leaderboard when the total changed.

Verification
- `uv run pytest tests/coursework` -> pass; a rescore resets, rescores and recomputes the
  leaderboard; correct-answer fill picks the most popular answer; deadline extension rejects
  closed homework and days outside the option set.
- `testproject`: the Studio homework flow scores and rescores on imported data, updating
  submission scores and leaderboard positions.

## C5.2eb Coursework Studio: projects, complaints, certificates and campaigns

Repository: community-base. Depends on: C5.2ea.

Split from C5.2e; the donor analysis lives in `docs/plan/evidence/c5.2e-donors.md` (step 1
sections "Projects, criteria and peer review administration", "Leaderboard recompute,
complaints, enrollments and certificates", "Registration campaigns").

Read first
- `~/git/dtc-website/studio_courses/views/projects.py`, `project_submission_edit.py`,
  `project_submission_list.py`, `enrollment.py`, `enrollment_edit.py`,
  `enrollment_complaints.py`, `campaigns.py`, `campaign_lifecycle.py`,
  `campaign_registration_list.py`.

Steps
1. Project actions: assign peer reviews, score, deadline extension by project state; project
   submissions list and the admin override edit that rewrites evaluation scores, pass flags
   and totals.
2. Leaderboard complaints page and resolve action; enrollment list, edit and
   learning-in-public toggle; certificate management over `coursework/certificates.py`;
   leaderboard recompute through the scoring and enrollment actions.
3. Registration campaign create/edit with the guarded lifecycle actions, plus the campaign
   registrations page with role, country and region breakdowns.

Verification
- `uv run pytest tests/coursework` -> pass; peer review administration (assign, submit,
  score, admin override), complaint resolution, certificate issue and the campaign
  lifecycle state machine behave as recorded.
- `testproject`: the coursework Studio flows cover homework rescoring, peer review
  administration and leaderboard recompute on imported data.

## C5.2ec Testimonial management and Wrapped statistics

Repository: community-base. Depends on: C5.2dc.

Split from C5.2e; the donor analysis lives in `docs/plan/evidence/c5.2e-donors.md` (step 2
and step 3 sections).

Read first
- `~/git/dtc-website/courses/services/testimonials.py`, `courses/admin/testimonial.py`,
  `courses/admin/wrapped.py`, `courses/wrapped_statistics/`, `courses/views/wrapped.py`.

Steps
1. Testimonial management surface: Studio CRUD over `coursework.Testimonial` with the
   placement scope rule surfaced as form validation.
2. Wrapped statistics calculator port (`calculate_wrapped_statistics` with the activity,
   platform and per-user persistence) and the Studio read/recalculate surfaces.
3. Learner Wrapped pages: the public year page gated on `is_visible` and the per-member page
   readable by its owner and staff.

Verification
- `uv run pytest tests/coursework` -> pass; recalculation is idempotent under `force` and a
  no-op without it; the per-member page 404s for anyone but the owner and staff.
- `testproject`: calculate Wrapped statistics for a year with imported submissions and read
  the year page.

## C5.3 Release 0.6.0

Repository: community-base. Depends on: C3.7, C4.3, C5.2ec. Playbook P15.

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
