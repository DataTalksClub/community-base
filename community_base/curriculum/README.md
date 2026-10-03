# Curriculum

`community_base.curriculum` owns courses, cohorts, modules and units, enrollments, unit
progress and completion certificates, plus the import pipeline for the one content format. It
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
| `Module` | Ordered module, owned by the course (shared across every cohort). `parent` makes it a submodule of another module -- maximum two module levels. A module may hold direct units and child modules together. `is_bonus` and `available_after_days` (a drip offset for a top-level module, cascading to its units unless they override it) round it out. |
| `Unit` | Lesson, owned by its module. `kind` is `lesson` (default), `homework`, `event` or `checklist_item`; `event` units carry `session_position` (1-indexed, not a foreign key -- the site resolves the real event per viewer, against the viewer's own cohort, at render time) instead of embedding cohort-specific data in shared curriculum. `is_bonus` excludes a unit from the progress denominator while it is still tracked and displayed. |
| `CohortModule` | Optional per-cohort placement of a top-level module: `cohort`, `module`, `sort_order`. A cohort with no placements shows the course's full module tree in module order -- the common case, requiring zero extra rows. A cohort with placements shows exactly that curated subset and order instead, for courses whose cohorts genuinely differ (two cohorts of the same course each placing a different module that represents an alternative treatment of one topic, for example). |
| `Enrollment` | User-cohort enrollment with soft-delete history; remains the coursework and certificate enrollment type. |
| `CourseEnrollment` | User-course enrollment with soft history and at most one active row per user and course. |
| `UnitProgress` | Per-user unit completion. |
| `Certificate` | One certificate per enrollment. |
| `CurriculumImportRun` | Bounded evidence for one source import attempt. |

`CourseEnrollment` is independent of cohort membership. Its reverse relations are
`user.curriculum_course_enrollments` and `course.course_enrollments`; an inactive row stays as
history, and a later enrollment creates a new active row. Cohort `Enrollment` remains the type
used by coursework, certificates and the existing public and staff enrollment endpoints.
The additive course-enrollment migration can be reversed while its table is empty. Once a site
has populated course history, application rollback retains the migration and table until A5.1's
rehearsed back-copy and rollback acceptance permit retirement.

`Course.get_syllabus()` returns cohorts with each one's effective modules attached as
`.syllabus_modules` (placements, or the course's default tree); `Cohort.effective_modules()`
computes the same thing for one cohort. Progress (`Course.total_units()`,
`Course.completed_units()`) and the depth-first reading order
(`services.get_all_units_ordered()`, reused by `get_next_unit`/`get_prev_unit`) walk this same
shape: for each top-level module, in `sort_order`, its direct units and child modules follow their
shared source order when both kinds are present. Pure legacy sibling sets retain their existing
`sort_order` and primary-key ties. `is_bonus` (on the unit, its module, or that
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
completion state. The course parser reads `kind: checklist_item` (section 3.8 lists it), but no
content repository authors one yet; today they are Studio- or API-authored in practice.

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

The app registers exactly one `content_sync` parser, `curriculum_course`. It reads the course
layout of `community_base/content_sync/FORMAT.md` section 3.8 and nothing else; the two
site-shaped parsers that preceded it are deleted, and so is the layout sniffing that decided
between them (issue C7.10 names both files).

```text
<course>/course.yaml
<course>/NN-<module>/module.yaml
<course>/NN-<module>/README.md                    module overview, optional
<course>/NN-<module>/NN-<unit>.md
<course>/NN-<module>/NN-<homework>/homework.yaml
<course>/NN-<module>/NN-<homework>/homework.md
<course>/NN-<module>/NN-<submodule>/module.yaml   optional second module level
<course>/cohorts/<identifier>/cohort.yaml
<course>/cohorts/<identifier>/README.md           cohort notice, optional
<course>/cohorts/<identifier>/homework/<module-slug>/homework.yaml
```

`<course>` is a collection of kind `course` declared in the repository's `content.yaml`: `.` for
a single-course repository (where `course.yaml` declares its own `slug`), or one entry per course
in a repository that holds several. A repository of three courses therefore imports three, and a
`course.yaml` at the repository root is an ordinary course rather than a file to skip.

The parser is thin by construction. `content_sync.documents` walks the collection, splits the two
file shapes, validates the core and kind keys, derives `slug`, `sort_order` and `required_level`,
and checks identity; `content_sync.kinds` owns the layout and the per-part schemas.
`curriculum/parsers.py` maps what they read onto `community_base.curriculum.source`, and reports
their diagnostics unchanged: a rejected file comes back with its path, a pointer into it and the
number of the rule in `FORMAT.md`. A retired key (`prev_url`, `next_url`, `is_homework`,
`is_preview`, `access`, `schema_version` in anything but `content.yaml`) is named by that
diagnostic, not by a second rule written in the parser.

| Graph | From |
|---|---|
| `CourseGraph` | `course.yaml` plus the core keys; `image` becomes `cover_image_url`, `repository_url` becomes `github_repo_url`, `status` drives `visible`. |
| `ModuleGraph` | one `module.yaml` per module directory, its `README.md` as `overview`, `sort_order` from the `NN-` prefix, recursive through `children` to at most two module levels. |
| `UnitGraph` | one `NN-<unit>.md` per Markdown unit, or a module's `NN-<homework>/homework.yaml` with its sole `homework.md` prose companion. The YAML form is a homework Unit with stable identity, title, slug and order from the directory. |
| `CohortGraph` | one `cohorts/<identifier>/cohort.yaml` per cohort; `delivery` becomes `mode`, `modules` becomes `module_refs`, `homework` becomes `homework_bindings`. |

Cohort placement follows the contract `CohortModule` already has: `module_refs is None` means
"no placement declared, show the course's full tree", and a tuple places exactly those top-level
modules in that order. An absent `modules` list is `None`; `archive: true` is the empty tuple, so
an archived cohort places nothing and its own `README.md` is the notice for GitHub readers.
Declaring both is an error naming both keys.

A cohort's `homework` entries become `CohortGraph.homework_bindings`. Existing entries name a
cohort manifest with `source` and may also name a `unit` page. A `unit` with no `source` selects
an authored course-tree homework Unit by content ID. The parser validates the top-level module
and carries the binding to the coursework reader; the reader validates the selected source even
when coursework models are not installed. An unbound authored Unit remains a prose page.

Three parser rulings, where section 3.8 is silent:

- A course that declares no `cohorts/` directory gets one implicit open-ended self-paced cohort
  placing the full tree, which is the row `services.get_or_create_self_paced_cohort` would mint
  on demand anyway.
- A unit carries `required_level` only when it or one of its module ancestors declares one, so
  `Course.default_unit_required_level` still answers for a unit that declares nothing.
- An `instructors` reference resolves against a `person` collection of the same repository when
  there is one, and otherwise carries the reference itself as the instructor slug, which is what
  the importer matches an existing host by.

One importer applies the graph: source-managed rows are created, updated or removed to match the
repository, a course that vanishes is soft-deleted to `draft`, and every import records a
`CurriculumImportRun`. Re-importing unchanged content is a no-op. `source.validate_module_tree`
rejects duplicate sibling slugs, incomplete or duplicate mixed order, and trees deeper than two
module levels, naming the offending directory. Mixed siblings carry nullable internal
`source_sibling_position` values, separate from public `sort_order` and cohort placement order.
Existing pure trees and Studio rows keep null positions and their legacy ordering.

Hosts with project source files register one pure reader with
`project_modules.register_project_module_reader`. The reader yields
`ProjectModuleReference(project_id, source_path, module_path, pointer)` for each project in a
course collection. `module_path` is a directory relative to that collection, such as
`01-week-one/02-project`; `source_path` and `pointer` locate the host-owned authored reference.
The same resolver runs during sync and `check_content --kinds` before any domain write. It rejects
unknown or ambiguous module paths and duplicate project identities. The package neither parses
opaque `extra.projects` nor stores a course-level project pointer.

### Module identity during parent moves

A module matched by its course-scoped source identity keeps its row and its units when it
moves between parents or between child and top level within that valid tree. The importer writes
the new parent before deleting stale modules, so removing the old parent preserves the moved
module, unit progress and homework links. A parent change counts as updated once; an identical
reimport is unchanged. Stored slugs and parent-plus-slug fallback retain their existing behavior.
Cohort placements still target top-level modules and follow their existing synchronization rules.

This is the bounded module preservation guarantee of `C5.4b`; C5.4 adds mixed sibling order on
top of it. YAML-backed homework units were added in `C5.4c`, and unit movement between module
rows in `C5.4a`. Package fixtures do not establish
AISL donor equivalence or replace
the development-copy rehearsal required during adoption.

### Unit identity during module moves

Unit identity lookup spans the importing course, so moving an authored unit to another module
retains its primary key and stored slug. The destination module participates in the normal
change comparison: an otherwise unchanged move counts as one update, and a repeated import is
unchanged. Units in other courses are isolated, including independent repositories reusing a UUID.

Before any import-run or domain write, the importer plans final unit destinations. It rejects
duplicate incoming unit identities, ambiguous identities in the course, duplicate final slots,
and collisions with retained or unmanaged units. Same-slug swaps and cycles remain valid, as
does replacing a genuinely stale source-managed destination. Conflicting occupants are parked
under temporary internal slugs inside the transaction without save hooks; successful upserts
restore the original slugs, and a failure rolls back the whole import.

Known identities are reserved before slug fallback, so a new unit filling a moved unit's old
slot cannot take that unit's identity. Where no matching identity exists, the existing
module-plus-slug fallback still applies, including absent or replaced content IDs. This differs
from FORMAT section 3.4's general changed-ID/new-record description; this bounded fix preserves
the curriculum importer's current behavior and does not rename stored slugs.

Stale-unit cleanup runs after every module's unit upserts and before stale-module deletion.
Moving out of a removed module therefore preserves UnitProgress, Homework.unit and the existing
homework questions, submissions and answers. Homework.module separately becomes null when its
module is deleted, under its existing SET_NULL rule. This package behavior does not prove AISL
UserCourseProgress or donor-data compatibility; those need the later site adoption rehearsal.
Whole-module reparenting was added by C5.4b, and C5.4c extended stable Unit identity to authored
YAML homework units. C5.4 now projects mixed trees; donor site adoption remains separate work.

The course parser validates both homework source forms before writing curriculum. Its one outer
transaction applies curriculum and cohort-owned coursework, then cleans up only assignments not
retained by either source form. Source path and containing module changes retain Unit identity;
explicit per-cohort bindings retain separate Homework and Question identities and learner rows.
An invalid authored question or binding leaves curriculum and coursework unchanged.

Run imports with the content sync command:

```text
uv run python manage.py sync_content --from-disk <checkout> --source <slug>
```

### Site course adaptation

The package remains the only parser and writer for converted course collections. A host that
needs its own policy, rendering and extension rows may register one course-specific adapter with
`curriculum.site_adaptation.register_course_site_adapter`. Registration rejects a different
second adapter, and `CourseParser` reads the registration during `discover`, so Django app order
does not change which object owns the import.

The adapter has four bounded operations:

- `prepare(context, collection, parsed)` validates host policy and returns `PreparedCourse`;
- `apply_scope(context, prepared)` supplies the renderer and validated pre-write work;
- `after_apply(context, prepared, core)` writes host extension rows and returns
  `CourseSiteResult`;
- `report(context, results=..., errors=..., drafted=..., totals=...)` publishes item deltas and
  cumulative host counts.

The package reads course and homework sources, validates the prepared graph, opens the transaction,
calls its graph and homework importers exactly once, and owns provenance and stale cleanup. A
prepared graph may change only the course cover URL, module overview, and unit body or homework
render fields. Course, module, unit and cohort identity, topology and homework bindings must stay
equal. Validation happens before the site scope or any writes.

`CourseSiteRefusal` is an authored refusal only when `prepare` raises it. Other per-item failures
roll back, report as internal failures, continue valid siblings and suppress stale cleanup. Known
`CurriculumParseError` subclasses are authored source failures in any phase. The adapter's
`report` implementation owns source-scoped exception logging: it receives the `SourceItem`, the
live exception with its traceback and the authored/internal classification, and must redact secrets.
`CheckoutError` and `CourseSiteBoundaryError` stop the parser. Accepted results and failures report
immediately, so their details and cumulative counts survive a later boundary failure. A nonfatal
warning still commits and permits cleanup, then makes the adapted family partial. A scope that
suppresses a core or post-apply exception fails closed inside the transaction.

The generic package orchestrator records a fatal course-parser boundary as `partial`, because its
parser boundary catches all parser exceptions while continuing other content types. A host may
upgrade that run to `failed` only from its own structured boundary evidence. AISL does this when
the adapter reports the original `ContentCheckoutError.as_error()` entry with
`step: filesystem_boundary`; a bare `CourseSiteBoundaryError` message is not that evidence.

The ordinary path uses no lifecycle calls and retains its existing behavior when no adapter is
registered. A later site adoption must also stop its retired converted-course parser from emitting
an empty family cleanup/count report: a collector keyed by family can otherwise replace the
adapter's totals depending on registration order. The legacy parser may continue to own only
unconverted sources. That adoption must test both parser registration orders.

## Code annotations

A unit body can attach notes to lines of a fenced code block. The author writes a standalone
HTML comment immediately after the closing fence:

````text
```python
first = 1

third = first + 2
print(third)
```
<!--
structured: true
code_annotations:
  - line: 1
    text: Set the initial value.
  - lines: "2-3"
    text: The blank line still counts.
-->
````

The authoring contract is the one specified on AI-Shipping-Labs/website#1589, unchanged, so a
body written for either site behaves the same way here.

| Rule | Detail |
|---|---|
| Placement | A standalone multi-line `<!--` / `-->` comment, separated from the closing fence by blank lines only. An inline comment carrying a reserved key is an error, not metadata. |
| Payload | Exactly the keys `structured: true` and `code_annotations`, a non-empty sequence. Duplicate YAML keys are rejected; the loader is a safe loader, so a YAML tag never constructs an object. |
| Selector | Each item carries exactly one of `line` (a positive integer) or `lines` (a quoted `start-end` range with `start < end`), plus a non-empty `text`. |
| Ranges | Ranges must fit the block's visible line count and must not overlap or repeat. |
| Targets | One payload per block. A payload with no code fence in front of it, or one in front of a `mermaid` or `eventwidget` fence, is an error. |
| Note text | Plain text. It is whitespace-collapsed and escaped, never rendered as markdown, so a link or a tag in a note stays literal. |

Anything that claims to be annotation metadata but breaks a rule raises
`code_annotations.CodeAnnotationError`. A comment that makes no such claim is ordinary markdown
and is left alone.

The capability is split so the package owns meaning and each site owns appearance:

| Layer | Owner | Where |
|---|---|---|
| Parsing, validation, structured representation | package | `curriculum/code_annotations.py`: `parse_annotated_body` returns the stripped markdown plus one `AnnotatedCodeBlock` per fenced block (`language`, `CodeLine` rows carrying `number`/`text`/`is_highlighted`, and the `CodeAnnotation` notes with a ready-to-print `label`). No HTML, no Django. |
| Default markup | package, overridable | `curriculum/templates/curriculum/annotated_code_block.html`. |
| Styling | site | Each site adds rules for the hooks below to its own stylesheet. |

Line highlighting is expressed structurally, not visually: `CodeLine.is_highlighted` in the
parse result, and in the default markup an `is-highlighted` modifier plus a `data-line-number`
attribute on each `code-annotation-line`. The default template emits structural hooks only --
`annotated-code-block`, `code-line-gutter`, `code-line-number`, `code-annotation-line`,
`code-annotations`, `code-annotations-heading`, `code-annotation-list`, `code-annotation-note`,
`code-annotation-label`, `code-annotation-text` -- and no colour, spacing or typography. Decision
D18 keeps public design systems per site, so the package ships no stylesheet for them: a site
that adopts the feature styles those hooks itself, or overrides the template at the same path and
emits whatever markup its design system wants. Until a site does one of the two, an annotated
block renders as readable but unstyled numbered lines followed by the note list.

The package does not syntax-highlight. `render_markdown` has no codehilite extension, so a
fenced block renders as plain escaped text here, and an annotated one is the same text split into
numbered lines with the language kept on `<code class="language-...">` for a site that wants to
highlight client-side. A site that wants server-side highlighting registers `codehilite` through
`COMMUNITY_BASE["MARKDOWN_EXTENSIONS"]`.

`rendering.render_markdown`, `sanitize_rendered_html` and `strip_leading_title_h1` are imports of
`community_base.content_sync.rendering`, the one renderer and the one sanitizer (issue C7.8). The
import paths here are unchanged. Two things changed for a unit body: headings carry the ids of
`FORMAT.md` section 4.1, and the allowlist is the shared one, which keeps `<figure>`, `<details>`
and `<del>` that the narrower curriculum allowlist used to drop, and drops an `img src` that is
neither site-absolute nor an absolute `http(s)` URL.

`Unit.body_html_source` says who rendered the unit body, the way
`KnowledgeBasePage.body_html_source` does. At `markdown`, the default, `save()` renders the body.
At `site`, set by `unit.set_rendered_html(html)`, `save()` sanitizes the supplied HTML and stores
it unchanged, which is what a parser that renders at sync time needs.

`rendering.render_annotated_markdown` is the unit-body entry point and `Unit.save()` calls it, so
annotations are rendered once at ingestion rather than per request. A body with no annotations
renders exactly like `render_markdown`. Rendering is not a second markdown path or a second
sanitizer: the markdown still goes through `render_markdown` (which sanitizes), and the annotated
block is markup this package generates afterwards from the parsed structure, with the two
author-supplied strings -- code text and note text -- autoescaped by the template.

The course parser validates a lesson body before anything is written, so a malformed payload
fails the import as a `CurriculumParseError` naming the source file, rather than reaching a reader
as visible YAML. `Unit.save()` fails the same way, which means an invalid replacement body leaves the
previously published unit untouched.

Rendered HTML is stored on the row. A site that overrides the template, or changes its markup,
re-renders existing units by re-running the sync (or re-saving them); the stored HTML is not
regenerated on read.

AI Shipping Labs keeps its local copy in `content/utils/code_annotations.py` until it adopts this
curriculum app, and deletes it then. Removing it earlier is not part of this work: the site cannot
consume the package curriculum yet.

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

The published member JSON APIs at `/courses/api/courses/` and
`/courses/api/courses/<slug>/` include an additive `public_url` field. It is the absolute
canonical course page URL built from `COMMUNITY_BASE["SITE_URL"]` and `Course.get_absolute_url()`;
draft or hidden courses return `null`. The existing `cover_image_url`, `discussion_url` and
certificate URLs keep their existing meanings.

These are Django member-page JSON views, not routes in the versioned `/api/v1/` registry, so
they are intentionally outside `community_base/api/openapi.json`. This section is their
canonical response contract; the bearer-authenticated staff curriculum routes remain operational
APIs and do not receive `public_url`.

## Domain services

`community_base.curriculum.services` provides enrollment (`ensure_enrollment`, `unenroll`,
`get_or_create_self_paced_cohort`), progress (`mark_completed`, `unmark_completed`,
auto-enrollment into an explicit or self-paced cohort on completion), the cohort drip decision
(`decide_unit_drip(user, unit, cohort)`: the unit's own `available_after_days`, falling back to
its module's and then that module's parent module's, against the cohort start date; never
locking self-paced or unenrolled learners -- `cohort` is explicit because curriculum is
course-owned, so a unit has no single cohort of its own) and the depth-first reading-order
helpers.

Course-level history uses six separate services: `get_active_course_enrollment`,
`is_course_enrolled`, `ensure_course_enrollment`, `unenroll_from_course`,
`course_enrollment_history` and `active_course_enrollment_count`. They query and mutate only
`CourseEnrollment`; they do not select or create a cohort. Sites own public presentation,
entitlement policy and side effects for this signal.

## Public curriculum navigation

The generic curriculum views keep flat module and unit routes and JSON response shapes. Nested
pages use `/courses/<course>/cohorts/<cohort>/curriculum/<ancestry>/`, where ancestry contains the
root module, child module and optional unit slug. Repeated child slugs resolve through ancestry.
The API emits full child payloads once and shallow ordered sibling references. A site may supply
its own cohort-aware URL builder when rendering package projections.

Cohort placements curate syllabus and `effective_modules()` only. Reader destinations, sidebars,
previous/next and Continue follow the complete course tree, using the selected cohort for URLs,
homework and drip. The selected cohort must belong to the course and be visible. This preserves
flat reader behavior even when a cohort curates a subset or another order.

## Instructor import compatibility

The importer uses the installed model targeted by `CourseInstructor.host` (`events.Host`).
Consumers may retain their own events app while adopting curriculum models and sync. Their host
model supplies name, slug, bio, bio_html and updated_at; slug/name lookup, biography updates and
course-instructor positions retain the existing import behavior. The `kind` discriminator is
optional: when the installed model defines it, lookup and creation use `kind="instructor"`; a
model without it keeps the same identity and update behavior through its common fields.
Instructor-free graphs do not resolve or import an events model. Package events API and Studio
surfaces remain conditional on the package events app being installed.

## Known limitations

- A cohort that places nothing and a cohort that declared no placement are indistinguishable at
  the database level: both leave zero `CohortModule` rows, so `Cohort.effective_modules()` falls
  back to the course's default tree for either. An `archive: true` cohort therefore parses to the
  empty placement the format asks for and still displays the full tree. Separating the two needs
  a column on `Cohort`, which is the placement contract shipped in `C5.1e` and is not reopened by
  the parser issue.
