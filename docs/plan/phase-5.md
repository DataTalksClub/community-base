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

## C5.2 Coursework app

Repository: community-base. Depends on: C5.1d.

Read first
- `~/git/dtc-website/courses/models/homework.py`, `project.py`, `courses/scoring.py`,
  `leaderboard.py`, `project_*.py`, `homework_*.py`, `courses/views/`, `studio_courses/`,
  `_docs/specs/04-courses-and-cohorts.md` "Preserved learner behavior".

Steps
1. Models (`label = "cb_coursework"`) from DTC with `cohort` FK to `cb_curriculum.Cohort`:
   `Homework`, `Question`, `Submission`, `Answer`, `HomeworkStatistics`, `Project`,
   `ProjectSubmission`, `ProjectVote`, `ReviewCriteria`, `ProjectCriteriaAssignment`, `PeerReview`,
   `CriteriaResponse`, `ProjectEvaluationScore`, `ProjectStatistics`, `LeaderboardComplaint`,
   `RegistrationCampaign`, `CourseRegistration`, `Testimonial`, `WrappedStatistics`.
2. Services, scoring, leaderboard, deadline reminders (as job handlers and mail purposes),
   learner views, Studio pages from `studio_courses`, API endpoints from DTC `api`.
3. AISL's light `PeerReview` and `ProjectSubmission` (content app) map to `ProjectSubmission`
   and `PeerReview` here; the AISL peer-review settings on `Course` become a `Project` per
   cohort with the same criteria text.
4. Tests moved from DTC `courses/tests/` and `studio_courses/tests/`.

Verification
- `make test tests/coursework` -> pass with at least DTC's test count for these modules.
- `testproject`: submit homework, score it, leaderboard position computed; submit project, peer
  review assignment, evaluation score, certificate issued.

## C5.3 Release 0.6.0

Repository: community-base. Depends on: C3.7, C4.3, C5.2. Playbook P15.

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
