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

