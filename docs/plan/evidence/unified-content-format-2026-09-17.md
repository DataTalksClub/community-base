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

