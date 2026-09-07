# Curriculum

`community_base.curriculum` owns courses, cohorts, modules and units, enrollments, unit
progress and completion certificates, plus the import pipeline for both source layouts. It
exists so that neither site defines a `Course`, `Module` or `Unit` model.

## Installation

Add the app after the events app:

```python
INSTALLED_APPS = [
    "community_base.kernel",
    "community_base.events",
    "community_base.curriculum",
]
```

Run migrations:

```text
uv run python manage.py migrate
```

## Models

| Model | Purpose |
|---|---|
| `Course` | Reusable course; tags, testimonials, links, access levels, provenance. |
| `Cohort` | One delivery of a course: `mode="cohort"` (dated) or `mode="self_paced"` (one per course). |
| `Module` | Ordered module inside a cohort. |
| `Unit` | Lesson with video, markdown body, homework and drip offset. |
| `Enrollment` | User-cohort enrollment with soft-delete history. |
| `UnitProgress` | Per-user unit completion. |
| `Certificate` | One certificate per enrollment. |
| `CurriculumImportRun` | Bounded evidence for one source import attempt. |

Rows synced from a repository carry complete provenance (`source_content_id`, `source_path`,
`source_commit_sha`, `source_checksum`); Studio-managed rows carry none.

## Access

`community_base.curriculum.access.can_access(user, obj)` resolves the unit level chain
(unit override, then course default, then course `required_level`) and delegates the level
check to the configured `ACCESS_POLICY`. Individual purchase access is delegated to the site:

```python
COMMUNITY_BASE = {
    # Return True when this user holds a purchase or grant for this course.
    "COURSE_ACCESS_GRANTS": "payments.hooks.course_access_grants",
}
```

The hook is optional; without it only policy levels grant access. `Unit.is_preview` is not
part of `can_access`; callers check it separately so preview badges keep working.

## Import

The app registers two `content_sync` parsers, each sniffing its layout in `discover`:

| Content type | Layout |
|---|---|
| `curriculum_aisl_course` | `course.yaml` + `module.yaml` + numbered unit markdown. Every course becomes one `self_paced` cohort. |
| `curriculum_dtc_course_repository` | DTC course repository v1: root `course.yaml`, `SITE.md`, module manifests, `cohorts/<identifier>/cohort.yaml`. Homework manifests are left unread until the coursework app imports them. |

Both produce the same source graph (`community_base.curriculum.source`) and apply it through
one importer: source-managed rows are created, updated or removed to match the repository, a
course that vanishes is soft-deleted to `draft`, and every import records a
`CurriculumImportRun`. Re-importing unchanged content is a no-op.

Run imports with the content sync command:

```text
uv run python manage.py sync_content --from-disk <checkout> --source <slug>
```

## Domain services

`community_base.curriculum.services` provides enrollment (`ensure_enrollment`, `unenroll`),
progress (`mark_completed`, `unmark_completed`, auto-enrollment on completion), the cohort
drip decision (`decide_unit_drip`: `available_after_days` against the cohort start date, never
locking self-paced or unenrolled learners) and reading-order helpers.
