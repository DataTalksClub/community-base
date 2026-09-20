# Changelog

## Unreleased

- C7.31: a shared public page must stay usable before a site writes its `cb-`
  rules. Ugly is acceptable; an action that cannot be found is not. Fields and
  the primary action are blocks under the browser default stylesheet. The
  unsubscribe submit is no longer an inline sibling of the last radio label.
  Colour and button chrome stay site-owned (A7.5, D7.6).
- P16: the DataTalksClub consumer job no longer treats Gate B `pyproject.toml` /
  `uv.lock` seal failures as package regressions. The link step rewrites those
  files on every run; playbook P16 already called that an artefact.
- C7.12a: the sanitiser keeps `target="_blank"` on links and `data-event-widget`
  on the event-widget placeholder, so those two site extensions no longer render
  a stripped link or a permanent "Loading" state. Course testimonials may carry
  `company` (D42). Conversion profiles `aisl-content` and `aisl-workshops` exist
  for the two AI-Shipping-Labs repositories that C7.12 left unprofiled. Member
  wiki storage stays an A7.2a ruling: the shipped `aisl-wiki` profile still
  writes the package wiki kind.
- C7.24: wire up two config capabilities that existed in the code and reached no operator.
  `service.unset(key, actor_ref, reason)` had no caller and no test; the Studio settings page now
  has a "clear override" control per database-backed field, which calls it and records the same
  `SettingChange` audit trail a `set` gets. `registry.declare()`'s `requires_restart` flag was
  written and never read; a field declared with it now carries a "Requires restart" badge in
  Studio at the moment the operator edits it, and saving a group that actually changes or clears
  such a field adds a warning message naming the keys that need a restart.
- C7.30: every shared public template owns the `main` landmark. Seven pages that
  previously left it to the site's chrome now wrap themselves in
  `<main class="cb-page">`, matching the other 34, so a site seam that opens no
  `main` gets exactly one on every package public page and a seam that opens one
  is warned (`community_base.kernel.W005`) rather than producing a nested
  landmark on some routes and none on others.

## 0.5.4

- C7.25: shared public templates extend a package-owned seam,
  `community_base/public/base.html`, instead of the site's `base.html` directly. Django drops the
  content of an undefined block in silence, so a site whose chrome names its slots differently was
  serving package pages with the body missing and nothing raised: AI-Shipping-Labs' mounted
  unsubscribe page returned 21kB of chrome and no form. A site whose base defines `title`,
  `meta_description`, `page_head_metadata`, `content` and `extra_js` does nothing and renders
  byte-identically; a site that names them differently overrides that one path and maps its names
  on, instead of forking templates. `manage.py check` now reads the chain above the seam:
  `community_base.kernel.E001` (a missing `content`) is an error, the other four are warnings, and
  `E002` means the chain could not be read. Adopting sites need the override before pinning this,
  because the error is a system check and Django runs those before tests.
- C7.26: Studio impersonation resolves the site's own authentication backend from
  `AUTHENTICATION_BACKENDS` rather than hardcoding `ModelBackend`, and derives its sensitive
  return prefixes from the mounted Studio URLconf rather than from literal paths. A site with only
  a custom backend previously had the operator go anonymous on the next request with no way to
  stop the session, and a site mounting Studio elsewhere had a return guard that matched nothing
  while appearing to work.
- C7.27: three settings whose shape only happened to match one site now fail loudly. An empty
  `SITE_URL` raises at first use instead of silently making outbound mail links relative;
  `STUDIO_EXTRA_CSS` set to a single string is accepted as one path instead of iterating into
  fifteen character-long stylesheet links; and `community_base.curriculum` tests app installation
  with `apps.is_installed()` instead of a string membership test that did not recognise the
  AppConfig spelling Django accepts, which silently unregistered its Studio section and API views.

## 0.5.3

- C7.29: ship the upstream source map referenced by the pinned Lucide Studio bundle so consumer
  deployments can run WhiteNoise `collectstatic` successfully.

## 0.5.2

- C7.28: add the additive absolute `public_url` field to shared event and published curriculum
  course API representations, sourced from the configured canonical site origin.

## 0.5.1 (never tagged)

No `v0.5.1` tag exists. The version bump landed but the release was superseded by 0.5.2 before it was cut, so everything below shipped to sites in v0.5.2. The
section is kept rather than folded away because a reader looking for where C7.19 and C7.20
landed should find them here.

Cut so the two sites can consume fixes that were stranded on `main`. Both sites' source check
accepts only a `vX.Y.Z` tag (D0.2), so nothing here was reachable by a site before this tag.

Note for anyone reading only this file: v0.5.0 shipped a regression, fixed here. C7.13's
mounted-route filter could not serve a Studio URLconf that declares `app_name`, so a site with a
namespaced Studio lost every registered sidebar destination silently. No site had adopted a
namespaced Studio yet, so nothing broke in production.

- C7.19: the Studio serves a URLconf that declares `app_name`, mounted wherever the site puts it.
  A Studio URL module with `app_name` mounts under a namespace, so its routes reverse and resolve as
  `studio:settings`, and v0.5.0 broke that case: `urlconf_route_names` recorded the bare name while
  `reverse()` and the registration needed the namespaced one, so `mounted_sections()` dropped every
  destination registered with `url_name="studio:settings"`, and registering the bare name instead
  rendered an empty href. C7.13 introduced it by adding `mounted_sections()` and the `_is_live`
  filter over that name set; before it nothing filtered on the set and a namespaced `url_name`
  worked. `urlconf_route_names` now records the name the way `reverse()` takes it, joining nested
  namespaces in mount order, and `route_name_for` returns the resolver match's `view_name`, which
  carries the namespace, instead of its bare `url_name`. A route with no name still has no route
  name.

  The C7.22 audit found two more places the same assumption was baked in, and they are fixed here
  rather than left as a follow-up. The shell hardcoded `{% url 'studio_dashboard' %}` and
  `{% url 'studio_global_search' %}`, which is `NoReverseMatch` on a namespaced mount, so every
  Studio page returned 500 rather than losing a link; package templates now link through
  `{% studio_url %}` and package views redirect through `studio_reverse`, both of which read where
  the site mounted the package's Studio URL module. `route_checks` hardcoded the `studio/` prefix,
  so a site mounting the Studio at `manage/` saw every claimed route reported as `claimed but not
  mounted`; the prefix is now found from that same mount, and `studio_routes --check` takes
  `--mount` for a site whose Studio routes live elsewhere.

  A site that mounts Studio at `studio/` without a namespace is unaffected: with no namespace to
  record `view_name` equals `url_name`, the found mount is the old default, and the tests pin the
  namespace-free case against the same routes. A namespaced site registers `url_name` with the
  namespace, which is what `reverse()` needs; `route_names`, `section_only_routes` and
  `routes_without_home` may be written either way, since a bare entry is read in the namespace of
  the destination's own `url_name`, or of the package's Studio mount, so no existing registration
  has to be rewritten. A site that overrides a package Studio template and links to a package route
  with `{% url %}` keeps working on an unnamespaced mount and should move to `{% studio_url %}`
  before namespacing one.

- Studio shell: the icon library is vendored instead of loaded from `unpkg.com/lucide@latest`.
  The shell now serves `community_base/vendor/lucide.min.js`, the unmodified UMD build of lucide
  1.47.0 taken from the npm tarball, from the site's own static files. The old tag was unpinned,
  so whatever unpkg served that day executed on a staff surface, and it was blocked outright by a
  site setting `script-src 'self'`, which left Studio with no icons and no remedy short of forking
  the shell. The script now sits in a `studio_icon_script` block, so a site that already loads
  lucide can empty it rather than download the library twice; emptying it without loading lucide
  elsewhere leaves `data-lucide` elements blank, which is the site's call to make.
  `community_base/studio/static/community_base/vendor/README.txt` records the version, source URL,
  license and sha256, and how to re-derive them. Run `collectstatic` after upgrading.

- Studio shell: `body_start`, an empty block immediately inside `<body>`, and `id="main-content"`
  with `tabindex="-1"` on `<main>`. A site can now put its own skip link on every Studio page
  without replacing the shell. `main-content` is the conventional id and the one DataTalksClub's
  skip link and accessibility tests already target, so it is a contract and will not change. The
  package ships no skip-link markup or styling; a site that overrides nothing renders exactly what
  it rendered before, the landmark id and `tabindex` aside.

- D37: `NullMediaStore`, the default media backend, returns a site-absolute URL instead of the
  repository path. The sanitiser admits an `img src` only when it is site-absolute or an absolute
  `http(s)` URL, so every site running the default backend stored synced images with a source the
  renderer then dropped, and nothing said so until someone looked at a page. The URL is now the
  repository path under `CONTENT_SYNC_NULL_MEDIA_URL_PREFIX`, defaulting to `/media/content-sync/`;
  serving that prefix is the site's job, and a site that serves it nowhere now gets a visible 404
  rather than an invisible omission. A path that escapes the checkout raises `MediaStoreError`
  rather than producing a URL. Behaviour change to a default: a site already relying on the bare
  repository path sets the prefix to `""` to keep a leading slash only.

- `scripts/plan.py check`: a `done` issue whose dependency is not itself `done` or `skipped` is
  now reported, every occurrence rather than the first. Previously `check` only verified that
  dependency ids resolve and that the graph has no cycles, and never compared statuses across an
  edge, so `D2.2b` could read `done` while its dependency `D2.2a` read `in-progress` and `check`
  called the graph clean. The repository has exactly this violation today; it is reported by
  `check` rather than silently fixed by this change.

- `scripts/plan.py check`: a `blocked` row whose `Link` column names an issue that is now `done`
  or `skipped` is reported as a warning. The `Link` column is free text, so this is a scan for
  issue ids inside it rather than a structured field; a Link may legitimately still mention a
  done issue for context, so this never fails `check` on its own. Motivated by `A2.1` having sat
  `blocked` citing `C7.13` and `C7.14` after `C7.14` had merged, so half its stated reason was
  stale. `A2.1`'s row has since moved on and the repository has no such row today, so this warning
  does not fire on the repository as it stands.

- `docs/01-decisions.md` gains an optional `Lands in:` field: a decision that requires
  implementation names the issue that lands it (`Lands in: `C7.12`.`), or states `Lands in:
  none.` when it lands nothing, since not every decision implies an issue (D21 is `site-owned`).
  `scripts/plan.py check` verifies every issue a `Lands in:` field names exists in the phase
  files, and leaves alone the decisions that do not carry the field. Motivated by D34, D38 and
  D39 being written into that file and carried nowhere else, so `FORMAT.md` still contradicted
  them the next day; a decision recorded in one place and implemented in none looks settled in
  review and is not. No existing decision carries the field yet, so this check does not fire on
  the repository as it stands; retrofitting D34, D38 and D39 (landed by C7.12 and C7.18
  respectively) with it is left as a small follow-up.

- C7.18: the kind registry and the reference resolver now implement what decisions D38 and D39
  ruled and `FORMAT.md` already stated. A cohort's `archive` is a mapping with one optional
  `notice_path` defaulting to `README.md`, not a boolean: seventeen real archived cohorts carry the
  mapping and two point at a leaderboard rather than a README, which a boolean cannot express.
  Presence is what archives a cohort, read from the file rather than from the defaulted values,
  because a mapping key defaults to `{}`. Section 3.7's fourth destination form works: a relative
  destination the checkout holds and no collection claims is a repository file, resolving to the
  source's hosting URL, neither uploaded nor recorded as a reference, while a destination the
  checkout does not hold stays an unresolved reference. `resolve_repository` takes `hosting_url` and
  the knowledge-base parser passes the source's GitHub repository at the synced commit, so no
  setting is added; `check_content` has no source and leaves such a destination as written. Real
  lesson bodies link to `code/`, to `.py` and `.ipynb` files and to sibling cohort directories, and
  every one of them failed the sync before this (refs #253).
- C7.12: the package gains the one-off conversion of the sixteen content repositories.
  `community_base/content_sync/convert/` holds two scripts, one for course repositories and one for
  document collections. Both are idempotent, both refuse rather than guess, and both write a
  per-file inventory taken before and after that refuses to call a run a success while one path is
  unaccounted for; every key a rewrite stops writing is printed with the value it held, and a key
  the format cannot express is moved under `extra` rather than dropped. The course script writes the
  cohort `title` that decision D34 makes required, since no real cohort manifest carries one. A
  directory whose every file `ignore` hides is now invisible rather than an empty node, which is
  what section 3.1 already said and what a course repository's archived cohort and tool directories
  need; a declared collection path stays the exception, so an empty collection is empty rather than
  missing. Six of the eight real course repositories convert with no refusal and pass
  `check_content` with zero errors and zero warnings;
  `docs/plan/evidence/conversion-runs-2026-09-18.md` records every run. The directory is deleted
  once the last conversion merges, which is `D7.4` step 9 (refs #253).
- C7.17: a Studio landing page above `STUDIO_NAV_COLLAPSE_THRESHOLD` no longer opens on a sidebar
  of closed headers. The active section is the headerless built-in `home` section there, which has
  no header of its own to expand server-side, so every titled section rendered collapsed; the
  A2.1 cutover (AI-Shipping-Labs/website#1615) found it live, with 52 destinations against the
  default threshold of 24. `registry._apply_collapse_state` now falls through to the first titled
  section, in registry order, whenever the active section is headerless; a section that genuinely
  owns the active route is unaffected, and behaviour below the threshold is unchanged. No new
  setting is added: the alternative considered, a `STUDIO_NAV_DEFAULT_SECTION` naming which section
  to open, would need every adopting site to carry it for a case only the landing page hits.
- Every shared Studio content template now fills its body inside both `{% block content %}` and,
  nested inside it, `{% block studio_content %}`, instead of picking one name. A site that
  replaces `community_base/studio/base.html` outright with its own shell, as both
  AI-Shipping-Labs/website and DataTalksClub/website already do, only ever exposed one of the two
  names, so every package page that had picked the other one rendered as an empty shell -- HTTP
  200, correct title, no body, nothing in the response to say why. `api_keys.html` was the
  reported instance (AI Shipping Labs, community-base#279); a repository-wide check found 59 more
  templates split about evenly between the two names, so both sites had latent broken pages the
  other direction. Filling both names in every package template fixes all 60 without requiring
  either site to change a template. `community_base.studio.checks.check_studio_content_block_contract`
  now runs on every `manage.py check` and fails with `community_base.studio.E001` when a site's
  Studio base replacement exposes neither contracted name, so a genuinely incompatible shell is
  caught at check time instead of shipping a silently empty page (community-base#279).

## 0.5.0 - 2026-09-17

Adoption-provisional. This release contains the nine provisional kept-label migrations listed in `docs/plan/evidence/release-readiness-2026-09-17.md`; `C3.7` and `C4.3` may still rewrite them, and donor adoption happens from `C5.3`, not from this tag.

- C7.11: a cohort's homework bindings become homework and question rows with encrypted answers. `community_base/coursework/manifests.py` reads the `homework.yaml` manifests that `CohortGraph.homework_bindings` names and `community_base/coursework/importing.py` writes them, both inside the one course sync and from the read the course parser already did, so no repository is walked twice and no key is validated twice. The kind registry now states the manifest instead of deferring to the DataTalks.Club shape in prose: `due_at` is required and carries a UTC offset, a question's `type` and `answer_type` are enumerated, `options` are `{id, label}` pairs, and a `KeySpec` of type `mapping` may name its own keys, which is how the cohort form's five keys are checked (`extra` names none and stays opaque). What is left to the reader is the binding half no single file states -- the manifest a binding points at, resolved against the cohort directory and never outside it, whether the cohort places the module it names, whether its `unit` is a `kind: homework` unit of this course, and whether each sealed answer was encrypted for this course, this homework and this question -- each a located error naming the file, the pointer and rule 3.8. Answers are always the envelope: `answer_crypto.validate_source_envelope` runs the check `decrypt_answer` runs before it touches a key, the importer holds none, and the plaintext `Question.correct_answer` column is cleared on every imported row; a plaintext `correct:` key is refused by the registry as an unknown key. Re-import is idempotent and does not restore `initial_state`, which is the state a homework is created in and not one a second sync reimposes. `Homework` gains `module` and `unit` (migration `cb_coursework.0003`, two nullable foreign keys), and the submission form moves into `coursework/_homework_form.html` so a bound unit's page shows the cohort's form and posts it to the one homework view (refs #253).
- C7.10: one course parser replaces two. `community_base/curriculum/parsers.py` reads the course layout of `FORMAT.md` section 3.8 over the document toolkit and maps it onto `curriculum.source`; `parsers_aisl.py`, `parsers_dtc.py` and the layout sniffing that chose between them are deleted, and the curriculum app now registers exactly one `content_sync` parser, `curriculum_course`. Courses come from the `content.yaml` collections rather than from where a `course.yaml` happens to sit, so a repository of three courses imports three and a root-level `course.yaml` is an ordinary course instead of a file to skip. No manifest carries a `schema_version` any more (section 3.1 puts the one version in `content.yaml`), and a retired key -- `prev_url`, `next_url`, `is_homework`, `is_preview`, `access` -- is reported by the toolkit diagnostic that names the file, the pointer and the rule, not by a second rule in the parser. A cohort's `modules` list becomes `CohortGraph.module_refs`, `archive: true` becomes the empty placement, and its `homework` entries become the new `CohortGraph.homework_bindings` that `C7.11` reads the manifests of. Three parser rulings fill silences in section 3.8: a course with no `cohorts/` directory gets one implicit self-paced cohort, a unit carries `required_level` only when it or a module ancestor declares one, and an instructor reference resolves against a `person` collection of the same repository when there is one. No migration ships here (refs #253).
- C7.16: the Studio shell gains its own quick-jump palette and mobile sidebar scroll affordance, closing the last package blocker `C7.15` scoped for the AISL shell cutover. The `studio_quick_jump` block renders a hidden overlay (`data-studio-quick-jump`, `data-testid="studio-quick-jump"`) over the same `data-studio-search` fetch and render code the sidebar box already used; a second endpoint was never written. The package already claimed Ctrl/Cmd-K to focus the sidebar box, so that binding is now centralised: the chord opens the overlay when it is present and falls back to focusing the sidebar box unchanged when a site empties the block. The overlay traps Tab focus, supports ArrowUp/ArrowDown/Enter over the rendered results and restores focus to the element that had it before Escape, backdrop click or Enter closes it. A restricted destination stays absent from the palette for the same reason it stays absent from the sidebar box: both read the one `studio_global_search` response. The mobile sidebar gains `#studio-sidebar-scroll-affordance`, a gradient hint at the foot of the nav, shown only while the sidebar can scroll further and hidden again at the bottom; it sits inside `<nav>` so the existing `studio_sidebar_footer` hook stays empty by default. `static/community_base/studio.css` is rebuilt from `assets/tailwind.css` for the utilities both surfaces need (`bg-gradient-to-t`, `z-[70]`, `rounded-xl`, `shadow-2xl`, `max-h-[min(60vh,32rem)]`, among others); every class the previous build carried is still present.
- C5.2f: peer review gains a second assessment mode for self-paced cohorts. `Project.uses_pooled_review` derives the mode from `Cohort.mode`, so there is no second field to keep in step. `ProjectSubmission.review_state` (`AWAITING_ASSIGNMENT`, `IN_REVIEW`, `SCORED`) carries the per-submission lifecycle in both modes, and the leaderboard and project statistics now read it instead of inferring completion from `Project.state`, which cannot describe a pool. The new `PeerReviewBatch` is the scoring unit for pooled mode: `pooling.try_form_batch` assigns once `number_of_peers_to_evaluate + 1` submissions are waiting, and `pooling.try_score_batch` scores a batch once every review in it is resolved, idempotently and under a row lock. `assign_peer_reviews_for_project` and `score_project` refuse to run against a pooled project, whose `Project.state` never leaves `COLLECTING_SUBMISSIONS` or `CLOSED`. A data migration backfills `review_state` for existing rows from their project's current state.
- C5.2g: a pooled review window expires instead of stalling. `coursework.expire_pooled_reviews`, scheduled every fifteen minutes, moves an unsubmitted pooled review from `TO_REVIEW` to `EXPIRED` once its batch is past `due_at`, then scores the batch as soon as no `TO_REVIEW` review is left; the reviewee falls back to the existing median of available reviews and the reviewer's own `reviewed_enough_peers` already carries the cost of a missed review. `submit_peer_review` rejects a pooled submission only once its batch is scored (`ReviewWindowClosedError`), not at `due_at`. Four event-driven mail purposes ship in `coursework/notifications.py` (`review_assigned`, `pool_ready`, `review_received`, `review_window_expired`), reusing `mail.send`'s own idempotency key rather than a parallel send mechanism, and `reminders.send_peer_review_deadline_reminders` also scans pooled reviews approaching their batch's `due_at`. Installing the app now registers the handler and its schedule at startup.
- C5.2h: certificates become learner-requested. `certificates.certificate_eligibility(enrollment)` is mode-agnostic and reuses existing fields rather than adding gating logic, and `certificates.request_certificate(enrollment)` checks eligibility, calls the configured generator and issues, re-attaching a fresh artifact when a certificate already exists instead of refusing. The artifact comes from a site callable named by `COURSEWORK_CERTIFICATE_GENERATOR`, following the `EVENT_BANNER_GENERATOR` pattern exactly, and raises `ImproperlyConfigured` when unset; the package never sees an endpoint or a token and the artifact format is the site's choice. A session-authenticated member API route `POST courses/<slug>/cohorts/<slug>/certificate-request` and an eligibility column on the Studio certificates list come with it.
- C5.1g: curriculum unit bodies support structured code annotations. An author marks a fenced code block by placing a standalone HTML comment carrying `structured: true` and `code_annotations` immediately after the closing fence; `community_base.curriculum.code_annotations` owns the authoring contract, and `rendering.render_annotated_markdown` expands each annotated block through the overridable `curriculum/annotated_code_block.html` template. The default markup carries structural hooks and no stylesheet, so each site supplies the styling (D18). The contract is the one specified on AI-Shipping-Labs/website#1589, so a body authored for one site parses identically on the other, with two deliberate differences: no pygments and no new dependency, and token substitution instead of positional index matching, which misaligns when a body contains an indented code block. Both sync parsers and `Unit.save` fail closed on a malformed payload, naming the source file, so an invalid body never overwrites a published unit.
- Events: `EventSeries.visibility` (`public` or `hidden`) removes every occurrence of a hidden series from the package's discovery surfaces, that is public listings, sitemaps and feeds, for every viewer. The series and its events stay reachable by direct URL and keep working for recaps and registration. This is separate from `is_active`, which only affects the series' own public page (community-base#249).
- C7.5: `RevisionedModel`, `RevisionConflict`, `AppendOnlyManager` and `AppendOnlyQuerySet` join the kernel in `community_base/kernel/models.py` as shared optimistic-concurrency and append-only bases (decision D19). Abstract and manager-only, so there is no new app, no table and no migration.
- C7.6: the accounts app gains `AccountSession`, a queryable record over Django's own `django_session` table with an added `account_id` column, plus an opt-in `SessionStore` selected through `SESSION_ENGINE` (decision D20). Installing the app never sets `SESSION_ENGINE`, so a site that does not opt in keeps Django's default session behaviour untouched. `erase_member_sessions` and `purge_expired_sessions` ship as services rather than a management command, so no site scheduler is assumed. The migration is provisional: AI-Shipping-Labs already carries this column in production and owns the donor equivalence check under `C3.7`.
- C7.8: `community_base.content_sync.rendering` is the one renderer and the one sanitiser for synced content (`FORMAT.md` section 4). The dialect is python-markdown with `fenced_code`, `tables` and `sane_lists`, without `attr_list` or `md_in_html`, plus two package fences: `mermaid` renders to `<pre class="mermaid">` with its source escaped, and `embed`, a YAML `{type, id}` mapping with `type` in `youtube` or `loom`, renders to a `div.cb-embed` carrying `data-embed-type` and `data-embed-id` around a plain link, so no iframe is ever stored. `render_document` returns the HTML, the `{level, id, title}` heading list and the search text; `inject_heading_ids` uses DataTalks.Club's algorithm, counting repeats from zero, so three `Setup` headings give `setup`, `setup-1` and `setup-2` and DTC's pinned fragment contracts keep resolving. `COMMUNITY_BASE["MARKDOWN_EXTENSIONS"]` appends site extensions to the package list; a site extends and never replaces, and an extension's output still passes the package sanitiser. `knowledge_base/rendering.py` and `curriculum/rendering.py` become imports of the shared module, so existing import paths keep working, and `content_sync/check.py` drops the private copy of the heading-slug algorithm C7.7 left for this issue. `Unit` gains `body_html_source`, the field C7.4 gave the knowledge base page, so a parser can supply rendered HTML that `save()` sanitises and stores unchanged. Two changes to rendered output, both pinned by tests: every heading now carries an id, and unit bodies are held to the shared allowlist, which keeps `<figure>`, `<details>` and `<del>` that the narrower curriculum allowlist dropped, and drops an `img src` that is neither site-absolute nor an absolute `http(s)` URL.
- C7.7: the content format, version 1, is stated normatively in `community_base/content_sync/FORMAT.md` and enforced by `community_base.content_sync.kinds`, a registry of content kinds with the package kinds `course`, `article`, `person`, `wiki`, `docs` and `data`. A site registers its own kinds from `AppConfig.ready()` with `register_kind(name, spec)`; a kind adds keys and never removes, renames or retypes a core key. A kind declares the kinds it depends on, explicitly or through its reference keys, and `kind_order()` turns those declarations into the sync order sources need. `check_content` validates a repository against the format with no database and no site, as `uv run python -m community_base.content_sync.check <path>` or `uv run python manage.py check_content <path>` over one implementation; every diagnostic names the file, a YAML pointer and the rule. Also records, in `SourceProvenanceMixin` and in `knowledge_base.sync`, that `source_content_id` means the item's own `content_id` and that the knowledge base stores the `ContentSource` primary key there instead (repaired with its migration in C7.9c). No migration, no parser and no renderer ship here (closes #253).
- C7.9a: `community_base.content_sync.documents` turns a checkout plus its `content.yaml` into validated `ParsedDocument` values, so no parser walks files, parses YAML or validates keys again. `read_repository(source)` reads a directory or an `ImmutableCheckout`, applies the `ignore` globs, walks each collection through its kind's layout, reads the two file shapes, checks the core and kind keys, derives `slug`, `sort_order`, `required_level` and the ancestor-chain `path`, enforces `content_id` uniqueness across the whole repository and sibling slug uniqueness, and emits a sha256 checksum over the whole derived record rather than over the file bytes, so a file moved without being edited is a changed record. The `data` kind is keyed by its path below the collection root without the extension, which keeps `graph/graph.json` and `search/search-corpus.json` distinct in one collection. Errors are bounded and named: nothing raises, and one pass reports every violation a collection has. `check_content` is now a consumer of this module and adds only sections 3.6, 3.7 and 4.1 on top of it, so the validator and a parser cannot drift apart. The registry gained `default_value`, `applied_defaults` and `resolve_level`, which put every key default in one place. No rendering, no asset upload, no reference resolution and no migration ship here (refs #253).
- C7.9c: the package parses the `wiki`, `docs` and `person` kinds itself (decision D24), and the knowledge base stops overloading one field with two meanings. `community_base.knowledge_base.content_sync_parsers` registers `knowledge_base_person`, `knowledge_base_docs` and `knowledge_base_wiki` from `AppConfig.ready()`; each is thin over the toolkit, reading `read_repository` and `resolve_repository` and mapping what comes back onto the models, and the three share one read and one resolution per checkout so a repository renders once and uploads its assets once. A page stores the shared renderer's HTML and carries the item's resolved values, the heading list, the resolved references and the referenced assets in `record`; a `docs` collection becomes the tree its directories describe, where a leaf slug may repeat under different parents and the collection root's `index.md` is a root page at the collection root itself. `Person` is the new record the `person` kind fills and the target `authors`, `instructors` and `guests` resolve to, through `knowledge_base.routes.route_resolver`, which answers a cross-source reference from the rows already synced; decision D31 keeps the kind an optional instructor source, so no public route and no template ship with it. `KnowledgeBasePage.source` and `Person.source` are the ownership scope `sync.delete_missing` and `sync.delete_missing_people` use, and `source_content_id` now holds the item's own `content_id` and nothing else, as `FORMAT.md` section 3.4 requires; migration `cb_knowledge_base.0006` moves every stored `ContentSource` primary key into the foreign key, drops a value naming a source that no longer exists, and reverses by putting the moved values back. `upsert_page` gains `status` and `content_id` and `upsert_person` joins it; a site parser that passes neither keeps the behaviour it had, so rows written before this release survive unchanged (refs #253).
- C7.9b: `community_base.content_sync.resolution` is the resolving half of the document toolkit (`FORMAT.md` sections 3.6 and 3.7). `resolve_repository(read_result)` resolves every relative asset and every cross-reference against the repository, uploads the assets a document actually references through `content_sync.media` keyed by the repository path, rewrites both in the rendered HTML and in the stored asset keys, and returns the reference list a record stores as `{kind, target, label, href}`. An unreferenced file is not an asset and is not uploaded; an asset may live outside every collection; a file matched by `ignore` is invisible as an asset too, so referencing it is an unresolved reference. Every asset passes the allowed types, the 16 MiB maximum and the donor's signature and unsafe-SVG checks, now `media.asset_payload_defect`, before upload. The three destination forms of section 3.7 resolve -- a relative file link inside one collection, a typed `kind:slug` or `kind:path`, and an external URL left alone -- for body links and for front-matter references alike, including the fixed-kind keys `authors`, `instructors` and `guests` written without a prefix; `strict_references: false` degrades an unresolved reference to a warning and drops the link while keeping its label. `order_sources` turns the declared `depends_on` graph into the sync order, so no source list is hand-written, and `theme_pairs` emits a `name.dark.ext` sibling as two `<img>` tags carrying `data-theme-figure` and the `cb-theme-figure` classes a site styles. Rewriting happens between the heading ids and the sanitiser, through the new `rendering.render_html` seam, because a relative `img src` does not survive the allowlist; there is still one markdown pass and one allowlist. `check_content` is now a consumer of this module and owns only the markdown dialect of section 4.1, so seven fixtures the validator alone used to reject are rejected by the toolkit too. No migration ships here (refs #253).
- C7.4: the knowledge base page can be identified, routed, rendered and described by the site. Its slug is now unique per `(section, parent)` instead of per section, so a leaf segment may repeat under different parents, and a slug may be a `/`-joined path. `public_path` stores a site-owned URL that `get_absolute_url` returns when set. `body_html_source` lets a site supply already-rendered HTML that `save` sanitizes and preserves instead of re-rendering the markdown body. `record` is one JSON object of site-owned metadata the package never interprets. `sync.upsert_page` carries all of them plus `parent_path`, and `sync.delete_missing` accepts `seen_source_paths`. Backward compatible: a page with no public path, no supplied HTML and no record keeps the behaviour v0.4.7 shipped (unblocks D7.1).
- C7.4: `rendering.sanitize_rendered_html` now passes nh3 the attribute allowlist its `_allowed_attribute` filter was written against. nh3 consults the filter only for attributes its own allowlist already admits, so `class`, `id`, `lang` and `title` were being dropped before the filter was asked -- including the heading ids a site's table of contents links to. Everything the filter rejects is still stripped, and the app's markdown extensions emit none of these attributes, so bodies rendered by the app are unchanged.
- C7.14: the Studio sidebar collapses. Sections collapse with per-viewer persistence, and the section owning the active route is expanded server-side, so a stored collapse cannot hide the current page even with JavaScript disabled. Behaviour is unchanged below `COMMUNITY_BASE["STUDIO_NAV_COLLAPSE_THRESHOLD"]`, default 24, and the package's own registry is 21 destinations across 9 sections. A `Destination` gains optional `icon`, `external_url` and `new_tab`, so a destination may carry an icon and link outside the URLconf. The shell gains an empty `studio_sidebar_footer` block and an opt-in theme-toggle hook, while the version string, back-to-website URL and toggle chrome stay site-owned. Studio search results render grouped under their provider headings, and stay visible when `studio-nav.js` is absent.
- Studio's global search now matches destinations registered inside a `DestinationGroup`, not only flat section destinations. A grouped match carries its section and group in `summary` (joined with ` · `) so the client places it correctly, and the same superuser and feature-flag visibility rules that hide a flat destination hide a grouped one (AI-Shipping-Labs/website#1615).

## 0.4.7 - 2026-09-17

- Import the accounts email-resolution service lazily in the events registration, guest-invitation and anonymous-registration paths, so a site can install the package events app without adopting shared accounts (D4.1).

## 0.4.6 - 2026-09-16

- Move `SourceProvenanceMixin` and `provenance_constraint` to the app-neutral `community_base.content_sync.provenance` (`curriculum.models` re-exports them): the knowledge base no longer imports curriculum models, so a site can install it without the package curriculum or events apps (A7.1).

## 0.4.5 - 2026-09-16

- Import the events `Host` lazily in the curriculum importer so the sync parsers register on sites that install curriculum without the package events app (A7.1).

## 0.4.4 - 2026-09-16

- Curriculum's events-dependent API and Studio surfaces register only when the package events app is installed, so a site can install `community_base.curriculum` for the knowledge base provenance models without owning the package events tables (A7.1).

## 0.4.3 - 2026-09-16

- Restore `config.service.unset`, which a merge resolution dropped after v0.3.9: sites calling it failed startup against v0.4.0 to v0.4.2.

## 0.4.2 - 2026-09-16

- Restore the `requires_restart` declaration metadata that `declare()` accepted at v0.3.9 and a merge resolution dropped: sites declaring restart-affecting keys failed startup against v0.4.0 and v0.4.1.

## 0.4.1 - 2026-09-16

- C7.2: ship the knowledge base fixture repository as regular files instead of a mode-160000 gitlink, so git-dependency installs (uv, pip) resolve the package and fresh clones run the fixture tests.

## 0.4.0 - 2026-09-16

- C4.1e: remove `EventAlias`, `add_alias`, the `event_alias` view and the trailing `<path:alias>/` route (decision D17). An event is addressed only by its canonical URL and a path below `events/` that matches no event returns 404. Breaking for any site that mounted the alias route, created `EventAlias` rows, or resolved superseded paths through them.
- C7.2: add the `knowledge_base` app (`cb_knowledge_base`): wiki and documentation pages with `content_sync` provenance, the donor docs hierarchy resolution, the lifted donor sanitizer allowlist, a search-corpus service, Studio inspection screens and overridable default public routes for `/wiki/` and `/docs/` (community-base#260).

## 0.3.9 - 2026-09-13

- C6.2a: surface the verified email on the double opt-in `RelayVerificationConfirmation` so the adopting site can mirror the confirmation onto its own user (cherry-pick of main 68b3593).

## 0.3.8 - 2026-09-13

- C6.2a: surface the verified email on the double opt-in `RelayVerificationConfirmation` so the adopting site can mirror the confirmation onto its own user.

## 0.3.7 - 2026-09-12

- C6.2: add the Relay contacts, subscriptions and tags clients (`RelayContactsClient`) with FakeRelay contract coverage; contact-level callbacks record transition `sequence` and `occurred_at` and emit `relay_callback_processed` for site `unsubscribed` and `bounce_state` updates.

## 0.3.6 - 2026-09-12

- Studio: add nested destination groups and the `COMMUNITY_BASE["STUDIO_EXTRA_CSS"]` shell stylesheet hook (community-base#220).

## 0.3.5 - 2026-09-12

- A0.2: clear blank optional integer overrides with audited `service.unset`, and expose restart metadata and save feedback.
- A1.2: preserve SES reply-to, configuration sets, plain text, backend key declarations and worker context enrichment from later releases.
- Maintenance release based on `v0.3.0`; excludes later provisional kept-label capabilities.

## 0.3.4 - 2026-09-12

- D2.1: add the `STUDIO_AUTHORIZER` hook so a site can replace the default `is_staff` check on shared Studio views.

## 0.3.3 - 2026-09-11

- A1.2: ses_local's registry declarations, including `SES_FROM_EMAIL`, become `declare_if_absent` with package docs metadata so every contributed key stays documented when the site declares nothing.

## 0.3.2 - 2026-09-11

- A1.2: add `declare_if_absent` so sites that already declare backend operational keys keep their operator metadata; ses_local's AWS keys use it.

## 0.3.1 - 2026-09-11

- A1.2: ses_local gains `reply_to` and `configuration_set` transport options and sends a derived plain-text part next to the HTML part.

## 0.3.0 - 2026-09-05

- C2.1a: Add the shared Studio shell, registry, route checks, assets, search and security controls.
- C2.1b: Integrate configuration, API key, durable jobs and mail operations into Studio.
- C2.2: Add generic Studio user list, detail, export, tags and notes with extension registries.
- C2.3: Add immutable content sync, GitHub webhooks, durable dispatch, S3 media, Studio and API.

## 0.2.0 - 2026-09-05

- C1.1a: Add durable jobs, local backends, signed ingress, schedules, commands and Studio.
- C1.1b: Add Relay task, lease, schedule and health clients with FakeRelay contract coverage.
- C1.2a: Add durable mail, memory delivery, callbacks, recipient links, Studio and scoped API.
- C1.2b: Add Relay mail send, signed callbacks, reconciliation and template catalog clients.
- C1.3: Add the transitional SES-local backend with AISL rendering parity and lifecycle hooks.
- C1.4: Export deterministic jobs, mail, Relay and signed-request testing helpers.

## 0.1.0 - 2026-09-05

- C0.1: Create the package repository skeleton.
- C0.2: Add the model-free kernel settings, hooks, access and service primitives.
- C0.3: Add typed runtime configuration with encrypted storage, audit, Studio and scoped API.
- C0.4: Add scoped API keys, Bearer authentication, route registry, safety and OpenAPI.
