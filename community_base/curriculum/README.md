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
layout of `community_base/content_sync/FORMAT.md` section 3.8 and nothing else; the two layout
parsers that preceded it (`parsers_aisl.py`, `parsers_dtc.py`) are gone, and so is the layout
sniffing that decided between them.

```text
<course>/course.yaml
<course>/NN-<module>/module.yaml
<course>/NN-<module>/README.md                    module overview, optional
<course>/NN-<module>/NN-<unit>.md
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
| `UnitGraph` | one `NN-<unit>.md` per unit: `kind`, `video_url`, `timestamps`, `session_position`, `is_bonus`, `code`, with the markdown body unrendered. |
| `CohortGraph` | one `cohorts/<identifier>/cohort.yaml` per cohort; `delivery` becomes `mode`, `modules` becomes `module_refs`, `homework` becomes `homework_bindings`. |

Cohort placement follows the contract `CohortModule` already has: `module_refs is None` means
"no placement declared, show the course's full tree", and a tuple places exactly those top-level
modules in that order. An absent `modules` list is `None`; `archive: true` is the empty tuple, so
an archived cohort places nothing and its own `README.md` is the notice for GitHub readers.
Declaring both is an error naming both keys.

A cohort's `homework` entries become `CohortGraph.homework_bindings`, a tuple of
`{module, source, unit}`. This parser validates that `module` names a top-level module and
carries the rest through; the manifests themselves are read by the coursework app (issue C7.11).

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
rejects a mixed module (children and direct units) or a tree deeper than two module levels,
naming the offending directory.

Run imports with the content sync command:

```text
uv run python manage.py sync_content --from-disk <checkout> --source <slug>
```

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
- A cohort that places nothing and a cohort that declared no placement are indistinguishable at
  the database level: both leave zero `CohortModule` rows, so `Cohort.effective_modules()` falls
  back to the course's default tree for either. An `archive: true` cohort therefore parses to the
  empty placement the format asks for and still displays the full tree. Separating the two needs
  a column on `Cohort`, which is the placement contract shipped in `C5.1e` and is not reopened by
  the parser issue.
