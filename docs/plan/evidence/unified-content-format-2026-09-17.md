# Unified content format for the DataTalks.Club sites

Date: 2026-09-17. Design document, no code. Read-only analysis of `community-base`,
`DataTalksClub/website` (`~/git/dtc-website`), `AI-Shipping-Labs/website`
(`~/git/ai-shipping-labs`) and sixteen content repositories cloned under `~/git`. File and
line citations are against the working trees on that date; a content repository whose local
checkout was not on `main` is cited against `origin/main` and marked as such.

Subsumes GitHub issue `DataTalksClub/community-base#253` (one content format and one importer
across both sites). Section 8 states how.

Constraint taken from the owner: no backwards compatibility. Every content file may be rewritten.
There are no shims, dual readers, version negotiation or migration windows in this design.

Contents

1. What is synced today: the inventory
2. Divergence analysis: same idea, different expression, versus genuinely different ideas
3. The specification
4. Rendering: one markdown dialect
5. Conversion cost per content repository
6. Findings that change the plan's assumptions
7. Proposed issues
8. How this subsumes issue 253
9. Open questions for the owner

## 1. Inventory

### 1.1 Sources

| Site | Source slug | Repository | Declared in | Files | Kinds read from it |
|---|---|---|---|---|---|
| DTC | `dtc-content` | `DataTalksClub/content` | `website/settings/base.py:439-445` | 1,406 | article, book, podcast, media, podcast_platforms, slack_page |
| DTC | `dtc-main-site` | `DataTalksClub/datatalksclub.github.io` | `website/settings/base.py:446-451` | 2,655 | people, media (profile pictures) |
| DTC | `dtc-docs` | `DataTalksClub/docs` | `website/settings/base.py:452-457` | 286 | docs |
| DTC | `dtc-faq` | `DataTalksClub/faq` | `website/settings/base.py:458-463` | 1,619 | faq |
| DTC | `dtc-podwiki` | `DataTalksClub/podwiki` | `website/settings/base.py:464-469` | 1,768 | wiki, wiki_graph, wiki_search, wiki_assets |
| DTC | six course slugs | `DataTalksClub/{ai-dev-tools,data-engineering,llm,machine-learning,mlops,stock-markets-analytics}-zoomcamp` | `content_sync/course_repository_sources.json` | 241 to 1,784 | course (catalogue copy); curriculum through DTC `courses/services/curriculum_import.py`, not through the package |
| AISL | `content` | `AI-Shipping-Labs/content` | `integrations/management/commands/seed_content_sources.py:16-22` | 269 | article, project, event, curated_link, interview_question, tier, wiki_pages, docs_pages, course (aihero) |
| AISL | `python-course` | `AI-Shipping-Labs/python-course` | same file, lines 23-28 | 143 | course |
| AISL | `workshops-content` | `AI-Shipping-Labs/workshops-content` | same file, lines 29-34 | 433 | workshop |
| AISL | `ai-buildcamp-course` | `AI-Shipping-Labs/ai-buildcamp-course` | same file, lines 35-40 | 896 | course |
| AISL | `wiki` | `AI-Shipping-Labs/wiki` | same file, lines 41-48 | 115 | wiki_topics (site `topics` app, private member wiki) |

Two DTC parsers publish nothing today because their source files do not exist:
`content/sync_parsers/platforms.py:41` reads `podcast-platforms.yaml` and
`content/sync_parsers/slack.py:38` reads `slack.yaml` at the `DataTalksClub/content` root, and
`git ls-files` of that repository lists neither. The DTC course-catalogue parser
(`content/sync_parsers/course.py:75-79`) reads a `catalog:` block from each course `course.yaml`;
none of the six live manifests carries one. Both are recorded here so the inventory is not
mistaken for the set of rows the sites actually publish.

The AISL classifier (`content/sync_parsers/families/classify.py:95-283`) also recognises
`instructors/*.yaml`, `downloads/*.yaml` and markdown with `content_type: marketing_page`.
No file of any of those three shapes exists in any AISL content repository at `origin/main`;
those families run against nothing today.

### 1.2 Content kinds, per site

Columns: identity is the upsert key; nesting is how a tree is expressed; ordering is how sibling
order is expressed; assets is how images are referenced from the source file. `fm` means YAML
front matter; `manifest` means a standalone YAML file.

DataTalks.Club. Every kind is written into one generic row, `content.SyncedDocument`
(`content/models.py:738-793`), keyed `(source, content_kind, stable_key)` with the kind-specific
shape in the opaque `record` JSON. No `content_id` exists outside the course repositories.

| Kind | On-disk layout (real file) | Metadata keys read | Identity | Nesting | Ordering | Assets | Parser |
|---|---|---|---|---|---|---|---|
| article | `articles/2025/25-02-26-building-ai-agent-that-thrives-in-real-world.md`, fm plus markdown body with literal `<figure><img>` HTML and Liquid `{% include %}` | `title`, `subtitle`, `description`, `date` or `datepublished`, `authors` (person keys), `tags`, `image`, `layout`, `faq`, `related_posts`, `charts`, `math` | slug = filename stem after the `YY-MM-DD-` or `YYYY-MM-DD-` prefix (`articles.py:26,71-74`) | none | `date` | site-absolute `/images/posts/<date-slug>/x.jpg` in raw HTML; `image:` is a repo-relative path under `images/posts/` | `content/sync_parsers/articles.py` |
| book | `books/2024/24-01-15-distributed-machine-learning-patterns.yaml`, manifest only | `slug`, `legacy_path` (must equal `/books/<slug>.html`), `title`, `authors`, `description`, `summary`, `start`, `end`, `links[{text,link}]`, `archive[]`, `image`, `cover` | `slug` key | none | `start` date | repo-relative `images/books/<slug>/cover.jpg` | `books.py` |
| podcast | `podcasts/s24/e01.yaml` plus sibling `e01-transcript.yaml`; pre-reorg layout `podcasts/transcripts/<slug>.yaml` still accepted (`podcasts.py:150-158`) | `slug`, `legacy_path`, `season`, `episode`, `guests` (person keys), `ids`, `links{platform:url}`, `short`, `title`, `description` or `intro`, `dateadded`, `transcript`, `resources[]`, `topics`, `duration` | `slug` key; public path derived from season and episode (`content/podcast_routes.py:19-25`) | none | season, episode | repo-relative `images/podcast/<slug>.jpg` | `podcasts.py` |
| people | `_people/16rahuljain.md` in the Jekyll main-site repository, fm plus body | allowlist `short`, `title`, `picture`, `bio_short`, `linkedin`, `github`, `twitter`, `web`, `layout` (`people.py:28-38`) | `short` must equal the filename stem (`people.py:118-120`) | none | none | `picture:` must match `images/authors/<name>.<ext>` (`people.py:39`) | `people.py` |
| media | every file under `images/{posts,podcast,books}/` whether referenced or not, plus one picture per person | none | repo path | none | none | is the asset | `media.py:22-27,131-140` |
| docs | Jekyll just-the-docs pages: `courses/llm-zoomcamp/index.md`, `courses/llm-zoomcamp/project.md`, roots `activities/`, `courses/`, `general/`, `touch/` and `index.md` (`docs.py:23,137-148`) | `title`, `description`, `parent` (a page title), `grand_parent`, `nav_order`, `has_children`, `toc`, `permalink`, `layout` | slash path: path parts without extension, `index` dropped (`docs.py:175-179`) | `parent:` by title, resolved in `discover` (`docs.py:66-77`); 25 of 106 pages name a sibling page, not their directory index, as parent (measured in section 6) | `nav_order` | Liquid `{{ '/assets/images/x.png' | relative_url }}` unwrapped (`docs.py:29-36`), or relative | `docs.py` |
| faq | `_questions/llm-zoomcamp/_metadata.yaml` (course, sections order) plus `_questions/llm-zoomcamp/general/001_74eb249bbf_i-just-discovered-the-course-can-i-still-join.md` | metadata: `course`, `course_name`, `slack_channel`, `telegram_channel`, `sections[{id,name,comment}]`; question fm: `id` (ten base62 chars, `content/faq_data.py:45`), `question`, `sort_order`, `images[{id,description,path}]` | one document per course keyed by course directory; questions keyed by `id` inside the record | course, section, question: directories | `sort_order` then filename | declared `images:` list plus `{IMAGE:id}` tokens in the body (`faq_data.py:46-48`) | `faq.py` |
| wiki | `_wiki/a-a-testing.md`, fm plus markdown with `[[event tracking]]`, `[[a-b-testing=>A/B testing]]`, `[[cite:episode=>label]]`, `[[person:key]]` tokens | `title`, `summary`, `layout` (`wiki` 202 pages, `article` 81 pages), `related` (titles), `tags`, `keyword`, `related_wiki`, `secondary_keywords`, `seo_title`, `search_intent` | filename stem (`podwiki.py:118`) | none | title A to Z | none in pages; three PNG assets declared in code (`builder.WIKI_PUBLIC_ASSETS`) | `podwiki.py` |
| wiki_graph, wiki_search, wiki_assets | `graph/graph.json`, `search/search-corpus.json` generated by the repository's own scripts (`scripts/build_graph.py`, `build_search_index.py`); node counts include podcasts 206, persons 442, books 99, events 212 | allowlisted node and document fields (`podwiki.py:70-97`) | singleton kinds | none | none | none | `podwiki.py:300-372` |
| podcast_platforms, slack_page | `podcast-platforms.yaml`, `slack.yaml` at the repository root (absent today) | `platforms[{provider,label,url,dot}]`; `title`, `lead`, `channels`, `troubleshooting_url` | singleton | none | list order | none | `platforms.py`, `slack.py` |
| course (catalogue copy) | `catalog:` block of a course repository's `course.yaml` (absent today) | `slug`, `title`, `finished`, `homework_count`, `project_count`, deadlines | edition slug | none | none | none | `course.py` |

DataTalks.Club curriculum is imported by the site's own `courses` app, not by the package. The
live shape is schema 2 (`~/git/llm-zoomcamp/course.yaml:1`, `data-engineering-zoomcamp`,
`machine-learning-zoomcamp`, `mlops-zoomcamp`, `ai-dev-tools-zoomcamp`), with
`stock-markets-analytics-zoomcamp` still schema 1 and holding no module at all.

| Piece | Real file | Keys | Identity | Nesting | Ordering | Assets |
|---|---|---|---|---|---|---|
| course | `llm-zoomcamp/course.yaml` | `schema_version: 2`, `content_id`, `slug`, `title`, `current_cohort`, `cohorts[{identifier, content: root or cohorts/<id>, legacy}]`, `description` (inline markdown), `outcome`, `starting_point`, `prerequisites`, `progression[{heading,description}]`, `urls{repository,docs,faq}`, `hashtag`, `published` | `content_id` | one course per repository root | none | `images/` at the root |
| module | `llm-zoomcamp/01-agentic-rag/module.yaml` | `schema_version`, `content_id`, `title`, `summary`, `units[{content_id,title,path}]` | `content_id`; slug = directory name minus `NN-` | flat: no submodule exists in any repository; DTC's design proposal keeps folders flat and nests `sub_modules:` inside `module.yaml` (`_docs/planning/shared-curriculum-submodules-design.md:336-435`) | `NN-` directory prefix | `01-agentic-rag/images/01-intro-01-...png`, referenced relatively from lessons; `code/` sibling |
| unit | `llm-zoomcamp/01-agentic-rag/01-intro.md` | fm `video_url`, `prev_url`, `next_url`, `code` (71 files carry `prev_url`/`next_url`, 55 `video_url`, 5 `code`) | `content_id` from the module manifest; slug = file stem | none | position in the manifest list | relative `images/...` |
| module overview | `01-agentic-rag/README.md` | none, plain markdown | none | none | none | relative |
| cohort | `llm-zoomcamp/cohorts/2026/cohort.yaml` | `schema_version`, `content_id`, `identifier`, `course`, `delivery` (`live`, `self_paced`), `published`, `start_date`, `end_date`, `curriculum` (`current`, `github_archive`), `archive{notice_path}`, `homework[{module,source}]` | `content_id`; directory name equals `identifier` | `cohorts/<identifier>/` | none | archive cohorts keep whole old trees under their directory (`cohorts/2025/01-intro/...`) |
| homework | `cohorts/2026/homework/01-agentic-rag/homework.yaml` plus `homework.md` | `schema_version`, `content_id`, `slug`, `title`, `instructions_path`, `due_at`, `initial_state`, `form{}`, `questions[{content_id,id,type,options,prompt,points,answer_type,answer{envelope}}]` with encrypted answers | `content_id` | bound from `cohort.yaml` | list order | none |

AI Shipping Labs. Every kind has a concrete model with real `save()` logic and Studio editing;
the article model alone has about twenty fields (`content/models/article.py:35-106`). Every
markdown file carries a `content_id` (`content/sync_parsers/common.py:15-33` lists the required
fields per family; the classifier routes files by directory name and front-matter sniffing,
`classify.py:181-283`).

| Kind | On-disk layout (real file) | Metadata keys read | Identity | Nesting | Ordering | Assets | Parser |
|---|---|---|---|---|---|---|---|
| course | `ai-buildcamp-course/course.yaml` at the repository root (also `python-course`); `content/courses/aihero/course.yaml` nested in the content repository | `content_id`, `slug`, `title`, `description`, `cover_image` or `cover_image_url`, `instructors` (ids), `required_level`, `default_unit_access`, `access_mode`, `enroll_url`, `program_label`, `maven_course_key`, `cohorts[{key,name,start_date,end_date,mode}]`, `tags`, `testimonials`, `discussion_url`, `ignore` (globs) | `content_id` | course directory, module directories, optional submodule directories (max two module levels), `_docs/course_yaml.md:15-45` | `NN-` prefix or `sort_order` | `images/cover.jpg` relative to `course.yaml`; unit images relative, rewritten to the CDN at sync (`content/sync_parsers/media.py:107-160`) | `families/courses.py` |
| module | `ai-buildcamp-course/01-foundations-llms-rag-and-structured-output/module.yaml` | `content_id`, `title`, `slug`, `sort_order`, `bonus`, `available_after_days`, `ignore` | `content_id`; slug from directory minus `NN-` | directory | `NN-` prefix or `sort_order` | `README.md` is the overview, never a unit (`courses.py:842-844`) | same |
| unit | `.../04-foundation-llms-rag-and-search/01-section-overview.md` | fm `content_id`, `title`, `sort_order`, `video_url`, `timestamps`, `access`, `is_preview`, `kind` (`lesson`, `homework`, `event`), `session_position`, `is_bonus`, `is_homework`, plus `questions` and `due_date` on gradable homework (`_docs/course_yaml.md:195-235`); counts on the restructure branch: 210 `content_id`, 205 `sort_order`, 112 `is_bonus`, 108 `video_url`, 18 `kind`, 8 `session_position` | `content_id` in the file | file inside the leaf module directory | `NN-` prefix or `sort_order` | relative | same |
| workshop | `workshops-content/2026/06/2026-06-02-serving-open-models-vllm-runpod/workshop.yaml` plus `01-overview.md` ... `10-qa.md`, `README.md`, `images/` | manifest `content_id`, `slug`, `date`, `title`, `instructor_name`, `pages_required_level`, `landing_required_level`, `tags`, `code_repo_url`, `recording{url,embed_url,required_level,timestamps[],materials[]}`, `event_slug`, `cover_image_url`, `copy_file`; page fm `content_id`, `title`, `sort_order`, `video_start` (258 pages; `_docs/03-04-frontmatter.md`) | `content_id`; `slug` from the manifest, not the directory | workshop directory; pages flat inside it | `NN-` prefix | relative `images/request-path.svg` with `.dark.svg` sibling pairing; README is the landing description | `families/workshops.py` |
| article | `content/blog/crisp-dm-for-ai/crisp-dm-for-ai.md` with `images/` sibling (22 posts at `origin/main`) | `content_id`, `title`, `slug`, `description`, `date`, `author` (free text, may list two names), `tags`, `cover_image`, `cover_image_url`, `status`, `required_level`, `page_type`, `data` | `content_id`; slug from fm or filename | directory per article | `date` | relative `images/cover.jpg` | `families/articles.py` |
| project | `content/projects/ai-data-cleaning-assistant/ai-data-cleaning-assistant.md` | `content_id`, `title`, `slug`, `description`, `date`, `author`, `difficulty`, `tags`, `cover_image`, `demo_url`, `source_code_url`, `required_level` | `content_id` | directory per project | `date` | relative | `families/projects.py` |
| event | `content/events/community-launch.yaml` plus `events/community-launch/recap.md` and HTML partials | `content_id`, `slug`, `title`, `event_type`, `status`, `start_datetime`, `end_datetime`, `location`, `tags`, `required_level`, `speaker_name`, `recording_url`, `timestamps[{time_seconds,label}]`, `recap_file`, `description`, `cover_image` | `content_id` | none | `start_datetime` | relative to the events directory | `families/events.py` |
| curated_link | `content/curated-links/a-day-of-an-ai-engineer-talk-materials.md` | `content_id` (a slug, not a UUID), `title`, `url`, `tags`, `date`, `required_level`, `category`, `published`, `sort_order` | `item_id` or `content_id` | none | `sort_order` | none | `families/curated_links.py` |
| interview_question | `content/interview-questions/theory.md`, fm carries the whole question tree | `content_id`, `title`, `description`, `sections[{id,intro,qa[{question}]}]`, `status` | `content_id` | sections inside one file | list order | none | `families/interview_questions.py` |
| tier | `content/tiers.yaml` | `name`, `stripe_key`, `level`, prices, `benefits[]` | `stripe_key` | none | list order | none | `families/tiers.py` |
| wiki page | `content/wiki/ai-engineering-glossary.md` (`origin/main`, 2 pages) | `content_id`, `title`, `summary` | package `KnowledgeBasePage.slug` = file stem | none | title | relative, rewritten | `families/knowledge_base.py` |
| docs page | `content/docs/taking-courses.md` (`origin/main`, 7 pages) | `content_id`, `title`, `summary`, `parent` (a slug), `nav_order` | slug = file stem, no directories | `parent:` by slug | `nav_order` | relative | same |
| member wiki topic | `AI-Shipping-Labs/wiki/_wiki/rag.md` (private, 19 pages) | `title`, `summary`, `related` (slugs), `topics`, `layout` | file stem | none | title | none | `families/member_wiki.py`, site `topics` app |

Package. `community_base.curriculum` carries two parsers for two course layouts
(`parsers_aisl.py`, `parsers_dtc.py`), both producing `curriculum/source.py:ParsedCurriculum`.
`community_base.knowledge_base` stores pages keyed `(section, slug)` with `parent` and
`nav_order` (`knowledge_base/models.py:56-80`). Provenance is
`content_sync/provenance.py:SourceProvenanceMixin`: `source_content_id`, `source_path`,
`source_commit_sha`, `source_checksum`, all-or-nothing.

### 1.3 Markdown dialects in use

| Where | Renderer | Preprocessing | Sanitiser | Heading ids | Citation |
|---|---|---|---|---|---|
| DTC docs | mistune, plugins `strikethrough`, `table`, `escape=False` | strip kramdown `{: ... }` attribute lines and inline attributes; rewrite Liquid `relative_url`; rewrite markdown links | bleach allowlist, `content/services.py:145-235` | injected after rendering, NFKD ascii slug, `-N` dedupe, returned as TOC metadata | `content/docs_projection.py:60-67,111-139,376-382,431-446` |
| DTC articles | source split into a JSON block list; per-block `markdown` rendered by mistune at request time | Liquid stripped | same bleach allowlist | in the block list (`_slugify`, `-N` dedupe) | `scripts/build_public_projection.py:1208-1360`, `content/article_content.py:75-99` |
| DTC wiki and people | no HTML: plain-text `blocks` of `heading`, `paragraph`, `list_item`; `[[tokens]]` become `relations` | none | not applicable | in the block list; every search-corpus fragment must resolve uniquely or the sync fails | `build_public_projection.py:649-700,2108-2150`, `podwiki.py:380-395` |
| DTC faq | raw question markdown stored, rendered at request time | `{IMAGE:id}` token substitution | same | none | `faq.py:9-13`, `content/faq_data.py` |
| AISL | python-markdown with `fenced_code`, `tables`, `codehilite`, `toc` and site extensions `MermaidExtension`, `ExternalLinksExtension`, `EventWidgetExtension`; inline-bullet normalisation and URL linkify passes | image URL rewriting to the CDN, sibling page link rewriting (workshops) | nh3 allowlist, `content/utils/markdown.py:26-50` | python-markdown `toc` defaults | `content/utils/markdown.py:1-100`, `content/models/workshop.py:376,610` |
| package curriculum | python-markdown `fenced_code`, `tables`, `sane_lists` | none | nh3 allowlist, narrower than the knowledge base one | none | `curriculum/rendering.py:1-60` |
| package knowledge base | python-markdown, same extensions | strip a leading H1 equal to the title | nh3, DTC's allowlist lifted plus absolute `img src` | none | `knowledge_base/rendering.py:1-30,150-192` |

## 2. Divergence analysis

The test applied to every row: two expressions converge only when a single reader could serve
both sites with one meaning. Where the meanings differ, the concepts stay distinct even if the
key names happen to match.

### 2.1 Same idea, different expression: these converge

| Idea | DTC expression | AISL expression | Package today | Convergent form (section 3) |
|---|---|---|---|---|
| Stable item identity | `content_id` UUID in course manifests only; slug or path elsewhere | `content_id` on every file; a slug in curated links | provenance `source_content_id` | `content_id` UUID required on every item of every kind |
| Where an item's metadata lives | module `units:` list names each lesson's `content_id`, `title`, `path`; lesson files carry only `video_url`, `prev_url`, `next_url`, `code` | every file carries its own front matter | both parsers | front matter in the file; a manifest lists no children |
| Sibling order | `nav_order` (docs), `sort_order` (faq), manifest list order (lessons), `NN-` prefix (modules), `NNN_` prefix (faq files) | `NN-` prefix, `sort_order` override | `NN-` prefix, `sort_order` override | `NN-` prefix on the file or directory name, `sort_order` override in front matter |
| Tree parent | `parent:` by page title (docs), directory (faq) | `parent:` by slug (docs), directory (courses) | `parent` FK resolved by slug | the directory tree, nothing else |
| Cohort declaration | `cohorts/<id>/cohort.yaml` plus a duplicate `cohorts:` list and `current_cohort` in `course.yaml` | inline `cohorts:` list in `course.yaml` | AISL inline, DTC directories | `cohorts/<identifier>/cohort.yaml` only |
| Course description source | `SITE.md` (schema 1), inline `description` (schema 2) | inline `description`, else `README.md` | both | inline `description`; `README.md` is never read at course level |
| Module overview | `README.md` beside `module.yaml` (`overview_markdown`) | `README.md` beside `module.yaml` (`overview`) | both | unchanged, `README.md` is the overview |
| Schema versioning | `schema_version` on every manifest | none | DTC parser demands it | once, in the repository `content.yaml` |
| Access gate | `published` boolean | `required_level` integer or name, `access`, `is_preview` | `required_level` integer (D5) | `required_level` integer or name; `status` for visibility |
| Homework page flag | `kind` on the manifest unit entry | `kind: homework` or `is_homework: true` | `kind` with a legacy alias | `kind` only |
| Bonus flag | `is_bonus` on manifest entries | `bonus` (module.yaml) and `is_bonus` (unit) | `is_bonus` | `is_bonus` |
| Cover image key | `image`, `cover`, `picture` | `cover_image`, `cover_image_url` | `cover_image_url` | `image` (relative path or URL) |
| One-line summary key | `description` (article, docs), `bio_short` (person), `short` (podcast), `summary` (wiki, book) | `description` (article, project), `summary` (wiki, docs) | `summary` | `summary` |
| Image references | site-absolute `/images/...` in raw HTML, Liquid `relative_url`, declared `images:` lists with `{IMAGE:id}` tokens | relative paths, rewritten at sync | relative | relative paths only, resolved from the referencing file, uploaded and rewritten by the engine |
| Links between items | `prev_url`/`next_url` filenames, Liquid, `[[wikilinks]]` by title, `/workshops/<slug>` style routes | bare sibling filenames rewritten, `/workshops/<slug>` routes | none | relative file links for siblings; typed `kind:slug` links for everything else; no wiki token syntax |
| Slug alphabet | `[a-z0-9]+(-[a-z0-9]+)*` in course repos; `[A-Za-z0-9._-]` in the wiki; two podcast slugs end in `.md` and two person keys carry `_` or `()` | lowercase, digits, hyphens | `[-a-zA-Z0-9_.]` in the knowledge base | `[a-z0-9]+(-[a-z0-9]+)*` everywhere |
| Author reference | `authors: [person-key]` resolved to `/people/` | `author: "Alexey Grigorev, Valeriia Kuka"` | none | `authors: [person-id]` plus optional `byline` (section 2.2 explains why both) |
| Jekyll residue | `layout:`, `permalink:`, `has_children:`, `has_toc:`, `grand_parent:`, `legacy_path:` | none | none | dropped; all are derivable or presentation |
| Which kind a file is | fixed per parser by source slug and root directory | classifier heuristics on directory names and front-matter sniffing (`classify.py:181-283`) | course parsers sniff the layout | declared once per repository in `content.yaml` |
| Markdown dialect | mistune plus kramdown and Liquid preprocessing | python-markdown plus extensions | python-markdown | one dialect, section 4 |

### 2.2 Genuinely different ideas: these stay distinct

| Pair | Why they are not the same thing |
|---|---|
| Course and workshop | A course is a tree of modules delivered to cohorts with homework, progress and certificates. A workshop is one recording with a landing page, a gate on the recording separate from the pages, and tutorial pages tied to video offsets (`workshops-content/_docs/03-04-frontmatter.md`). Folding a workshop into a one-module course loses the recording gate and the landing semantics. Both follow the same core rules; they keep separate kind schemas. |
| Course tree and cohort placement | The tree is authored once per course. A cohort places a subset in an order with dates and homework bindings (`community_base/curriculum/models.py:420`, DTC `CohortSharedModule`). This is the ownership decision already shipped in C5.1e and is not reopened. |
| A `kind: homework` unit and a `homework.yaml` | The unit is a page in the reading order (instructions, prose). The manifest is a gradable assignment with due date, form and encrypted answers, owned by a cohort (`llm-zoomcamp/cohorts/2026/homework/01-agentic-rag/homework.yaml`). AISL puts `questions:` and `due_date:` in the unit file (`_docs/course_yaml.md:195-235`), which welds a cohort artefact to course content and is exactly why AISL needs a one-cohort-per-sync resolution rule. They separate: the page stays in the tree, the assignment moves under the cohort and may point at the page. |
| `authors` and a byline | DTC authors are references to person records that resolve to profile pages. AISL's `author` is display text. A reference and a display string are different data; the format carries both, `authors` for identity and `byline` for display when no person record exists. |
| `summary` and `description` | `summary` is one line of plain text for cards, search and meta tags. `description` on a course, workshop or event manifest is long-form markdown copy for a landing page. Articles and pages have no long-form description apart from their body, so they carry only `summary`. |
| `required_level` and `status` | The gate answers who may read a published item. `status` answers whether the item is published at all. DTC uses `published: true`; AISL uses `status` and `published` on articles. One integer gate and one status enum. |
| `sort_order` and `date` | Sibling order in a tree versus chronological order in a feed. Articles, projects and podcasts are ordered by date; lessons, pages and modules by position. A date prefix on a filename (DTC articles, `YY-MM-DD-slug.md`) is chronology leaking into identity; it goes. |
| `tags` and `related` | Free taxonomy versus typed references to other items. `related` becomes a list of typed references, not titles. |
| Wiki page and docs page | A flat graph of pages versus a tree with one parent per page. Same page model, two sections, as `knowledge_base` already has; the format keeps `wiki/` flat and `docs/` nested. |
| Podcast `links` and `resources` | Platform-keyed listening URLs versus an ordered list of titled resources. Kind-specific, both kept. |
| FAQ question `id` and `content_id` | The ten-character id is the key the FAQ automation writes files by and that `_docs/compatibility/faq-fragment-contracts.jsonl` pins. `content_id` is the upsert key. Two keys with two roles. |
| Unit `video_url` and workshop `recording` | One video per lesson versus one recording per workshop with per-page `video_start` offsets. Different cardinality, both kept. |
| Content and generated artefacts | `graph/graph.json` and `search/search-corpus.json` in the podwiki are outputs of scripts over the wiki plus four other Jekyll collections. They are not authored content and the format does not describe their insides; they are carried as opaque data files (section 3.9). |
| Content and site configuration | `tiers.yaml`, `podcast-platforms.yaml`, `slack.yaml` configure a site. They ride in a content repository for convenience and are carried the same opaque way. |

### 2.3 Kinds by how far they unify

| Tier | Kinds | Rule |
|---|---|---|
| A, shared kinds | course (with module, unit, cohort, homework), article, wiki page, docs page, person | Both sites have them. Full unified schema in the package; the same parser can serve both sites. |
| B, single-site kinds | workshop, project, curated link, interview questions, podcast, book, faq, member wiki topic | One site has them. They obey the common core (section 3.2 to 3.6) and keep a site-owned kind schema documented in the same registry. |
| C, not content | events (decision D7: Studio-authored on both sites; AISL still syncs `events/*.yaml`, recorded in section 6), HTML partials (`events/community-launch/*.html`, `widgets/*.html`), generated artefacts, site configuration | Outside the format, except that data files travel as opaque records. |

A negative finding, stated plainly: the FAQ, podcast and book kinds gain nothing from a
different layout. They are DTC-only, their YAML shapes are sound, and the FAQ has its own writer
(`faq_automation/`, GitHub Actions) that produces the current file names. Section 3 applies the
core rules to them only where a rule is violated (Liquid, absolute asset paths, identity), and
section 5 prices the FAQ conversion as optional.

## 3. The specification

Name: the DataTalks.Club content format, version 1. Lives in the package as
`community_base/content_sync/FORMAT.md` (normative text, this section) and
`community_base/content_sync/kinds/` (the kind registry that enforces it). Everything below is
normative unless marked as a recommendation.

### 3.1 Repository manifest

Every synced repository carries `content.yaml` at its root. A repository without it is not
synced; the engine records one error and stops for that source.

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

Files outside every collection path are ignored, not errors. This replaces AISL's classifier
(`classify.py`, 391 lines of directory and front-matter heuristics) and DTC's per-parser
`source.slug` checks with one declaration per repository.

### 3.2 Two file shapes

- A document is a `.md` file whose first line is `---`, followed by YAML front matter, a line
  `---`, then the markdown body. Front matter is required; a `.md` file without it inside a
  collection is an error. UTF-8, LF line endings.
- A manifest is a `.yaml` file whose top level is a mapping.
- File names inside a collection: `NN-slug.md`, `slug.md`, `index.md`, `README.md`,
  `<fixed name>.yaml` as the kind prescribes. Files and directories whose name starts with `_`
  or `.` are ignored.

### 3.3 Core keys

Every document and every item manifest (course, module, cohort, homework, workshop, podcast,
book) carries the core keys. Unknown top-level keys are an error. A kind adds keys; it never
removes, renames or retypes a core key.

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

### 3.4 Naming, ordering and identity

- Ordering prefix: a file or directory name may start with two or three digits and a hyphen
  (`01-intro.md`, `01-agentic-rag/`, `001-first-question.md`). The prefix sets `sort_order` and
  is stripped from the slug. An explicit `sort_order` wins over the prefix. Two siblings that
  strip to the same slug are an error; two siblings with the same prefix are allowed.
- No date prefixes on names. Chronology is `date` in front matter.
- `index.md` is the document of its directory (a tree node). `README.md` is for GitHub readers
  and is read only where a kind names it (module overview, workshop landing copy).
- `content_id` is the upsert key. A renamed file with the same `content_id` updates the same
  record with a new slug. A changed `content_id` creates a new record and drafts the old one,
  exactly as `knowledge_base.sync.delete_missing` and the curriculum soft delete do today.
- `slug` is the URL segment. `path` for a tree kind is the chain of ancestor slugs plus the
  slug, relative to the collection root, joined with `/`. The public URL is the site's decision:
  the package apps compute a default route from `(kind, path)` and a site may map it.
- Provenance: `source_content_id` on every synced row holds the item's `content_id`. Section 6
  records that the knowledge base stores the source's pk there today.

### 3.5 Nesting

- A tree is expressed by directories and by nothing else. `parent:` keys do not exist.
- In a docs collection: a directory is a node and must contain `index.md`; leaves are
  `NN-slug.md` files; maximum depth four below the collection root.
- In a course: a module is a directory holding `module.yaml`; a submodule is a directory holding
  `module.yaml` inside a module directory; maximum two module levels
  (`curriculum.source.validate_module_tree`); a module directory holds either submodule
  directories or unit files, never both, apart from `README.md` and asset directories.
- A wiki collection is flat: one directory of `slug.md` files; subdirectories are an error.
- Cohorts are not part of the tree; they are placements (section 3.8, course).

### 3.6 Assets

- An asset is any file that a document body, a manifest key of asset type (`image`, and the
  kind-declared ones), or an HTML `<img src>` references by a relative path.
- A reference resolves from the referencing file's directory and must stay inside the
  repository. A path that escapes the repository, an absolute `/path`, a Liquid expression or
  a `{IMAGE:id}` token is an error. An asset may live outside every collection (DTC's shared
  `images/` root) as long as a document references it.
- `https://` references are left alone. `http://` and `data:` references are errors.
- Allowed asset types: `png`, `jpg`, `jpeg`, `gif`, `webp`, `svg`, `pdf`. The engine applies
  the signature and unsafe-SVG checks now in DTC `content/sync_parsers/media.py:53-73` to every
  asset before upload. Maximum 16 MiB.
- The engine uploads every referenced asset through `content_sync.media` keyed by the
  repository path and rewrites the reference in the rendered HTML and in stored asset keys.
  Unreferenced files are not assets and are not uploaded.
- Recommendation: keep an item's assets in an `images/` directory next to the item (article
  directory, module directory, workshop directory) or, for flat collections, in
  `<collection>/images/`.
- `theme_pairs` (section 3.1) makes `name.dark.ext` a paired asset of `name.ext`; the engine
  emits both with the class hooks the site styles (AISL issue 1725 behaviour, opt-in).

### 3.7 Cross-references

One link syntax: a standard markdown link or image. Three destination forms.

| Form | Example | Resolution |
|---|---|---|
| Relative file | `[setup](02-environment.md)`, `[intro](../01-intro/index.md#running-example)` | another document in the same collection; resolved to that document's route; the fragment must name a heading of the target when both are in the same source |
| Typed reference | `[A/B testing](wiki:a-b-testing)`, `[Rahul](person:16rahuljain)`, `[episode](podcast:s24e01-competitions-beyond-kaggle-leaderboard)`, `[project rules](docs:courses/llm-zoomcamp/project)`, `[module 1](course:llm-zoomcamp/agentic-rag)` | `kind:` prefix is a registered kind; the remainder is the target's slug, or its path for a tree kind; resolved through the kind's route resolver, site-provided for site-routed kinds |
| External URL | `[docs](https://...)` | left alone |

Front-matter references use the same typed form without the link wrapper:
`related: [wiki:a-b-testing, podcast:s24e01-...]`. Keys whose kind is fixed omit the prefix:
`authors: [16rahuljain]`, `instructors: [alexey-grigorev]`, `guests: [tatianagabruseva]` are
person references.

Rules.

- An unresolved reference fails the sync when `strict_references` is true (the default),
  otherwise the link is dropped, its label kept, and a warning recorded. This keeps DTC's
  wiki behaviour (fail on unresolved fragments, `podwiki.py:363-374`) as the default and its
  graceful degradation for cross-source podcast links as the opt-out.
- Resolution happens at sync, against the rows already synced. A reference to a kind from
  another source therefore requires that source to be synced first; the engine orders sources
  by the declared kinds' dependencies, which is what DTC's `podwiki.py:265-299` does by hand.
- `[[wikilinks]]`, `prev_url`, `next_url` and Liquid do not exist. Previous and next are derived
  from order.
- Heading fragments use the slug algorithm of section 4. Every heading id on a page is unique;
  duplicates get `-2`, `-3`.
- The resolved references of a document are stored as a list of `{kind, target, label, href}`
  on the record. This is DTC's `relations` (`podwiki.py:391`), made general.

### 3.8 Kind registry and kind schemas

The registry is `community_base.content_sync.kinds`. A kind is a module that declares: the
file shape (`document`, `manifest`, `tree`, `data`), the kind keys with type, required flag
and default, which keys are asset references and which are typed references, and a route
resolver. The package registers the tier A kinds and `data`; a site registers its tier B kinds
with `register_kind(name, spec)` in `AppConfig.ready()`, the same pattern as
`register_parser`. A kind cannot alter the core; `extra` is the only site escape hatch.

The specifications below list kind keys only; core keys apply everywhere.

#### course

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
| `extra` | mapping | no | `{}` | 

AISL's `access_mode`, `enroll_url`, `program_label` and `maven_course_key` go under `extra`
and stay AISL-read (`families/courses.py:64-125`). DTC's `starting_point`, `progression` and
`homework_summaries` go under `extra` and stay DTC-read. `cohorts`, `current_cohort`, `urls`,
`schema_version`, `published`, `cover_image`, `cover_image_url`, `ignore` (moved to
`content.yaml`) and `instructor_name` do not exist.

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
assignment is the cohort's `homework.yaml`. `is_homework`, `is_preview`, `access`, `prev_url`
and `next_url` do not exist.

`cohorts/<identifier>/cohort.yaml`. The identifier is the directory name and is not repeated
inside the file. It follows the slug pattern (`2026`, `self-paced`, `4`).

| Key | Type | Required | Default |
|---|---|---|---|
| `delivery` | `live` or `self_paced` | yes | none |
| `start_date`, `end_date` | ISO dates | when `delivery: live` and `status: published` | `null` |
| `modules` | ordered list of top-level module slugs | no | absent means the full course tree in module order |
| `archive` | boolean | no | `false`; `true` means the cohort places no modules and points GitHub readers at its own directory (`README.md` is the notice) |
| `registration_url` | https URL | no | `""` |
| `hashtag` | as course | no | `""` |
| `homework` | list of `{module, source, unit}` | no | `[]` |

`homework[].module` is a top-level module slug that the cohort places; `homework[].source` is
the manifest path relative to the cohort directory (`homework/01-agentic-rag/homework.yaml`);
`homework[].unit` is the optional `content_id` of a `kind: homework` unit whose page shows the
submission form. This is DTC's binding (`llm-zoomcamp/cohorts/2026/cohort.yaml`) plus the one
key AISL needs to keep its form on the unit page. `title` defaults to
`<course title> <identifier>`. `curriculum: current` becomes the absence of `archive`;
`curriculum: github_archive` becomes `archive: true`; `identifier`, `course`, `published`,
`legacy_slug`, `year`, `format` and `flow` do not exist. The package maps `modules` to
`CohortGraph.module_refs` and `CohortModule` placements.

`homework/<module-slug>/homework.yaml` keeps the DTC manifest exactly
(`llm-zoomcamp/cohorts/2026/homework/01-agentic-rag/homework.yaml`): core keys plus
`instructions_path` (default `homework.md`), `due_at` (ISO datetime with offset), `initial_state`
(`closed`, `open`, `scored`), `form` (`homework_url`, `time_spent_lectures`,
`time_spent_homework`, `faq_contribution`, `learning_in_public_cap`), `questions` (each with
`content_id`, `id`, `type`, `prompt`, `points`, `options`, `answer_type`, and the encrypted
`answer` envelope of `coursework/answer_crypto.py:40-43`). AISL's plaintext `questions:` with
`correct:` in unit front matter does not exist; answers are always the envelope.

#### article

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

Storage stays site-owned (D21): the AISL parser fills `content.Article`, the DTC parser fills
`SyncedDocument`. Both read this one shape.

#### person

```
people/<id>.md
people/images/<id>.jpg
```

`title` is the display name, `summary` the short bio, `image` the picture, the body the long
bio. Kind keys: `links`, a list of `{label, url}` where `label` is one of `website`, `linkedin`,
`github`, `x`, `youtube`, `other`. AISL keeps instructors DB-authored if it wants; a synced
person is the same shape on both sites. `short`, `picture`, `bio_short`, `layout`, `photo_url`
do not exist.

#### wiki

```
wiki/<slug>.md
wiki/images/...
```

| Key | Type | Required | Default |
|---|---|---|---|
| `related` | list of typed references | no | `[]` |
| `page_type` | slug | no | `""`; a site-defined template selector (DTC's `layout: article` versus `wiki`) |

Stored per page: rendered HTML, the heading list, and the resolved references. DTC's
`keyword`, `secondary_keywords`, `seo_title`, `search_intent` and `related_wiki` go under `extra`.

#### docs

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

The tree is the directory tree. The page key in `knowledge_base` is `(section, parent, slug)`
and the stored path is the directory chain, which is what C7.4 step 1 proposes. Repeated leaf
slugs under different parents (DTC's fifteen repeated segments) are legal. `parent`,
`grand_parent`, `nav_order`, `has_children`, `has_toc`, `permalink`, `layout` do not exist.

#### data

```
data/<name>.yaml or data/<name>.json
```

One opaque record per file, keyed by the file stem, carrying the parsed content untouched. No
core keys are required. The package stores it; a site parser interprets it. This carries
`tiers.yaml`, `podcast-platforms.yaml`, `slack.yaml`, `graph.json` and `search-corpus.json`.

#### Tier B kinds, site-registered

| Kind | Site | Layout | Changes needed to obey the core |
|---|---|---|---|
| workshop | AISL | `YYYY/MM/YYYY-MM-DD-<slug>/workshop.yaml`, `NN-page.md`, `README.md`, `images/` | `cover_image_url` becomes `image`; `instructor_name` becomes `instructors` (person references) with `byline` fallback; page links already relative; everything else in `_docs/03-04-frontmatter.md` stands |
| project | AISL | `projects/<slug>/index.md`, `images/` | file renamed to `index.md`; `author` becomes `authors` or `byline`; `description` becomes `summary`; `cover_image` becomes `image` |
| curated_link | AISL | `links/NN-<slug>.md` | `content_id` becomes a UUID; `item_id` retired; `category` and `url` are kind keys |
| interview_question | AISL | `interview-questions/<slug>.md` | unchanged apart from `description` becoming `summary` |
| podcast | DTC | `podcasts/sNN/eNN.yaml`, `eNN-transcript.yaml`, `podcasts/sNN/images/` or a shared `podcasts/images/` | add `content_id`; `short` becomes `summary`; `image` path becomes relative; `legacy_path` retired; `dateadded` becomes `date`; `guests` are person references; the flat pre-reorg transcript layout is retired |
| book | DTC | `books/YYYY/<slug>.yaml`, `books/images/` | add `content_id`; `cover` and `image` become `image`; `legacy_path` retired; `start` becomes `date` with `end` kept as a kind key; `authors` are person references |
| faq | DTC | unchanged: `faq/<course>/index.yaml` (was `_metadata.yaml`), `faq/<course>/<section>/NNN-<id>-<slug>.md` | optional: add `content_id`; `{IMAGE:id}` tokens and `images:` declarations become relative image links; the ten-character `id` stays as a kind key; the `_questions` prefix and underscore separators go because leading underscores are ignored by the core |
| member wiki topic | AISL | private repository, `wiki/<slug>.md` | `_wiki` renamed to `wiki`; otherwise a wiki collection with `topics` under `extra` |

### 3.9 Worked examples

`content.yaml` of a single-course repository (`DataTalksClub/llm-zoomcamp`)

```yaml
schema_version: 1
collections:
  - kind: course
    path: .
ignore:
  - "**/code/**"
  - "etc/**"
  - "awesome-llms.md"
  - "project.md"
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
  Large Language Models. ...
outcome: Build, evaluate, and monitor production-style LLM applications.
prerequisites: You can write Python and use the command line, with some Docker familiarity.
repository_url: https://github.com/DataTalksClub/llm-zoomcamp
docs_url: https://datatalks.club/docs/courses/llm-zoomcamp/
faq_url: https://datatalks.club/faq/llm-zoomcamp.html
hashtag: llmzoomcamp
instructors: [alexeygrigorev]
extra:
  starting_point: You want to turn questions over your own documents into a working application.
  progression:
    - heading: I have documents and questions, but no working application
      description: I want an LLM to answer from my own data.
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

![Overview of the course RAG project](images/01-intro-01-rag-project-overview-imagegen.png)
```

`cohorts/2026/cohort.yaml`

```yaml
content_id: "0ea85a46-bd6b-4f21-82fe-317954d8be32"
title: LLM Zoomcamp 2026
delivery: live
start_date: "2026-08-24"
end_date: "2026-10-12"
hashtag: llmzoomcamp
homework:
  - module: agentic-rag
    source: homework/01-agentic-rag/homework.yaml
  - module: vector-search
    source: homework/02-vector-search/homework.yaml
```

`cohorts/2025/cohort.yaml` (GitHub-only archive)

```yaml
content_id: "5393ebf3-f68b-48f2-abca-d686bbbd7e7c"
title: LLM Zoomcamp 2025
delivery: live
start_date: "2025-05-27"
end_date: "2025-08-23"
archive: true
```

`cohorts/4/cohort.yaml` for an AISL course, and its `course.yaml` tail

```yaml
content_id: "7b1f5a3e-2c4d-4e8f-9a0b-1c2d3e4f5a6b"
title: Cohort 4
delivery: live
start_date: "2026-09-21"
end_date: "2026-11-22"
homework:
  - module: foundations-llms-rag-and-structured-output
    source: homework/01-foundations/homework.yaml
    unit: "458d8bbc-f236-5be3-a29a-774e4f435e65"
```

```yaml
required_level: basic
default_unit_required_level: basic
extra:
  access_mode: entitlement
  enroll_url: https://maven.com/alexey-grigorev/from-rag-to-agents
  program_label: Maven
  maven_course_key: from-rag-to-agents
  maven_cohort_keys: {"4": "4"}
```

`articles/crisp-dm-for-ai/index.md` (AISL) and `articles/building-ai-agent-that-thrives-in-real-world/index.md` (DTC)

```markdown
---
content_id: "6bc9da15-7603-46ee-901d-096fdebf5764"
title: "CRISP-DM for AI Engineering: Why a 1996 Framework Still Describes Modern AI Development"
summary: See how CRISP-DM still guides AI engineers in 2026.
date: 2026-03-11
authors: [alexey-grigorev, valeriia-kuka]
tags: [ai-engineering, data-science, crisp-dm]
image: images/cover.jpg
---

During AI development, teams work with large language models (LLMs) ...
```

```markdown
---
content_id: "3f7c2a10-5e2b-4d1a-9c3e-8b7a6f5d4c3b"
title: Building an AI Agent that Thrives in the Real World
subtitle: A Guide to Development, Testing, and Monitoring
summary: A Guide to Development, Testing, and Monitoring
date: 2025-02-26
authors: [sallyanndelucia]
tags: [arize, llm, monitoring]
image: images/cover.jpg
related: [article:llm-monitoring-basics]
---

<figure>
<img src="images/image2.jpg" alt="Building an AI agent that thrives">
<figcaption>Building an AI agent that thrives</figcaption>
</figure>
```

`docs/02-courses/04-llm-zoomcamp/index.md` and `docs/02-courses/04-llm-zoomcamp/07-project.md`

```markdown
---
content_id: "9a1b2c3d-4e5f-4a6b-8c7d-0e1f2a3b4c5d"
title: LLM Zoomcamp
summary: Free, hands-on course on building RAG and AI applications with Large Language Models
---

The LLM Zoomcamp is a free, hands-on course ...

1. [Community Guidelines](../../01-general/02-guidelines/index.md)
2. [Zoomcamp Logistics](../01-zoomcamp-logistics/index.md)
```

```markdown
---
content_id: "0b1c2d3e-4f5a-4b6c-9d8e-1f2a3b4c5d6e"
title: Project
summary: Rubric and deadlines for the final project.
toc: false
---

Submit your project through the [course platform](course:llm-zoomcamp).
```

`wiki/a-a-testing.md` (DTC podwiki) and `wiki/ai-engineering-glossary.md` (AISL)

```markdown
---
content_id: "c4d5e6f7-a8b9-4c0d-8e1f-2a3b4c5d6e7f"
title: A/A Testing
summary: A/A testing for validating experiment assignment, tracking, and statistical interpretation.
related: [wiki:a-b-testing, wiki:power-analysis, wiki:event-tracking]
page_type: concept
extra:
  seo_title: A/A testing explained
---

A/A testing sits between [event tracking](wiki:event-tracking),
[product analytics](wiki:product-analytics) and [A/B testing](wiki:a-b-testing).
It doesn't answer whether a feature works.
[Product Analytics and A/B Testing](podcast:s12e04-ab-testing-and-product-experimentation)
```

```markdown
---
content_id: "523a63d8-58da-453c-b951-516076ccaca5"
title: AI Engineering Glossary
summary: Plain-language definitions of the terms that come up most often in AI engineering discussions.
---

## Core terms

- LLM (large language model): a neural network trained on large amounts of text ...
```

`people/16rahuljain.md`

```markdown
---
content_id: "d7e8f9a0-b1c2-4d3e-8f4a-5b6c7d8e9f0a"
title: Rahul Jain
summary: Data engineering manager at Siemens with over 12 years of experience.
image: images/16rahuljain.jpg
links:
  - {label: linkedin, url: https://www.linkedin.com/in/16rahuljain/}
---

Rahul Jain is a data engineering manager at Siemens ...
```

### 3.10 Validation

The package ships `uv run python -m community_base.content_sync.check <path>` (also a
management command `check_content`), usable in a content repository's CI without a database.
It validates `content.yaml`, every collection against its kind schema, naming and ordering,
identity uniqueness, asset resolution, references inside the repository, and the dialect rules
of section 4. Diagnostics carry the repository path and a YAML pointer, never prose. It replaces
`zoomcamp-ops` `check_zoomcamp.py`, AISL `scripts/check_workshops.py` and
`scripts/check_content_ids.py`, and DTC `scripts/verify_course_repository_curriculum.py` for
layout checks.

## 4. Rendering: one markdown dialect

Decision: python-markdown, in the package, at sync time, with one sanitiser. Not mistune. The
package already renders with python-markdown in two apps (`curriculum/rendering.py`,
`knowledge_base/rendering.py`), AISL renders everything with it, and mistune is used by DTC in
two modules that D7.1 and the article path retire or reshape anyway. The reverse choice would
rewrite the package and AISL to save DTC two modules.

### 4.1 The dialect

- CommonMark as python-markdown implements it, plus `tables`, `fenced_code`, `sane_lists`,
  `attr_list` is not enabled, `md_in_html` is not enabled.
- Fenced code blocks render to `<pre><code class="language-x">`. No server-side highlighting in
  the package. A site may add `codehilite` through the extension hook below.
- A fenced block with info string `mermaid` renders to `<pre class="mermaid">` with the source
  escaped; the site's JavaScript draws it. Both sites use mermaid already (`docs`
  `_includes/mermaid_config.js`, AISL `MermaidExtension`).
- A fenced block with info string `embed` whose body is a YAML mapping `{type, id}` with `type`
  in `youtube`, `loom` renders to `<div class="cb-embed" data-embed-type="youtube" data-embed-id="...">` containing a plain link to the video. The site hydrates it. This replaces DTC's `{% include youtube.html video_id=... %}` and keeps iframes out of stored HTML.
- Raw HTML is allowed and passes through the sanitiser. `<figure>`, `<figcaption>`, `<details>`,
  `<summary>`, `<img>`, `<table>` survive; `style` attributes, `<script>`, `<style>`, `<iframe>`
  and event handlers do not.
- Liquid (`{% %}`, `{{ }}`) and kramdown attribute lists (`{: .class }`) are errors outside
  fenced and inline code. Inside code they are text.
- A leading H1 equal to the title is stripped, as `knowledge_base` does today.
- Heading ids are injected after rendering by the package with DTC's algorithm
  (`content/docs_projection.py:111-139`): NFKD, ASCII, lowercase, non-alphanumerics to `-`,
  duplicates suffixed `-1`, `-2`; the heading list `{level, id, title}` is returned and stored.
  This keeps DTC's pinned fragment contracts (`_docs/compatibility/faq-fragment-contracts.jsonl`,
  `podwiki-graph-fragment-contracts.jsonl`) meaningful.
- Links are resolved and images rewritten before rendering, by the parser toolkit (sections 3.6
  and 3.7).
- Plain text for search is derived from the rendered HTML by the package, as
  `knowledge_base.search` does.

### 4.2 Where it lives and who owns what

- `community_base/content_sync/rendering.py` owns `render_document(text, *, extensions)`,
  `inject_heading_ids`, `sanitize_rendered_html` and `plain_text`. `curriculum/rendering.py`
  and `knowledge_base/rendering.py` become thin imports of it.
- Rendering runs in the sync job through the parser toolkit, never in a model `save()`. The
  page and unit models store `body_html` as supplied (C7.4 step 3 for the knowledge base, the
  same change for `curriculum.Unit`). This matches DTC spec 03 line 190 and architecture rule 7.
- Sanitisation is package-owned and always last. The allowlist is the one already lifted from
  DTC into `knowledge_base/rendering.py:30-148` (tags, attribute filter, URL schemes) plus the
  attributes the shared extensions emit: `class` on `div`, `pre`, `code`, `span`, `img`;
  `data-embed-type`, `data-embed-id` on `div`; `data-theme-figure` on `img`. `curriculum`'s
  narrower list and AISL's `sanitize_html` list are retired for synced content. DTC's bleach
  cleaner (`content/services.py:145-235`) is retired for synced content when D7.1 lands.
- Sites extend, they do not replace: `COMMUNITY_BASE["MARKDOWN_EXTENSIONS"]` is a list of
  dotted paths to python-markdown extensions appended to the package list (AISL's
  `EventWidgetExtension`, `ExternalLinksExtension`, `codehilite`). An extension's output still
  passes the package sanitiser, so an extension that needs a new attribute needs a package
  change to the allowlist.

### 4.3 What breaks, and what to do about it

| Break | Where | Handling |
|---|---|---|
| Inline `style` on `<img>` in DTC articles | `content/articles/**` (five occurrences seen in one file, more across 55) | stripped by the sanitiser; the conversion script removes `style` and keeps `width` and `loading`; a rendering diff over all 55 articles is a human review step |
| kramdown `{: .fs-9 }`, `{: .btn }` in DTC docs | two occurrences, `docs/index.md`, `courses/index.md` | dropped; the site's stylesheet styles the hooks |
| Liquid includes in DTC articles: `related-posts.html`, `youtube.html`, `course-structured-data/*.html` | about twelve files | `youtube.html` becomes an `embed` fence; `related-posts` becomes `related:` front matter; the structured-data includes are site SEO output, not content, and are removed from the source |
| Raw HTML blocks followed by markdown on the next line | DTC articles, python-markdown needs a blank line after a block-level HTML element | the conversion script inserts blank lines after `</figure>`, `</table>`; the rendering diff catches the rest |
| DTC wiki and person pages stop being plain-text `blocks` | `templates/public/wiki_detail.html:144`, `content/catalogue.py:548-557` | they render stored HTML plus the stored heading list and references; this is D7.1 work and removes gap 2 of the C7.4 report for the body, leaving `tags`, `references` and `page_type` to the record field |
| DTC article `blocks` with the FAQ split index | `scripts/build_public_projection.py:1208-1360` | article storage is site-owned (D21); DTC may keep deriving blocks from the unified source, or render the body once; not decided here |
| Server-side code highlighting | AISL | `codehilite` registered through the extension hook, unchanged output |
| `normalize_inline_bullets` and `linkify_urls` | AISL `content/utils/markdown.py:56-104` | not applied to synced content; they exist for Studio-authored event and email text and stay there |
| mistune `strikethrough` | DTC docs | python-markdown has no built-in strikethrough; `~~x~~` is rare in the corpus; the validator warns and the conversion script rewrites to `<del>` |
| Heading id suffix style | AISL `toc` produced `_1`; DTC `-1` | one algorithm, DTC's, and AISL's docs are new enough to have no pinned fragments |

## 5. Conversion cost per content repository

Counts are `git ls-files` on the local clones on 2026-09-17. "Scripted" means one conversion
script per repository, run once, producing a pull request; "human" is what a person must look
at before that pull request merges. Every conversion is verified by `check_content` (section
3.10) in the content repository and by a development-site sync that reports zero errors.

| Repository | Files changed | Scripted | Human |
|---|---|---|---|
| `DataTalksClub/llm-zoomcamp` | `content.yaml` added; `course.yaml` rewritten (drop `schema_version`, `cohorts`, `current_cohort`, flatten `urls`, move `starting_point` and `progression` to `extra`); 7 `module.yaml` (drop `units`, `schema_version`); 72 lessons gain `content_id` and `title` from the manifest and lose `prev_url`, `next_url`; 3 `cohort.yaml` (drop `identifier`, `course`, `schema_version`, `format`; `curriculum` to `archive`; homework `source` made cohort-relative; `module` to slug); 7 `homework.yaml` (drop `schema_version`) | all of it, from the manifests | none; the checker proves the round trip |
| `DataTalksClub/data-engineering-zoomcamp` | same shape: 7 modules, 88 lessons, 6 cohorts, 7 homework manifests | all | none |
| `DataTalksClub/machine-learning-zoomcamp` | 9 modules, 113 lessons, 6 cohorts, 9 homework manifests; 1,226 module images stay where they are | all | none |
| `DataTalksClub/mlops-zoomcamp` | 6 modules, 46 lessons, 5 cohorts, 0 homework manifests | all | none |
| `DataTalksClub/ai-dev-tools-zoomcamp` | 4 modules, 2 cohorts, 4 homework manifests; lessons live below the module directory and need the `NN-unit.md` sibling rule checked by hand | most | the module layout, one look |
| `DataTalksClub/stock-markets-analytics-zoomcamp` | `content.yaml`, `course.yaml` (schema 1, no modules); `homework_summaries` to `extra` | all | none; the course has no module tree to convert |
| `DataTalksClub/content` | `content.yaml`; 55 articles renamed from `articles/YYYY/YY-MM-DD-slug.md` to `articles/<slug>/index.md`, `description` to `summary`, `image` to `image`, raw `<img src="/images/posts/...">` to relative, `style` attributes dropped, `layout` and `datepublished` dropped, Liquid includes converted (about twelve files); 98 books gain `content_id`, lose `legacy_path`, `cover` and `image` merge; 203 podcasts and 201 transcripts gain `content_id`, lose `legacy_path`, `short` to `summary`, `dateadded` to `date`; 815 images either stay under `images/` with references rewritten, or move next to their items (recommended) | all except the Liquid includes | the twelve Liquid files; a rendering diff of all 55 articles under python-markdown (section 4.3) |
| `DataTalksClub/datatalksclub.github.io` | 444 `_people/*.md` and their `images/authors/` pictures move into `DataTalksClub/content` as `people/` (recommended, section 9); front matter `short`, `picture`, `bio_short`, `layout` to core keys; one picture path with a stray space and two keys outside the slug alphabet (`_template`, `ella(wati)sahnan`) | all but three files | three files; the repository stops being a sync source |
| `DataTalksClub/docs` | 106 pages: `nav_order` to `sort_order` (no directory renames, so public paths are unchanged), `layout`, `parent`, `grand_parent`, `has_children`, `has_toc`, `permalink` dropped, `description` to `summary`, `content_id` minted; about 150 Liquid `relative_url` links to relative file links; 2 kramdown lines dropped; 25 pages whose parent is a sibling page (the five section pages under `courses/zoomcamp-logistics/`) move into five new subdirectories with `index.md`; 54 images referenced relatively | all but the 25 | the 25 re-parented pages, because their public paths change from `/docs/courses/zoomcamp-logistics/joining/` to `/docs/courses/zoomcamp-logistics/start-here/joining/`, which is a DTC route decision |
| `DataTalksClub/podwiki` | 283 wiki pages: `layout` to `page_type`, `related` titles to `wiki:` references, SEO keys to `extra`, `content_id` minted; `[[...]]` tokens to typed links using the same title map the parser uses today; `graph/graph.json` and `search/search-corpus.json` declared as a `data` collection; the repository's own build scripts keep producing them | most | tokens whose title resolves to nothing today (the parser drops them silently, `_wiki_relations`); a report lists them |
| `DataTalksClub/faq` | `content.yaml` only, declaring a site-registered `faq` kind over `_questions/` renamed to `faq/`; optional later: `content_id` on 1,400 questions and relative images for 76 | the rename | none, unless the optional step is taken, which also touches `faq_automation/` |
| `AI-Shipping-Labs/content` | `content.yaml` (replaces the classifier); 22 articles renamed to `articles/<slug>/index.md`, `description` to `summary`, `author` to `authors` or `byline`, `cover_image` to `image`; 10 projects the same; curated links, interview questions renamed keys; 2 wiki and 7 docs pages, the docs pages into directories per their `parent`; `courses/aihero` unchanged apart from `content.yaml`; `tiers.yaml` to `data/`; `events/` left alone (section 2.3, tier C) | all | none |
| `AI-Shipping-Labs/python-course` | `content.yaml` with `ignore` moved out of `course.yaml`; `course.yaml` drops `instructor_name`, `instructor_bio`, `is_free`, `cover_image` to `image`; `cohorts/self-paced/cohort.yaml` added; 84 units unchanged | all | none |
| `AI-Shipping-Labs/ai-buildcamp-course` | `content.yaml` with the `ignore` list; `course.yaml` drops `cohorts`, Maven keys to `extra`, `default_unit_access` to `default_unit_required_level`; `cohorts/4/cohort.yaml` added; 210 units unchanged; the branch `restructure-1675-maven-tree` is the shape to convert from, not `origin/main` | all | confirm the restructure branch is the intended tree |
| `AI-Shipping-Labs/workshops-content` | `content.yaml`; 25 `workshop.yaml`: `cover_image_url` to `image`, `instructor_name` to `instructors` or `byline`; 258 pages unchanged; `scripts/check_*.py` replaced by `check_content` | all | none |
| `AI-Shipping-Labs/wiki` | `content.yaml`; `_wiki/` renamed `wiki/`; 19 pages gain `content_id`, `topics` to `extra` | all | none |

Totals: about 4,000 files touched across sixteen repositories; roughly 95 percent by script.
Human review concentrates on three places: the 55 DTC articles' rendering diff, the 25
re-parented docs pages, and the podwiki tokens that do not resolve.

Two conversion scripts cover everything: one for course repositories (manifest to front matter,
cohort rewrite) and one for document collections (rename, key mapping, link and image rewrite,
Liquid handling). Both belong in the package as `content_sync/convert/` so the same code runs
against every repository, and both are deleted after the last conversion merges.

## 6. Findings that change the plan's assumptions

- The package's DTC course parser cannot read any live DTC course repository with modules.
  `parsers_dtc.py:559-562` demands `schema_version == 1`; `llm-zoomcamp`, `data-engineering-zoomcamp`,
  `machine-learning-zoomcamp`, `mlops-zoomcamp` and `ai-dev-tools-zoomcamp` are schema 2 with
  `cohorts:` inline, `urls:`, `current_cohort`, `delivery`, `curriculum` and `homework` bindings
  (`~/git/llm-zoomcamp/course.yaml`, `cohorts/2026/cohort.yaml`). Its lesson front matter rule
  (`parsers_dtc.py:349-351`, only `video_url` and `code`) rejects the `prev_url` and `next_url`
  keys that 71 of 72 llm-zoomcamp lessons carry. D5.1 would stop on its first repository.
- The package's AISL course parser skips two of the three AISL courses.
  `content_sync_parsers.py:145-148` ignores a root-level `course.yaml` because it assumes the
  DTC layout; `ai-buildcamp-course` and `python-course` both have a root `course.yaml` with no
  `schema_version`, which the DTC parser then rejects. Only `content/courses/aihero` parses.
  A5.1 would import one course of three.
- Neither parser is therefore a working baseline. Retiring both for one parser (C7.10) is not a
  clean-up; it is the first parser that would work against the real repositories.
- `source_content_id` means two things. `curriculum/importing.py:265` stores the item's
  `content_id`; `knowledge_base/sync.py:120,152` stores the `ContentSource` primary key and uses
  it as the ownership scope of `delete_missing`. The provenance mixin's own docstring says
  neither. Section 3.4 fixes the meaning to the item's `content_id`; the knowledge base gets a
  separate source foreign key for scoping (C7.9c).
- DTC docs identity is not "a slash path" in the sense the C7.4 report treats it. It is a
  directory path for 81 of 106 pages and a title-declared parent that contradicts the directory
  for 25 (all five section pages under `courses/zoomcamp-logistics/`). C7.4 step 1's
  parent-scoped slug is the right model; the format removes the title lookup entirely.
- DTC syncs generated artefacts as content and couples sources at sync time. `podwiki.py:265-299`
  refuses to run until podcast, book and people rows exist, and rewrites `graph.json` and
  `search-corpus.json` against them. Section 3.7 turns the ordering into a declared dependency
  and section 3.8 carries the two files as `data`; the graph itself stays DTC-owned (C7.2 step 5).
- Two DTC parsers and one DTC catalogue parser publish nothing (section 1.1). They are not
  evidence of a content kind that needs a format; `podcast_platforms` and `slack_page` are
  `data` files, and the course catalogue copy is course metadata the package course model can
  carry once DTC adopts it.
- AISL still syncs events from GitHub (`events/community-launch.yaml`, `families/events.py`)
  although decision D7 makes events Studio-authored on both sites. Out of this design's scope;
  recorded as a question in section 9.
- The package coursework app has the answer envelope (`coursework/answer_crypto.py`) but no
  `homework.yaml` reader; DTC's `courses/services/curriculum_source.py:114-160` is the only
  implementation of the manifest the format keeps. That reader is issue C7.11.
- Decision D16's clause "each site keeps its own parsers" was taken when the two sites' formats
  differed. With one format, the wiki and docs parsers on the two sites are the same code
  (`families/knowledge_base.py` already contains nothing site-specific). Section 9 asks the owner
  whether tier A parsers move into the package; the course parsers already live there, so the
  precedent exists.
- Decision D21 stands. The format is upstream of storage; the AISL article parser and the DTC
  article parser read one file shape and write two models. Nothing here asks to revisit it.

## 7. Proposed issues

Numbering continues `docs/plan/phase-7.md`, whose last issue is `C7.6`. Each issue below is
one pull request. Dependencies are given the way `scripts/plan.py` reads them.

### C7.7 Content format: specification, kind registry and validator

Repository: community-base. Depends on: nothing. Freeze required: no.

Goal: the package states the format normatively and can check a repository against it without
a database.

Steps
1. Add `community_base/content_sync/FORMAT.md` from section 3 and 4 of this document.
2. Add `content_sync/kinds/`: the registry (`register_kind`, `get_kind`), the core key schema,
   and the package kinds `course`, `article`, `person`, `wiki`, `docs`, `data`.
3. Add `content_sync/check.py` and the `check_content` command: `content.yaml`, naming,
   ordering, identity, assets, in-repository references, dialect rules.
4. Fixture repositories under `tests/content_sync/fixtures/` for a single-course repository, a
   multi-collection repository and a docs tree with repeated leaf slugs.

Verification
- `uv run pytest tests/content_sync` passes; every rule in section 3 has a failing fixture.
- `uv run python -m community_base.content_sync.check tests/content_sync/fixtures/<each>` exits 0.

Done when
- [ ] the six package kinds are registered and documented
- [ ] `check_content` reports every violation in section 3 with a path and a pointer
- [ ] the boundary test passes

### C7.8 Shared rendering: one dialect, one sanitiser, render at sync

Repository: community-base. Depends on: C7.4. Freeze required: no.

Goal: `content_sync.rendering` is the only renderer and sanitiser for synced content.

Steps
1. Move `knowledge_base/rendering.py` to `content_sync/rendering.py`; keep the lifted DTC
   allowlist and add the attributes of section 4.2.
2. Add heading id injection with DTC's algorithm and the returned heading list; add the
   `mermaid` and `embed` fences; add `COMMUNITY_BASE["MARKDOWN_EXTENSIONS"]`.
3. `curriculum.Unit` and `KnowledgeBasePage` stop rendering in `save()`; the importers supply
   `body_html` (C7.4 step 3 already makes the page accept it).
4. `curriculum/rendering.py` and `knowledge_base/rendering.py` become re-exports.

Verification
- A fixture body with Liquid, kramdown and a `<script>` renders with the first two rejected by
  the validator and the third removed by the sanitiser.
- Heading ids for a fixture equal DTC's `_heading_ids` output for the same input.

Done when
- [ ] one renderer, one sanitiser, no model renders in `save()`
- [ ] the extension hook is documented in the kernel README settings list

### C7.9a Document parser toolkit: collections, front matter, identity, checksums

Repository: community-base. Depends on: C7.7. Freeze required: no.

Goal: `content_sync.documents` turns a checkout plus `content.yaml` into validated
`ParsedDocument` values (core keys, kind keys, body, path, sort key, checksum), so a site parser
no longer walks files or parses YAML.

Done when
- [ ] a fixture repository yields one `ParsedDocument` per item with the checksum covering the
      whole derived record
- [ ] unknown keys, missing `content_id` and duplicate identities are bounded errors naming the file

### C7.9b Document parser toolkit: assets and references

Repository: community-base. Depends on: C7.9a, C7.8. Freeze required: no.

Goal: relative assets are uploaded through `content_sync.media` and rewritten; relative and
typed references resolve through kind route resolvers with `strict_references` semantics; the
resolved reference list is part of the document record; sources are ordered by kind dependency.

Done when
- [ ] a fixture with a sibling link, a `wiki:` reference and a `person:` reference to another
      source resolves, and the unresolved case fails or warns per the flag
- [ ] the `theme_pairs` opt-in emits the paired image markup

### C7.9c Package parsers for wiki, docs and person

Repository: community-base. Depends on: C7.9b, C7.4. Freeze required: no.

Goal: the knowledge base is filled by a package parser for the `wiki` and `docs` kinds, and a
`person` parser fills a package `Person` record that the knowledge base references; sites keep
routes and templates (D16, D18). Requires the owner answer to section 9 question 1.

Steps
1. Register `wiki` and `docs` parsers in `knowledge_base.apps`; store rendered HTML, the heading
   list and the resolved references (the C7.4 record field).
2. Fix `source_content_id` to the item's `content_id`; add a `source` foreign key for the
   ownership scope of `delete_missing`.
3. Remove the fixture parser's need for site code.

Done when
- [ ] a three-level docs fixture with repeated leaf slugs syncs and reads back at its own path
- [ ] AISL's `families/knowledge_base.py` has nothing left to do

### C7.10 One course parser

Repository: community-base. Depends on: C7.9b. Freeze required: no.

Goal: `curriculum/parsers.py` reads the section 3.8 course layout and both
`parsers_aisl.py` and `parsers_dtc.py` are deleted.

Steps
1. Implement the parser over `content_sync.documents` for `course.yaml`, module directories,
   unit documents and `cohorts/<identifier>/cohort.yaml`, producing `ParsedCurriculum`.
2. Map `modules` to `CohortGraph.module_refs`; `archive: true` to an empty placement; `homework`
   bindings to a new `CohortGraph.homework_bindings` tuple consumed by C7.11.
3. Delete both old parsers, their tests and the layout sniffing in `content_sync_parsers.py`.
4. Rewrite `curriculum/README.md` around the one layout.

Verification
- The four AISL and DTC fixtures converted by the section 5 scripts parse to the same graph as
  hand-written expected graphs.
- `uv run pytest tests/curriculum` passes.

Done when
- [ ] exactly one course parser is registered
- [ ] `parsers_aisl.py` and `parsers_dtc.py` are gone

### C7.11 Coursework: homework manifests from cohort bindings

Repository: community-base. Depends on: C7.10, C5.2h. Freeze required: no.

Goal: the coursework app imports `homework.yaml` manifests bound in `cohort.yaml` into
`Homework` and `Question` rows using the answer envelope, and links a binding's `unit` to the
homework unit page.

Done when
- [ ] a bound manifest creates the homework, its questions and their encrypted answers
- [ ] a binding with `unit` renders the submission form on that unit's page
- [ ] AISL's plaintext `questions:` shape is not read anywhere

### C7.12 Conversion scripts and the unified format release

Repository: community-base. Depends on: C7.9c, C7.10, C7.11. Freeze required: no.

Goal: `content_sync/convert/` holds the two conversion scripts of section 5, exercised against
copies of every real content repository, and the package is tagged (playbook P15) with the
format documented in the CHANGELOG.

Done when
- [ ] every one of the sixteen repositories converts on a scratch copy and passes `check_content`
- [ ] the release tag exists and both sites' cross-repo check is green

### A7.2 AISL: adopt the toolkit and the one course parser

Repository: AI-Shipping-Labs/website. Depends on: C7.12. Freeze required: no.

Goal: AISL's `content/sync_parsers/` reads the unified format only: `classify.py`, `parsing.py`
and the tier A family bodies are replaced by the toolkit; tier B kinds (`workshop`, `project`,
`curated_link`, `interview_question`, member wiki) are registered kinds; `sanitize_html` no
longer runs on synced content. AISL `AGENTS.md` and `_docs/PROCESS.md` govern the work.

Done when
- [ ] `make test-affected` passes with the converted fixture repositories
- [ ] a development deploy syncs every AISL source converted on a branch with zero errors

### A7.3 AISL: convert and cut over the content repositories

Repository: AI-Shipping-Labs/website (coordination) and the five AISL content repositories.
Depends on: A7.2. Freeze required: no, a content freeze of one day per repository.

Goal: each repository is converted by the C7.12 scripts on a branch, validated by
`check_content` in its CI, merged in the same hour the A7.2 deploy goes to production, and
synced. Order: `wiki`, `content`, `python-course`, `workshops-content`, `ai-buildcamp-course`
(last, because a paid cohort is running against it; convert from the restructure branch).

Done when
- [ ] every AISL source syncs from `main` with zero errors and zero warnings
- [ ] `scripts/check_workshops.py` and its siblings are deleted from the content repositories

### D7.2 DTC: editorial, people and data kinds on the toolkit

Repository: DataTalksClub/website. Depends on: C7.12, D7.1. Freeze required: no.

Goal: the article, book, podcast, person and data parsers are rewritten over the toolkit,
`SyncedDocument` stays (D21), the everything-under-`images/` media parser is replaced by
referenced-asset upload, and the bleach sanitiser is not applied to synced content. DTC
`AGENTS.md`, `_docs/PROCESS.md` and `_docs/specs/03-github-content-and-people.md` govern the
work; the spec's adapter sections are amended to cite the format.

Done when
- [ ] route and sitemap contract tests pass unchanged for articles, books, podcasts and people
- [ ] the `/images/` route serves the referenced assets of the converted repository

### D7.3 DTC: course repositories on the package course parser

Repository: DataTalksClub/website. Depends on: D5.1, C7.12. Freeze required: no.

Goal: DTC imports its six course repositories through `community_base.curriculum` and
`coursework`, and `courses/services/curriculum_source.py`, `curriculum_import.py`'s schema
branches and the `zoomcamp-ops` checker are retired.

Done when
- [ ] the shared-curriculum route contract passes against a converted repository on development
- [ ] no DTC code parses `course.yaml`

### D7.4 DTC: convert and cut over the content repositories

Repository: DataTalksClub/website (coordination) and the ten DTC content repositories.
Depends on: D7.2, D7.3. Freeze required: no, a content freeze of one day per repository.

Goal: as A7.3, in the order `docs`, `podwiki`, `content` (with `people/` moved in from
`datatalksclub.github.io`), then the six course repositories, `faq` last with the
`content.yaml`-only change.

Done when
- [ ] every DTC source syncs from `main` with zero errors and zero warnings
- [ ] `datatalksclub.github.io` is removed from `CONTENT_SOURCES`

Dependency order: C7.7, C7.4, C7.8, C7.9a, C7.9b, C7.9c, C7.10, C7.11, C7.12, then A7.2 and
D7.2 and D7.3 in parallel, then A7.3 and D7.4. C7.4 is already planned and unchanged; C7.7 can
start now.

## 8. How this subsumes issue 253

| Stage in issue 253 | State | Where it lands here |
|---|---|---|
| A, agree ownership and format on paper with both repositories mapped field by field | done by this document | sections 1 to 3 |
| B, package ownership moves to the course with cohort placement | shipped in C5.1e | unchanged |
| C, nesting in the canonical format | directory nesting is the canonical form | section 3.5, C7.10 |
| D, migrate each content repository | scripted, per repository | section 5, C7.12, A7.3, D7.4 |
| E, retire the second parser | both parsers retire at once because nothing depends on them working (section 6) | C7.10 |

Answers to the three questions the issue asked the owner.

1. Cohort declaration: `cohorts/<identifier>/cohort.yaml` directories only; the inline list is
   dropped from both sites.
2. A cohort may choose a subset and an order of the course's top-level modules (`modules:`) and
   bind homework; it never overrides or extends the tree. Cohort-local module manifests do not
   exist.
3. Retiring the DTC layout is acceptable under the owner's no-compatibility statement, and the
   rewrite is scripted from the existing manifests with no hand edits (section 5).

Issue 253 should be closed when C7.7 is filed, with a link to this document; its remaining
work is the issue list of section 7.

## 9. Open questions for the owner

1. Should the parsers for tier A kinds (course, article, wiki, docs, person) live in the package,
   amending the "each site keeps its own parsers" clause of D16? Recommended answer: yes for
   wiki, docs and person, whose storage is the package app; the course parser already does; the
   article parser stays per site because article storage is site-owned (D21) and each site's
   parser is a thin adapter over the toolkit.
2. Should DTC's `_people` move from `datatalksclub.github.io` into `DataTalksClub/content` as a
   `people/` collection, retiring the Jekyll repository as a sync source? Recommended answer:
   yes; the Jekyll repository is being replaced and only one directory of it is synced.
3. Should the FAQ repository be converted beyond `content.yaml` (adding `content_id` to 1,400
   questions and replacing `{IMAGE:id}` tokens), given `faq_automation/` writes those files?
   Recommended answer: not now; register `faq` as a site kind with its current file shape and
   revisit when the automation is next touched.
4. Should the podwiki's `graph.json` and `search-corpus.json` stay as opaque `data` files built
   by the repository's scripts, or should DTC rebuild the graph from synced references?
   Recommended answer: opaque data now; the rebuild is a DTC-owned follow-up after D7.1 and
   D7.4, when every relation the graph needs is a synced reference.
5. Should the 25 DTC docs pages under `courses/zoomcamp-logistics/` take the paths their
   section parents imply (`/docs/courses/zoomcamp-logistics/start-here/joining/`), or keep flat
   paths by dropping the section grouping? Recommended answer: take the nested paths, since D17
   carries no legacy paths and the grouping is the authors' intent.
6. Are AISL's entitlement keys (`access_mode`, `enroll_url`, `program_label`,
   `maven_course_key`) a package concept, given `COMMUNITY_BASE["COURSE_ACCESS_GRANTS"]`
   already exists, or AISL-only `extra` keys? Recommended answer: `extra` now; promote them when
   DTC or a second program needs them.
7. AISL still syncs events from `events/*.yaml` although D7 says events are Studio-authored on
   both sites. Should that family be retired in the AISL adoption issue? Recommended answer: not
   in this plan; open a separate AISL issue so the content-format work does not carry an events
   decision.
8. Should the `person` kind become the instructor source on AISL (replacing DB-authored
   instructors), or stay optional? Recommended answer: optional; the format defines the shape,
   AISL decides its source in A7.2.
