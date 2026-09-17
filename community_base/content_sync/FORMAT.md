# The DataTalks.Club content format, version 1

Normative. This file is the contract a synced content repository is checked against, and
`community_base/content_sync/kinds/` is the registry that enforces it. Decision D23 adopts it;
there is no backwards compatibility, so every content file may be rewritten.

The section numbers are those of `docs/plan/evidence/unified-content-format-2026-09-17.md`
sections 3 and 4, kept unchanged so that issues, diagnostics and the design document cite the same
rule by the same number. A diagnostic from `check_content` names the rule it enforces, for example
`[3.3]` for a core key.

Everything below is normative unless a paragraph says recommendation. Where the design document
left a mechanism unstated, the paragraph is marked "Package ruling" and says what the package
decided and why.

Contents

- 3.1 Repository manifest
- 3.2 Two file shapes
- 3.3 Core keys
- 3.4 Naming, ordering and identity
- 3.5 Nesting
- 3.6 Assets
- 3.7 Cross-references
- 3.8 Kind registry and kind schemas
- 3.9 Worked examples
- 3.10 Validation
- 4.1 The dialect
- 4.2 Where rendering lives and who owns what
- 4.3 What breaks
- 5 Not yet implemented

## 3.1 Repository manifest

Every synced repository carries `content.yaml` at its root. A repository without it is not synced;
the engine records one error and stops for that source.

```yaml
schema_version: 1
collections:
  - kind: article
    path: articles
  - kind: person
    path: people
  - kind: data
    path: data
ignore:
  - "**/*.template.md"
  - "**/solution.md"
strict_references: true
```

| Key | Type | Required | Default | Rule |
|---|---|---|---|---|
| `schema_version` | integer | yes | none | must equal `1`; the only place a version is written |
| `collections` | list | yes | none | at least one entry |
| `collections[].kind` | string | yes | none | a kind registered in the package or by the site (section 3.8) |
| `collections[].path` | string | yes | none | repository-relative directory; `.` means the whole repository and then no other collection may be declared; two collections never nest |
| `ignore` | list of globs | no | `[]` | matched against repository-relative paths; a matched file is invisible to every collection |
| `strict_references` | boolean | no | `true` | `true` fails the sync on an unresolved reference (section 3.7); `false` records a warning and drops the link |
| `theme_pairs` | boolean | no | `false` | `true` turns a `name.dark.ext` sibling of a referenced image into a paired image (section 3.6) |

Unknown top-level keys in `content.yaml` are an error. Files outside every collection path are
ignored, not errors.

Package ruling: `theme_pairs` is a property of the repository and of nothing smaller. The design
document put it in this table but left open what happens to one asset referenced from two
collections. There is no such case: a reference never leaves its repository (section 3.6), so every
reference to an asset is made under one `theme_pairs` value. A per-collection or per-kind override
is therefore not part of version 1, and a kind cannot declare one. C7.9b owns assets and may
propose one, but it then also owns the answer for a shared asset.

Glob syntax for `ignore` is the `pathlib.PurePosixPath.full_match` syntax: `*` does not cross a
directory separator, `**` does, and a pattern is matched against the repository-relative path.

## 3.2 Two file shapes

- A document is a `.md` file whose first line is `---`, followed by YAML front matter, a line
  `---`, then the markdown body. Front matter is required; a `.md` file without it inside a
  collection is an error. UTF-8, LF line endings.
- A manifest is a `.yaml` file whose top level is a mapping.
- File names inside a collection: `NN-slug.md`, `slug.md`, `index.md`, `README.md`,
  `<fixed name>.yaml` as the kind prescribes. Files and directories whose name starts with `_` or
  `.` are ignored.
- A `README.md` is read only where a kind names it (module overview, workshop landing copy,
  cohort notice). Elsewhere it is ignored rather than an error, so that a collection may explain
  itself to GitHub readers.

## 3.3 Core keys

Every document and every item manifest (course, module, cohort, homework, workshop, podcast, book)
carries the core keys. Unknown top-level keys are an error. A kind adds keys; it never removes,
renames or retypes a core key.

| Key | Type | Required | Default | Rule |
|---|---|---|---|---|
| `content_id` | UUID string, any version | yes | none | permanent identity; unique across the whole repository regardless of kind; quoted in YAML |
| `title` | string, 1 to 300 chars | yes | none | display title; the body must not repeat it as a leading H1 (the renderer strips one if present) |
| `slug` | slug | no | file or directory name with the ordering prefix removed | pattern `^[a-z0-9]+(?:-[a-z0-9]+)*$`, at most 100 chars; unique among siblings |
| `summary` | plain text, at most 500 chars | no | `""` | one line for cards, search and meta description; no markdown |
| `status` | `draft` or `published` | no | `published` | a draft is imported and hidden |
| `required_level` | integer, or one of `open`, `registered`, `basic`, `main`, `premium` | no | inherited from the parent item, else `0` | resolved to the integer through `curriculum.source.ACCESS_NAMES`; decision D5 |
| `sort_order` | integer | no | the numeric prefix of the file or directory name, else `0` | sibling order; ties break by slug |
| `tags` | list of slugs | no | `[]` | free taxonomy |
| `image` | relative path or `https://` URL | no | `""` | the item's cover, picture or thumbnail (section 3.6) |
| `date` | ISO date `YYYY-MM-DD` | kind-dependent | none | required by article, project, podcast, book, workshop; forbidden elsewhere |
| `extra` | mapping | no | `{}` | site-specific keys; the package validates it is a mapping and never reads inside it; it is stored on the record and passed to the site parser |

The `data` kind is the one exception to this section and carries no core keys (section 3.8); its
file is an opaque record.

## 3.4 Naming, ordering and identity

- Ordering prefix: a file or directory name may start with two or three digits and a hyphen
  (`01-intro.md`, `01-agentic-rag/`, `001-first-question.md`). The prefix sets `sort_order` and is
  stripped from the slug. An explicit `sort_order` wins over the prefix. Two siblings that strip to
  the same slug are an error; two siblings with the same prefix are allowed.
- No date prefixes on names. Chronology is `date` in front matter. A name beginning `YY-MM-DD-` or
  `YYYY-MM-DD-` is an error even though its first group would otherwise read as an ordering prefix.
- `index.md` is the document of its directory (a tree node). `README.md` is for GitHub readers and
  is read only where a kind names it (module overview, workshop landing copy).
- `content_id` is the upsert key. A renamed file with the same `content_id` updates the same record
  with a new slug. A changed `content_id` creates a new record and drafts the old one, exactly as
  `knowledge_base.sync.delete_missing` and the curriculum soft delete do today.
- `slug` is the URL segment. `path` for a tree kind is the chain of ancestor slugs plus the slug,
  relative to the collection root, joined with `/`. The public URL is the site's decision: the
  package apps compute a default route from `(kind, path)` and a site may map it.
- Provenance: `source_content_id` on every synced row holds the item's own `content_id` from this
  format, and nothing else. It is not the id of the `ContentSource` row the item came from; a
  source foreign key is a separate field.

The provenance rule has a live contradiction in this package, recorded here because it is the
reason the rule is stated:

- `community_base/curriculum/importing.py` follows this rule and stores the item's `content_id`.
- `community_base/knowledge_base/sync.py` stores `ContentSource.pk` in the same field and scopes
  `delete_missing` by it.
- `ContentSource.id` and `SourceProvenanceMixin.source_content_id` are both `UUIDField`, so the two
  meanings have the same type and the mistake cannot raise; it produces rows whose provenance
  points at a source instead of an item.

Issue C7.9c repairs the knowledge base by adding the source foreign key and migrating the field.
C7.7 ships no migration and therefore only writes the contract down, in this section and in the
`SourceProvenanceMixin` docstring.

## 3.5 Nesting

- A tree is expressed by directories and by nothing else. `parent:` keys do not exist.
- In a docs collection: a directory is a node and must contain `index.md`; leaves are `NN-slug.md`
  files; maximum depth four below the collection root.
- In a course: a module is a directory holding `module.yaml`; a submodule is a directory holding
  `module.yaml` inside a module directory; maximum two module levels
  (`curriculum.source.validate_module_tree`); a module directory holds either submodule directories
  or unit files, never both, apart from `README.md` and asset directories.
- A wiki collection is flat: one directory of `slug.md` files; subdirectories are an error, apart
  from asset directories.
- Cohorts are not part of the tree; they are placements (section 3.8, course).

An asset directory is a directory holding only files of the allowed asset types of section 3.6, at
any depth. It carries no items and is skipped by every layout rule above.

## 3.6 Assets

- An asset is any file that a document body, a manifest key of asset type (`image`, and the
  kind-declared ones), or an HTML `<img src>` references by a relative path.
- A reference resolves from the referencing file's directory and must stay inside the repository. A
  path that escapes the repository, an absolute `/path`, a Liquid expression or a `{IMAGE:id}`
  token is an error. An asset may live outside every collection (a shared `images/` root) as long
  as a document references it.
- `https://` references are left alone. `http://` and `data:` references are errors.
- Allowed asset types: `png`, `jpg`, `jpeg`, `gif`, `webp`, `svg`, `pdf`. The engine applies
  signature and unsafe-SVG checks to every asset before upload. Maximum 16 MiB.
- The engine uploads every referenced asset through `content_sync.media` keyed by the repository
  path and rewrites the reference in the rendered HTML and in stored asset keys. Unreferenced files
  are not assets and are not uploaded.
- Recommendation: keep an item's assets in an `images/` directory next to the item (article
  directory, module directory, workshop directory) or, for flat collections, in
  `<collection>/images/`.
- `theme_pairs` (section 3.1) makes `name.dark.ext` a paired asset of `name.ext`; the engine emits
  both with the class hooks the site styles.

Package ruling: a file matched by `ignore` is invisible to every collection, and that includes
being invisible as an asset. A reference to an ignored file is an unresolved reference, reported
against the referencing file, not a silent success. The alternative, letting `ignore` hide a file
from collection discovery but keep it uploadable, would make `ignore` mean two things.

Package ruling, when the rewrite happens: an asset path and a cross-reference are resolved after
the markdown is rendered and before the sanitiser runs; `rendering.render_html` is that seam.
Section 4.1 said "before rendering", and that order cannot hold. The sanitiser drops a relative
`img src` (section 4.2), so a rewrite that ran after it would rewrite an attribute that is already
gone, and a reference-style link or an autolink is only a destination once the markdown is HTML.
The stored HTML still carries the rewritten reference, which is what this section asks for.

Package ruling, the paired markup: `theme_pairs` replaces the image with two `<img>` tags, adjacent
and with no whitespace between them as in the AI Shipping Labs donor, each carrying
`data-theme-figure` (`light` or `dark`) and the classes `cb-theme-figure cb-theme-figure-light` or
`cb-theme-figure cb-theme-figure-dark`. A site styles those hooks; the package ships no stylesheet
(D18). The dark half is never itself a light base, so no `name.dark.dark.ext` is ever looked for,
and a dark sibling that fails a rule of this section is not paired.

Package ruling, what the reference is rewritten to: the URL the media store returned. The sanitiser
admits an `img src` that is site-absolute or an absolute `http(s)` URL and drops every other one
(section 4.2), so a store returning neither leaves a stored image without a `src`. The default
`null` backend returns the repository path unchanged and is one such store; a site that renders
synced images configures a store whose URL is one of the two admitted shapes.

## 3.7 Cross-references

One link syntax: a standard markdown link or image. Three destination forms.

| Form | Example | Resolution |
|---|---|---|
| Relative file | `[setup](02-environment.md)`, `[intro](../01-intro/index.md#running-example)` | another document in the same collection; resolved to that document's route; the fragment must name a heading of the target when both are in the same source |
| Typed reference | `[A/B testing](wiki:a-b-testing)`, `[Rahul](person:16rahuljain)`, `[project rules](docs:courses/llm-zoomcamp/project)`, `[module 1](course:llm-zoomcamp/agentic-rag)` | `kind:` prefix is a registered kind; the remainder is the target's slug, or its path for a tree kind; resolved through the kind's route resolver, site-provided for site-routed kinds |
| External URL | `[docs](https://...)` | left alone |

Front-matter references use the same typed form without the link wrapper:
`related: [wiki:a-b-testing, podcast:s24e01-...]`. Keys whose kind is fixed omit the prefix:
`authors: [16rahuljain]`, `instructors: [alexey-grigorev]`, `guests: [tatianagabruseva]` are person
references.

Rules.

- An unresolved reference fails the sync when `strict_references` is true (the default), otherwise
  the link is dropped, its label kept, and a warning recorded.
- Resolution happens at sync, against the rows already synced. A reference to a kind from another
  source therefore requires that source to be synced first; the engine orders sources by the
  declared kinds' dependencies (section 3.8, `depends_on`).
- `[[wikilinks]]`, `prev_url`, `next_url` and Liquid do not exist. Previous and next are derived
  from order.
- Heading fragments use the slug algorithm of section 4.1. Every heading id on a page is unique;
  the second `Setup` heading is `setup-1`, the third `setup-2`.
- The resolved references of a document are stored as a list of `{kind, target, label, href}` on
  the record.

Package ruling, what a stored reference holds: `kind` and `target` name the destination, `href` is
the route it resolved to, and `label` is the link text of a body reference and the empty string for
a front-matter one, which has no link wrapper. An external URL is left alone and is not recorded,
because it has no kind.

Package ruling, the route: `href` is `/` plus the kind's `route(path)`, or `/<kind>/<path>` when
the kind declares no route. A site whose public URLs differ, and a reference to a kind no
collection of this repository declares, both go through one seam: the toolkit takes a
`routes(kind, target)` callable, which answers with a route or with None. Without that callable a
reference to a kind another source owns is neither resolved nor reported, which is what lets
`check_content` run over one repository and still fail closed at sync.

## 3.8 Kind registry and kind schemas

The registry is `community_base.content_sync.kinds`. A kind declares: its name, the file shape
(`document`, `manifest`, `tree`, `data`), the kind keys with type, required flag and default, which
keys are asset references, which are typed references, the kinds it depends on, and a route
resolver. The package registers the shared kinds `course`, `article`, `person`, `wiki`, `docs` and
`data`; a site registers its own kinds with `register_kind(name, spec)` in `AppConfig.ready()`, the
same pattern as `register_parser`. A kind cannot alter the core; `extra` is the only site escape
hatch.

```python
from community_base.content_sync.kinds import KeySpec, KindSpec, register_kind
from community_base.content_sync.kinds.layouts import ItemDirectoryLayout

register_kind(
    "workshop",
    KindSpec(
        name="workshop",
        shape="manifest",
        layout=ItemDirectoryLayout(manifest_name="workshop.yaml"),
        keys={
            "instructors": KeySpec("reference_list", reference_kind="person"),
            "recording_url": KeySpec("url"),
        },
        asset_keys=("image",),
        requires_date=True,
        route=lambda path: f"workshops/{path}",
    ),
)
```

| Field | Type | Meaning |
|---|---|---|
| `name` | string | the kind name used in `content.yaml` and in `kind:` references |
| `shape` | `document`, `manifest`, `tree`, `data` | the primary file shape of the kind's items |
| `layout` | layout object | how files under the collection path become items; the package ships `FlatLayout`, `TreeLayout`, `ItemDirectoryLayout`, `DataLayout` and `CourseLayout` |
| `keys` | mapping of name to `KeySpec` | kind keys; a name that collides with a core key is refused at registration |
| `asset_keys` | tuple of key names | keys whose value is an asset reference; `image` is always one, except on a part that carries no core keys (the `data` kind), where an `image` key is opaque site data and not a path the engine resolves |
| `reference_keys` | derived from `keys` | keys whose value is a typed reference or a fixed-kind reference |
| `depends_on` | tuple of kind names | kinds whose rows must exist before this kind's references resolve |
| `requires_date` | boolean | whether `date` is required (and, when false, forbidden) by section 3.3 |
| `route` | callable | `(path) -> route`, the default route the package apps compute from an item path |
| `parts` | mapping of part name to `PartSpec` | for a composite kind such as `course`, the per-file schemas |

A `KeySpec` declares `type` (one of `string`, `text`, `markdown`, `integer`, `boolean`, `slug`,
`date`, `url`, `level`, `mapping`, `list`, `reference`, `reference_list`, `object_list`),
`required`, `default`, `max_length`, `choices`, `reference_kind` and `item_keys` for object lists.

Package ruling, kind dependencies: section 3.7 requires the engine to order sources by the declared
kinds' dependencies, and the design document's field list had no field to declare one. The registry
adds `depends_on`, a tuple of kind names, with these rules.

- A kind that declares no `depends_on` gets the fixed kinds named by its reference keys. The
  article kind, whose `authors` key is a person reference, therefore depends on `person` without
  saying so.
- An explicit `depends_on` replaces that derivation, because a kind whose body references are typed
  (`wiki:` links written inside a markdown body) cannot be inferred from its key list.
- `kind_order(names)` returns the registered kinds in dependency order, breaking ties by name so
  the order is stable between runs, and raises `KindDependencyError` naming the cycle when the
  declared graph has one. Ordering sources is then ordering their kinds.
- The declared graph covers front-matter references, which must resolve during the item's own
  upsert. A body reference to a kind in another source degrades through `strict_references` and
  does not need a declared dependency, which is what keeps the graph acyclic in practice.

The specifications below list kind keys only; core keys apply everywhere.

### course

Layout, with `<course>` the collection path (`.` for a single-course repository, or
`courses/<slug>/` in a multi-course one).

```
<course>/course.yaml
<course>/images/cover.jpg
<course>/NN-<module>/module.yaml
<course>/NN-<module>/README.md                    overview, optional
<course>/NN-<module>/NN-<unit>.md
<course>/NN-<module>/images/...                   assets
<course>/NN-<module>/code/...                     never synced, referenced by unit `code`
<course>/NN-<module>/NN-<submodule>/module.yaml   optional second level
<course>/NN-<module>/NN-<submodule>/NN-<unit>.md
<course>/cohorts/<identifier>/cohort.yaml
<course>/cohorts/<identifier>/README.md           cohort notes or archive notice, optional
<course>/cohorts/<identifier>/homework/<module-slug>/homework.yaml
<course>/cohorts/<identifier>/homework/<module-slug>/homework.md
<course>/cohorts/<identifier>/**                  anything else is opaque archive, ignored
```

A course repository carries notebooks, scripts and datasets beside its content. A file this layout
does not recognise is ignored rather than rejected; `ignore` in `content.yaml` exists for the ones
an author wants named. The other layouts are stricter, because their collections hold nothing but
authored content.

A course collection at `path: .` has no directory name to take a slug from, so its `course.yaml`
declares `slug` explicitly.

`course.yaml`

| Key | Type | Required | Default |
|---|---|---|---|
| `description` | markdown | yes | none |
| `instructors` | list of person references | no | `[]` |
| `default_unit_required_level` | level | no | inherits `required_level` |
| `outcome` | plain text, at most 300 | no | `""` |
| `prerequisites` | plain text, at most 1000 | no | `""` |
| `discussion_url` | https URL | no | `""` |
| `repository_url` | https URL | no | `""` |
| `docs_url` | https URL | no | `""` |
| `faq_url` | https URL | no | `""` |
| `hashtag` | `[A-Za-z0-9_]+` without `#` | no | `""` |
| `testimonials` | list of `{quote, name, role, source_url}` | no | `[]` |

AISL's `access_mode`, `enroll_url`, `program_label` and `maven_course_key` go under `extra` and
stay AISL-read (decision D29). DTC's `starting_point`, `progression` and `homework_summaries` go
under `extra` and stay DTC-read. `cohorts`, `current_cohort`, `urls`, `schema_version`,
`published`, `cover_image`, `cover_image_url`, `ignore` (moved to `content.yaml`) and
`instructor_name` do not exist.

`module.yaml`

| Key | Type | Required | Default |
|---|---|---|---|
| `is_bonus` | boolean | no | `false` |
| `available_after_days` | integer or null | no | `null` |

No `units` list, no `schema_version`, no `bonus`, no `ignore`. The overview is `README.md`.

Unit document `NN-<unit>.md`

| Key | Type | Required | Default |
|---|---|---|---|
| `kind` | `lesson`, `homework`, `event`, `checklist_item` | no | `lesson` |
| `video_url` | https URL | no | `""` |
| `timestamps` | list of `{time, title}`, `time` as `MM:SS` or `H:MM:SS` | no | `[]` |
| `session_position` | positive integer | when `kind: event` | `null` |
| `is_bonus` | boolean | no | `false` |
| `code` | list of `{label, path}` with `path` relative to the unit file | no | `[]` |

The body is the lesson. A `kind: homework` unit body is the instructions page; the gradable
assignment is the cohort's `homework.yaml`. `is_homework`, `is_preview`, `access`, `prev_url` and
`next_url` do not exist.

`cohorts/<identifier>/cohort.yaml`. The identifier is the directory name and is not repeated inside
the file. It follows the slug pattern (`2026`, `self-paced`, `4`).

| Key | Type | Required | Default |
|---|---|---|---|
| `delivery` | `live` or `self_paced` | yes | none |
| `start_date`, `end_date` | ISO dates | when `delivery: live` and `status: published` | `null` |
| `modules` | ordered list of top-level module slugs | no | absent means the full course tree in module order |
| `archive` | boolean | no | `false`; `true` means the cohort places no modules and points GitHub readers at its own directory |
| `registration_url` | https URL | no | `""` |
| `hashtag` | as course | no | `""` |
| `homework` | list of `{module, source, unit}` | no | `[]` |

`homework[].module` is a top-level module slug that the cohort places; `homework[].source` is the
manifest path relative to the cohort directory (`homework/01-agentic-rag/homework.yaml`);
`homework[].unit` is the optional `content_id` of a `kind: homework` unit whose page shows the
submission form. `title` defaults to `<course title> <identifier>`. `identifier`, `course`,
`published`, `legacy_slug`, `year`, `format` and `flow` do not exist.

`homework/<module-slug>/homework.yaml` keeps the DTC manifest: core keys plus `instructions_path`
(default `homework.md`), `due_at` (ISO datetime with offset), `initial_state` (`closed`, `open`,
`scored`), `form` (`homework_url`, `time_spent_lectures`, `time_spent_homework`,
`faq_contribution`, `learning_in_public_cap`) and `questions` (each with `content_id`, `id`,
`type`, `prompt`, `points`, `options`, `answer_type`, and the encrypted `answer` envelope of
`coursework/answer_crypto.py`). Plaintext answers in unit front matter do not exist; answers are
always the envelope.

### article

```
articles/<slug>/index.md
articles/<slug>/images/...
```

| Key | Type | Required | Default |
|---|---|---|---|
| `date` | ISO date | yes | none |
| `authors` | list of person references | no | `[]` |
| `byline` | plain text | no | `""`; display text when no person record exists |
| `subtitle` | plain text, at most 300 | no | `""` |
| `related` | list of typed references | no | `[]` |
| `faq` | list of `{question, answer}` with markdown answers | no | `[]` |

Storage stays site-owned (decision D21): the AISL parser fills its own article model, the DTC
parser fills `SyncedDocument`. Both read this one shape.

### person

```
people/<id>.md
people/images/<id>.jpg
```

`title` is the display name, `summary` the short bio, `image` the picture, the body the long bio.

| Key | Type | Required | Default |
|---|---|---|---|
| `links` | list of `{label, url}`, `label` one of `website`, `linkedin`, `github`, `x`, `youtube`, `other` | no | `[]` |

`short`, `picture`, `bio_short`, `layout` and `photo_url` do not exist. Decision D31 makes the kind
an optional instructor source, not a required one.

### wiki

```
wiki/<slug>.md
wiki/images/...
```

| Key | Type | Required | Default |
|---|---|---|---|
| `related` | list of typed references | no | `[]` |
| `page_type` | slug | no | `""`; a site-defined template selector |

Stored per page: rendered HTML, the heading list and the resolved references. DTC's `keyword`,
`secondary_keywords`, `seo_title`, `search_intent` and `related_wiki` go under `extra`.

### docs

```
docs/index.md
docs/NN-<section>/index.md
docs/NN-<section>/NN-<page>.md
docs/NN-<section>/NN-<subsection>/index.md
docs/images/...
```

| Key | Type | Required | Default |
|---|---|---|---|
| `toc` | boolean | no | `true` |

The tree is the directory tree. The page key in `knowledge_base` is `(section, parent, slug)` and
the stored path is the directory chain. Repeated leaf slugs under different parents are legal.
`parent`, `grand_parent`, `nav_order`, `has_children`, `has_toc`, `permalink` and `layout` do not
exist.

### data

```
data/<name>.yaml or data/<name>.json
```

One opaque record per file, keyed by its path below the collection root without the extension, so
a generated artefact may sit in a subdirectory (`graph/graph.json`) and keep a distinct key. The
parsed content is carried untouched: no core keys are required, no key is rejected, and a top-level
list is as acceptable as a mapping. The package stores it; a site parser interprets it. This
carries `tiers.yaml`, `podcast-platforms.yaml`, `slack.yaml`, `graph.json` and `search-corpus.json`
(decision D27).

### Site-registered kinds

A kind that only one site has obeys sections 3.2 to 3.7 and keeps a site-owned schema registered
from that site's `AppConfig.ready()`: `workshop`, `project`, `curated_link`, `interview_question`,
`podcast`, `book`, `faq` and the private member wiki. Decision D26 keeps the FAQ repository on its
current file shape behind a site-registered `faq` kind.

## 3.9 Worked examples

`content.yaml` of a single-course repository

```yaml
schema_version: 1
collections:
  - kind: course
    path: .
ignore:
  - "**/code/**"
  - "etc/**"
```

`course.yaml`

```yaml
content_id: "e79727f3-f540-4176-ae98-9b9cb42abdc7"
title: LLM Zoomcamp
slug: llm-zoomcamp
summary: Build, evaluate and monitor production-style LLM applications.
image: images/llm-zoomcamp.jpg
tags: [llm, rag, agents]
description: |
  LLM Zoomcamp is a free, hands-on course on building real-world applications with
  Large Language Models.
outcome: Build, evaluate, and monitor production-style LLM applications.
repository_url: https://github.com/DataTalksClub/llm-zoomcamp
hashtag: llmzoomcamp
instructors: [alexeygrigorev]
extra:
  starting_point: You want to turn questions over your own documents into an application.
```

`01-agentic-rag/module.yaml`

```yaml
content_id: "d9ca5cb3-b94c-4281-be7d-a2462559f02b"
title: "Module 1: Agentic RAG"
summary: Build an agentic RAG assistant over a course FAQ dataset.
```

`01-agentic-rag/01-intro.md`

```markdown
---
content_id: "1e8059d3-1c63-47f6-b0a1-9b21c96ca1c6"
title: Introduction
video_url: https://www.youtube.com/watch?v=rQYyFxf1FWw
---

In this module, we'll build a working Retrieval-Augmented Generation (RAG)
system from scratch, step by step.

Before you start, read the [course logistics](docs:courses/zoomcamp-logistics)
and the [environment page](02-environment.md).

![Overview of the course RAG project](images/01-intro-01-rag-project-overview.png)
```

`cohorts/2026/cohort.yaml`

```yaml
content_id: "0ea85a46-bd6b-4f21-82fe-317954d8be32"
title: LLM Zoomcamp 2026
delivery: live
start_date: "2026-08-24"
end_date: "2026-10-12"
homework:
  - module: agentic-rag
    source: homework/01-agentic-rag/homework.yaml
```

`articles/crisp-dm-for-ai/index.md`

```markdown
---
content_id: "6bc9da15-7603-46ee-901d-096fdebf5764"
title: "CRISP-DM for AI Engineering"
summary: See how CRISP-DM still guides AI engineers in 2026.
date: 2026-03-11
authors: [alexey-grigorev]
tags: [ai-engineering, crisp-dm]
image: images/cover.jpg
---

During AI development, teams work with large language models.
```

`people/16rahuljain.md`

```markdown
---
content_id: "d7e8f9a0-b1c2-4d3e-8f4a-5b6c7d8e9f0a"
title: Rahul Jain
summary: Data engineering manager with over 12 years of experience.
image: images/16rahuljain.jpg
links:
  - {label: linkedin, url: https://www.linkedin.com/in/16rahuljain/}
---

Rahul Jain is a data engineering manager.
```

## 3.10 Validation

The package ships the validator twice over one implementation:

```text
uv run python -m community_base.content_sync.check <path>
uv run python manage.py check_content <path>
```

The module form runs with the package kinds alone. A content repository whose CI checks a
site-registered kind passes `--kinds <dotted.module>`, repeatable, and the module registers its
kinds the way `AppConfig.ready()` does. The management command needs no flag: the site's apps have
already registered them.

Both call `community_base.content_sync.check.run_check`, which does the work and writes the report;
the module entry point turns its return value into a process exit code and the management command
turns it into a `CommandError`. There is no second implementation to drift.

The validator needs no database and no site. It reads `content.yaml`, walks every collection with
its kind's layout, and checks file shapes, naming and ordering prefixes, core and kind keys,
identity uniqueness, nesting, assets, in-repository references and the dialect rules of section
4.1.

Every diagnostic carries the repository-relative path of the file it is about, a YAML pointer into
that file, and the rule number:

```text
articles/no-id/index.md:/content_id: [3.3] required key content_id is missing
content.yaml:/collections/1/kind: [3.1] unknown kind: article-draft
wiki/liquid.md:12:/body: [4.1] Liquid expression is not part of the dialect: {% include x.html %}
```

A pointer of `/body` names the markdown body and carries the one-based line number before it. The
process exits 1 when any error was reported, and 0 when only warnings were.

## 4.1 The dialect

- CommonMark as python-markdown implements it, plus `tables`, `fenced_code` and `sane_lists`.
  `attr_list` and `md_in_html` are not enabled.
- Fenced code blocks render to `<pre><code class="language-x">`. No server-side highlighting in the
  package. A site may add `codehilite` through the extension hook of section 4.2.
- A fenced block with info string `mermaid` renders to `<pre class="mermaid">` with the source
  escaped; the site's JavaScript draws it.
- A fenced block with info string `embed` whose body is a YAML mapping `{type, id}` with `type` in
  `youtube`, `loom` renders to a `div.cb-embed` carrying `data-embed-type` and `data-embed-id` and
  containing a plain link to the video. The site hydrates it. This keeps iframes out of stored
  HTML.
- Raw HTML is allowed and passes through the sanitiser. `<figure>`, `<figcaption>`, `<details>`,
  `<summary>`, `<img>` and `<table>` survive; `style` attributes, `<script>`, `<style>`, `<iframe>`
  and event handlers do not.
- Liquid (`{% %}`, `{{ }}`) and kramdown attribute lists (`{: .class }`) are errors outside fenced
  and inline code. Inside code they are text.
- `[[wikilinks]]` and `{IMAGE:id}` tokens are errors.
- A leading H1 equal to the title is stripped by the renderer; writing one is a warning.
- Heading ids are injected after rendering, with the DataTalks.Club algorithm: NFKD, ASCII,
  lowercase, non-alphanumerics to `-`, an empty result becoming `section`, and a repeat of an id
  suffixed by the number of times it was already seen, so a second `Setup` is `setup-1` and a third
  `setup-2`; the heading list `{level, id, title}` is returned and stored.
- The design document stated both suffix styles, `-1`, `-2` in its section 4.1 and `-2`, `-3` in
  its section 3.7. The donor is the authority, because the point of keeping the algorithm is that
  the pinned DataTalks.Club fragment contracts keep resolving, and the donor
  (`content/docs_projection.py`) counts from zero and suffixes `-1` first. That is the rule here.
- `~~strikethrough~~` has no python-markdown built-in; the validator warns and the conversion
  writes `<del>`.
- Links are resolved and images rewritten after rendering and before sanitising; section 3.6
  owns that order and says why the design document's "before rendering" cannot hold.
- Plain text for search is derived from the rendered HTML by the package.

## 4.2 Where rendering lives and who owns what

- `community_base/content_sync/rendering.py` owns `render_document`, `inject_heading_ids`,
  `sanitize_rendered_html` and `plain_text`. `curriculum/rendering.py` and
  `knowledge_base/rendering.py` become thin imports of it. This is issue C7.8; C7.7 ships the rule,
  not the module.
- Rendering runs in the sync job through the parser toolkit, never in a model `save()`. The page
  and unit models store `body_html` as supplied.

  This rule governs the synced path only. A model still renders markdown in `save()` for content a
  human authors in Studio, because such content reaches no parser and has no other renderer;
  removing the fallback would store empty HTML for every Studio-authored unit and page. A parser
  signals that it has already rendered by setting `body_html_source`, and `save()` then sanitises
  and stores what it was given rather than re-rendering the markdown body.
- Sanitisation is package-owned and always last, over one nh3 allowlist, plus the attributes the
  shared extensions emit: `class` on `div`, `pre`, `code`, `span` and `img`; `data-embed-type` and
  `data-embed-id` on `div`; `data-theme-figure` on `img`.

  `class` is admitted on every allowed tag through the allowlist's `*` entry, so the per-tag list
  above describes where the shared extensions emit it, not where it is permitted.
- Sites extend, they do not replace: `COMMUNITY_BASE["MARKDOWN_EXTENSIONS"]` is a list of dotted
  paths appended to the package list. An extension's output still passes the package sanitiser, so
  an extension that needs a new attribute needs a package change to the allowlist.

## 4.3 What breaks

| Break | Handling |
|---|---|
| Inline `style` on `<img>` | stripped by the sanitiser; the conversion removes `style` and keeps `width` and `loading`; the validator warns |
| kramdown `{: .fs-9 }` | an error; the site's stylesheet styles the hooks instead |
| Liquid includes | an error; `youtube.html` becomes an `embed` fence and `related-posts` becomes `related:` front matter |
| Raw HTML block followed by markdown on the next line | the conversion inserts a blank line after `</figure>` and `</table>` |
| Server-side code highlighting | `codehilite` registered through the extension hook, unchanged output |
| mistune `strikethrough` | the validator warns; the conversion rewrites to `<del>` |
| Heading id suffix style | one algorithm: a repeated `Setup` heading is `setup-1`, then `setup-2` |
| A site's article `blocks` projection | article storage is site-owned under decision D21; issue D7.2 decides whether DataTalks.Club keeps deriving blocks from this source or renders the body once. Not decided here. |

## 5 Not yet implemented

C7.7 shipped this document, the kind registry and the validator; C7.8 the renderer and the
sanitiser; C7.9a the reading half of the toolkit; C7.9b its resolving half, which is assets,
cross-references, source ordering and `theme_pairs`. The rest of the chain is named here so a
reader does not mistake a rule for shipped behaviour.

| Rule | Issue that implements it |
|---|---|
| Package parsers for `wiki`, `docs` and `person`, and the `source_content_id` repair with its migration | C7.9c |
| One course parser over this format | C7.10 |
| The `homework.yaml` reader | C7.11 |
| Per-repository conversion | C7.12, A7.3, D7.4 |
