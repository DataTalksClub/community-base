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
| `Module` | Ordered module, owned by the course (shared across every cohort). `parent` makes it a submodule of another module -- maximum two module levels. A module holds either child modules or direct units, never both. `is_bonus` and `available_after_days` (a drip offset for a top-level module, cascading to its units unless they override it) round it out. |
| `Unit` | Lesson, owned by its module. `kind` is `lesson` (default), `homework`, `event` or `checklist_item`; `event` units carry `session_position` (1-indexed, not a foreign key -- the site resolves the real event per viewer, against the viewer's own cohort, at render time) instead of embedding cohort-specific data in shared curriculum. `is_bonus` excludes a unit from the progress denominator while it is still tracked and displayed. |
| `CohortModule` | Optional per-cohort placement of a top-level module: `cohort`, `module`, `sort_order`. A cohort with no placements shows the course's full module tree in module order -- the common case, requiring zero extra rows. A cohort with placements shows exactly that curated subset and order instead, for courses whose cohorts genuinely differ (two cohorts of the same course each placing a different module that represents an alternative treatment of one topic, for example). |
| `Enrollment` | User-cohort enrollment with soft-delete history. |
| `UnitProgress` | Per-user unit completion. |
| `Certificate` | One certificate per enrollment. |
| `CurriculumImportRun` | Bounded evidence for one source import attempt. |

`Course.get_syllabus()` returns cohorts with each one's effective modules attached as
`.syllabus_modules` (placements, or the course's default tree); `Cohort.effective_modules()`
computes the same thing for one cohort. Progress (`Course.total_units()`,
`Course.completed_units()`) and the depth-first reading order
(`services.get_all_units_ordered()`, reused by `get_next_unit`/`get_prev_unit`) walk this same
shape: for each top-level module, in `sort_order`, either its own units (a module with no
children) or each child module's units in order (a module with children) -- never both, since a
module never mixes children and direct units. `is_bonus` (on the unit, its module, or that
module's parent module) excludes a unit from the progress denominator; `kind="event"` units
still count; `kind="checklist_item"` units never count, whether or not they are marked
`is_bonus`.

## Pre-work checklists

A course's pre-work checklist (read the docs, set up the environment, install tools, before the
cohort starts) is an ordinary `Module` whose `Unit` rows use `kind="checklist_item"` -- no
separate model. `title` is the item's short title, `body`/`body_html` its description and any
link, and `UnitProgress` (via the existing `is_completed`/`mark_completed`/`unmark_completed`
services) tracks per-learner completion exactly like any other unit. `is_bonus` doubles as the
item's required/optional flag: `is_bonus=False` (the default) means required, `is_bonus=True`
means optional. Checklist items are excluded from `Course.total_units()`/`completed_units()` --
a pre-work checklist is a separate readiness track, not lesson/homework/event course progress.

```python
from community_base.curriculum.services import get_checklist_state

for item in get_checklist_state(user, pre_work_module):
    item.unit, item.is_required, item.is_completed
```

`services.get_checklist_items(module)` returns the raw ordered `Unit` rows without a user's
completion state. Neither the AISL nor the DTC content-sync parser emits `checklist_item` units
yet; today they are Studio- or API-authored only.

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
| `curriculum_aisl_course` | `course.yaml` + `module.yaml` (optionally nested one level: `01-module/01-submodule/module.yaml`) + numbered unit markdown. The numeric ordering prefix supplies sort order and is stripped from the slug at every level. Every course becomes one `self_paced` cohort that places the full course tree. |
| `curriculum_dtc_course_repository` | DTC course repository v1: root `course.yaml`, `SITE.md`, module manifests (optionally nested one level), `cohorts/<identifier>/cohort.yaml`. A `modules`-format cohort's `flow` is its placement of top-level modules (`CohortModule`), not a private copy. Homework manifests are left unread until the coursework app imports them. |

Both parsers produce the same source graph (`community_base.curriculum.source`): a course owns
one module tree (`CourseGraph.modules`, recursive via `ModuleGraph.children`), and a cohort
carries `module_refs` -- `None` for "no placement declared, show the full tree" (every AI
Shipping Labs course), or an ordered tuple of top-level module identifiers to place (DataTalks.Club
cohorts that curate a subset or order). One importer applies the graph: source-managed rows are
created, updated or removed to match the repository, a course that vanishes is soft-deleted to
`draft`, and every import records a `CurriculumImportRun`. Re-importing unchanged content is a
no-op. `source.validate_module_tree` rejects a mixed module (children and direct units) or a tree
deeper than two module levels, naming the offending directory.

Run imports with the content sync command:

```text
uv run python manage.py sync_content --from-disk <checkout> --source <slug>
```

## Studio

Mount the Studio routes and register the section (done by the app config):

```python
urlpatterns = [
    path("studio/", include("community_base.curriculum.studio_urls")),
]
```

Routes cover courses (with their module tree), cohorts, modules, units, instructors,
enrollments and certificate issuing, registered under the `Courses` section. Modules and units
are managed from the course page, since curriculum is course-owned; a cohort's page shows its
effective modules read-only. Rows with provenance are source-managed: Studio renders them
read-only and refuses saves, because the repository is the truth.

## Staff API

The app registers bearer-authenticated routes under `/api/v1/` (scopes `curriculum.read`
and `curriculum.write`):

| Route | Purpose |
|---|---|
| `GET/POST /api/v1/courses/<slug>/enrollments` | List enrollments; bulk enroll into the self-paced cohort (four-bucket result). |
| `DELETE /api/v1/courses/<slug>/enrollments/<email>` | Soft-unenroll a learner from every cohort of the course. |
| `GET/POST /api/v1/courses/<slug>/certificates` | List certificates; issue or update one per active enrollment. |
| `DELETE /api/v1/courses/<slug>/certificates/<email>` | Not available: revoke in Studio. |
| `GET/PUT /api/v1/courses/<slug>/instructors` | Read or atomically replace the ordered instructor list (409 for source-managed courses). |

## Domain services

`community_base.curriculum.services` provides enrollment (`ensure_enrollment`, `unenroll`,
`get_or_create_self_paced_cohort`), progress (`mark_completed`, `unmark_completed`,
auto-enrollment into an explicit or self-paced cohort on completion), the cohort drip decision
(`decide_unit_drip(user, unit, cohort)`: the unit's own `available_after_days`, falling back to
its module's and then that module's parent module's, against the cohort start date; never
locking self-paced or unenrolled learners -- `cohort` is explicit because curriculum is
course-owned, so a unit has no single cohort of its own) and the depth-first reading-order
helpers.

## Known limitations

- Public pages (`/courses/<slug>/<cohort_slug>/<module_slug>/...`) resolve `module_slug`
  against top-level modules only; deep-linking straight to a unit inside a submodule is not
  yet routed. Nested content parses, imports and computes correctly; its public browsing pages
  are a follow-up.
- A DataTalks.Club `legacy`-format cohort (one with no module content at all) and a cohort with
  no placement rows are currently indistinguishable at the database level: both read as "show
  the course's default tree" through `Cohort.effective_modules()`. This only matters for a
  course that mixes a `legacy` cohort with a `modules`/`shared` cohort in the same family, a
  narrow case during DataTalks.Club's own per-family migration window.
