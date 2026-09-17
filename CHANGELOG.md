# Changelog

## Unreleased

Adoption-provisional. This release contains the nine provisional kept-label migrations listed in `docs/plan/evidence/release-readiness-2026-09-17.md`; `C3.7` and `C4.3` may still rewrite them, and donor adoption happens from `C5.3`, not from this tag.

- C5.2f: peer review gains a second assessment mode for self-paced cohorts. `Project.uses_pooled_review` derives the mode from `Cohort.mode`, so there is no second field to keep in step. `ProjectSubmission.review_state` (`AWAITING_ASSIGNMENT`, `IN_REVIEW`, `SCORED`) carries the per-submission lifecycle in both modes, and the leaderboard and project statistics now read it instead of inferring completion from `Project.state`, which cannot describe a pool. The new `PeerReviewBatch` is the scoring unit for pooled mode: `pooling.try_form_batch` assigns once `number_of_peers_to_evaluate + 1` submissions are waiting, and `pooling.try_score_batch` scores a batch once every review in it is resolved, idempotently and under a row lock. `assign_peer_reviews_for_project` and `score_project` refuse to run against a pooled project, whose `Project.state` never leaves `COLLECTING_SUBMISSIONS` or `CLOSED`. A data migration backfills `review_state` for existing rows from their project's current state.
- C5.2g: a pooled review window expires instead of stalling. `coursework.expire_pooled_reviews`, scheduled every fifteen minutes, moves an unsubmitted pooled review from `TO_REVIEW` to `EXPIRED` once its batch is past `due_at`, then scores the batch as soon as no `TO_REVIEW` review is left; the reviewee falls back to the existing median of available reviews and the reviewer's own `reviewed_enough_peers` already carries the cost of a missed review. `submit_peer_review` rejects a pooled submission only once its batch is scored (`ReviewWindowClosedError`), not at `due_at`. Four event-driven mail purposes ship in `coursework/notifications.py` (`review_assigned`, `pool_ready`, `review_received`, `review_window_expired`), reusing `mail.send`'s own idempotency key rather than a parallel send mechanism, and `reminders.send_peer_review_deadline_reminders` also scans pooled reviews approaching their batch's `due_at`. Installing the app now registers the handler and its schedule at startup.
- C5.2h: certificates become learner-requested. `certificates.certificate_eligibility(enrollment)` is mode-agnostic and reuses existing fields rather than adding gating logic, and `certificates.request_certificate(enrollment)` checks eligibility, calls the configured generator and issues, re-attaching a fresh artifact when a certificate already exists instead of refusing. The artifact comes from a site callable named by `COURSEWORK_CERTIFICATE_GENERATOR`, following the `EVENT_BANNER_GENERATOR` pattern exactly, and raises `ImproperlyConfigured` when unset; the package never sees an endpoint or a token and the artifact format is the site's choice. A session-authenticated member API route `POST courses/<slug>/cohorts/<slug>/certificate-request` and an eligibility column on the Studio certificates list come with it.
- C5.1g: curriculum unit bodies support structured code annotations. An author marks a fenced code block by placing a standalone HTML comment carrying `structured: true` and `code_annotations` immediately after the closing fence; `community_base.curriculum.code_annotations` owns the authoring contract, and `rendering.render_annotated_markdown` expands each annotated block through the overridable `curriculum/annotated_code_block.html` template. The default markup carries structural hooks and no stylesheet, so each site supplies the styling (D18). The contract is the one specified on AI-Shipping-Labs/website#1589, so a body authored for one site parses identically on the other, with two deliberate differences: no pygments and no new dependency, and token substitution instead of positional index matching, which misaligns when a body contains an indented code block. Both sync parsers and `Unit.save` fail closed on a malformed payload, naming the source file, so an invalid body never overwrites a published unit.
- Events: `EventSeries.visibility` (`public` or `hidden`) removes every occurrence of a hidden series from the package's discovery surfaces, that is public listings, sitemaps and feeds, for every viewer. The series and its events stay reachable by direct URL and keep working for recaps and registration. This is separate from `is_active`, which only affects the series' own public page (community-base#249).
- C7.5: `RevisionedModel`, `RevisionConflict`, `AppendOnlyManager` and `AppendOnlyQuerySet` join the kernel in `community_base/kernel/models.py` as shared optimistic-concurrency and append-only bases (decision D19). Abstract and manager-only, so there is no new app, no table and no migration.
- C7.6: the accounts app gains `AccountSession`, a queryable record over Django's own `django_session` table with an added `account_id` column, plus an opt-in `SessionStore` selected through `SESSION_ENGINE` (decision D20). Installing the app never sets `SESSION_ENGINE`, so a site that does not opt in keeps Django's default session behaviour untouched. `erase_member_sessions` and `purge_expired_sessions` ship as services rather than a management command, so no site scheduler is assumed. The migration is provisional: AI-Shipping-Labs already carries this column in production and owns the donor equivalence check under `C3.7`.
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
