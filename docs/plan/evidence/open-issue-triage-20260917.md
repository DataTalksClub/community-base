# Open issue triage, 2026-09-17

Read-only triage of open `DataTalksClub/community-base` issues that are not plan issues (249,
252, 253, 255, 256), plus confirmation of the plan issues still open as GitHub issues (258, 269,
270, 271, 272, 273, 274). Method: `gh issue view <n> --repo DataTalksClub/community-base` for the
ask, then grep and read the concrete code on `main` to check whether it is already implemented.
For the four `undecided` rows in the `C7.1` candidate table, read-only research in
`/home/alexey/git/dtc-website` and `/home/alexey/git/ai-shipping-labs` (no files modified there).

## Part 1: non-plan issues

| Issue | Title | Verdict |
|---|---|---|
| 249 | Package gap: EventSeries.visibility | real outstanding work |
| 252 | Curriculum nesting: submodules and typed unit elements | partially done |
| 253 | Unify course sync: one content format and one importer | partially done |
| 255 | Port course code-line highlighting and annotations | not implemented |
| 256 | Peer review modes, pooled self-paced review, email, certificates | already done |

### 249, EventSeries.visibility

Ask: add `visibility` (`public`/`hidden`) to `community_base.events.EventSeries`, hiding every
occurrence of a hidden series from all discovery surfaces while keeping detail/recap pages open
to staff and entitled members.

Code check: `community_base/events/models.py:63` defines `class EventSeries`, with fields through
`cadence` at line 68. No `visibility` field exists anywhere in that file (`grep -n visibility
community_base/events/models.py` returns nothing). `community_base/events/` has no
`related_content` module and no `is_entitled_for_series`-style helper; the package events app
does not yet model an "enrollment gates a hidden series" concept at all.

Verdict: real outstanding work, not started. Size is small to medium: one field plus choices, an
`is_hidden` property, exclusions in the existing listing queryset(s) and the ICS feed
(`community_base/events/integrations/calendar.py`), and a new entitlement bridge to
`curriculum.Enrollment` (the package has no cross-app hook for this today, so that seam is new
work, not a copy). The issue itself frames this as landing when `A4.1` (events-into-package
migration, still `todo`) happens, so it is reasonable to leave open rather than build ahead of the
donor migration, but the field itself does not technically require `A4.1` to land.

### 252, curriculum nesting

Ask: `Module.parent` (self-FK, submodules), `Unit.kind` (lesson/homework/event), `Unit.event` FK,
depth-first reading order, importer support for nested module directories, Studio tree editing
with reparenting, and a serializer/API shape carrying the nesting.

Code check, what shipped in `C5.1e` (PR #254, merged, `docs/plan/STATUS.md` marks it done):

- `Module.parent`: `community_base/curriculum/models.py:329`, nullable self-FK,
  `related_name="children"`, with depth/cycle/same-course guards in `clean()` (lines 387-404).
- `Unit.kind`: `community_base/curriculum/models.py:45-53` (`UNIT_KINDS` tuple: lesson, homework,
  event, checklist_item — the last added later by C5.1f), field at line 468.
- `Module.is_bonus` / `Unit.is_bonus`: present, excluded from the progress denominator in
  `Course._countable_units` (`community_base/curriculum/models.py:155-170`).
- Depth-first reading order: `get_all_units_ordered` in
  `community_base/curriculum/services.py:166-196`, reused by `get_next_unit`/`get_prev_unit`.
- Importer support for nested directories in both parsers: `community_base/curriculum/
  parsers_aisl.py:7-15,138-140` (recursive walk, two-level cap) and
  `community_base/curriculum/parsers_dtc.py:94-145` (one extra nesting level in shared and
  cohort-local manifests).
- `Unit.event` FK was deliberately not built. A comment thread on the issue itself
  (2026-09-16, "AI Shipping Labs implementation diverges from Unit.event") records why: a direct
  FK to one cohort's `Event` breaks under concurrent cohorts. `Unit.session_position`
  (`community_base/curriculum/models.py:478-486`, a plain `PositiveIntegerField`) replaces it,
  resolved per-viewer at render time. This is a recorded, reasoned divergence, not a gap.

What did not ship, confirmed by grep and read:

- Studio reparenting: `ModuleForm` (`community_base/curriculum/studio_forms.py:45-53`) has no
  `parent` field in its `Meta.fields` tuple, so a module cannot be made a submodule, or moved,
  through Studio. `studio_views.py` has `module_create`/`module_edit`/`module_delete` but no
  submodule-under-module route.
- Public views/templates only resolve top-level modules: `community_base/curriculum/views.py:31,
  110,132` all filter `Module.objects.get_object_or_404(..., parent__isnull=True, ...)`. A
  submodule's own page, and breadcrumbs through it, are not wired.
- No API/serializer surface carries the tree: `community_base/curriculum/api_views.py` only
  exposes enrollment, certificate and instructor endpoints, nothing for modules/units.
- Open design question left unresolved on the issue itself (owner comment, 2026-09-16): whether
  `kind="event"` and a self-paced "recording" are one kind or two, and how progress carries across
  a learner switching cohort mode. Not decided, not built.

Verdict: partially done. The model layer, the depth-first ordering, and both importers are done
and released in `C5.1e`. Studio tree editing, public submodule pages/breadcrumbs, and an API shape
for the tree remain, plus one unresolved design question. Do not close; either update the issue
to record what shipped and re-scope the remainder, or split the remainder into new issues.

### 253, unify course sync

Ask: one canonical content format and one importer shared by both sites, settling first who owns
a curriculum (per-cohort copy vs per-course tree with cohort placement).

Code check: the ownership question is answered and shipped. `Module.course` FK
(`community_base/curriculum/models.py:328`) replaces the old per-cohort `Module.cohort`, and
`CohortModule` (`community_base/curriculum/models.py:420`) is the placement table — one module
tree per course, cohorts place a subset/order of it, matching DTC's own `CohortSharedModule`
design. This is confirmed by the investigation the issue's own comment thread records
(2026-09-16, reading DTC's `courses/services/curriculum_flow.py` and
`courses/models/shared_curriculum.py`) and by `C5.1e`'s PR body, which cites this issue directly.

What remains: `community_base/curriculum/` still ships two separate parsers,
`parsers_aisl.py` and `parsers_dtc.py`, with materially different root-manifest shapes (AISL:
`course.yaml` only; DTC: `course.yaml` plus `SITE.md` plus `cohorts/<id>/` directories). `C5.1e`
added nesting support to both parsers independently rather than converging them onto one format.
The issue's own staged plan (stage A ownership+format agreed, B package ships it, C nesting in the
canonical format, D migrate each content repository, E retire the second parser) is only through
stage B for ownership; stages C to E (one format, real repository migration, parser retirement)
have not happened.

Verdict: partially done. The harder, structural question (who owns a curriculum) is settled and
built. The part actually named in the title ("one content format and one importer") is still two
formats and two parsers. Real outstanding work remains and is not blocked on anything else in the
plan; it is a design-and-migration effort (stage A format spec, then stages D/E), not started.

### 255, code-line highlighting and annotations

Ask: port AI Shipping Labs' code-annotation parser/renderer
(`content/utils/code_annotations.py` on that site) into `community_base`, wired into unit
rendering and sync-time validation.

Code check: `grep -rln "annotated-code-block\|code_annotation\|code-annotation" .` from the
package root returns nothing. No file named anything like `code_annotations.py` exists under
`community_base/`. `community_base/curriculum/rendering.py` (named in the issue as the likely
home) has no annotation-related functions.

Verdict: not implemented. Real outstanding work, medium size: a battle-tested reference
implementation exists on the AISL site per the issue (not independently re-verified here, out of
scope for this triage), so this is a port-with-tests job, not a design job. The issue itself notes
it should be sequenced after PR #254 (now merged), so it is unblocked and ready to pick up.

### 256, peer review modes, pooling, email, certificates

Ask, broken into four "genuinely new" asks by the issue: explicit mode selection (not inferred
from data shape), email notifications for pool-ready/assigned/received/deadline events,
certificate issuance on request rather than automatic, and certificate artifact generation via a
site-configured banner-generator seam.

Code check, all four confirmed present in `community_base.coursework`:

- Explicit mode selection: `Cohort.mode` (`cohort`/`self_paced`,
  `community_base/curriculum/models.py:250`, unique constraint at lines 269-270) is the explicit,
  operator-set field. `Project.uses_pooled_review` (`community_base/coursework/models.py:378-386`)
  derives from it by design, per the property's own docstring, rather than inferring a mode from
  whether a submission has a cohort.
- Pooling with a deadline: `community_base/coursework/pooling.py:52-90`, `try_form_batch` forms a
  batch once `number_of_peers_to_evaluate + 1` submissions are waiting, and sets
  `due_at = now + project.pooled_review_window_days`
  (`community_base/coursework/models.py:362`, a per-project field) — answering the issue's open
  question 3 about a pooled-review deadline.
- Email notifications: `community_base/coursework/notifications.py` defines
  `REVIEW_ASSIGNED_PURPOSE`, `POOL_READY_PURPOSE`, `REVIEW_RECEIVED_PURPOSE`,
  `REVIEW_WINDOW_EXPIRED_PURPOSE` (lines 21-24), each sent through `mail.send` (a real durable
  outbox email, not only the on-platform `Notification` row the issue said existed before).
- Certificate on request: `community_base/coursework/certificates.py:67` `certificate_eligibility`
  and line 109 `request_certificate`. The module's own docstring (lines 12-18) states this is a
  package feature addition, not a behavior change within the package, since the package never had
  automatic issuance — so the issue's open question 1 (what happens to learners who already
  qualify under automatic issuance) is a site-level (AISL `A5.1`) migration concern, not a
  package gap.
- Certificate artifact via banner-generator: `community_base/coursework/integrations.py`,
  `generate_certificate_artifact` calls a site-configured `COURSEWORK_CERTIFICATE_GENERATOR` hook,
  mirroring the existing `events.EVENT_BANNER_GENERATOR` seam exactly, keeping the package free of
  a hardcoded client.

All of this shipped across `C5.2f` (PR #257), `C5.2g` (PR #262) and `C5.2h` (PR #263), all marked
`done` in `docs/plan/STATUS.md`.

Verdict: already done, matching the hint that this corresponds to C5.2f/g/h. Recommend closing
#256. The only thing left is site-side: wiring the AI Hero course into self-paced mode and
verifying end to end, which is a site deployment task, not a `community_base` package gap.

## Part 2: plan issues still open as GitHub issues

| Issue | Plan id | Verdict |
|---|---|---|
| 269 | C0.6 | already done, confirmed |
| 270 | C3.7 | blocked, not startable |
| 271 | C4.3 | blocked, not startable |
| 272 | C5.1f | already done, confirmed |
| 273 | C5.3 | blocked, not startable |
| 274 | C6.1 | blocked, not startable |
| 258 | C7.1 | real outstanding, decision needed (see part 3) |

### 269, C0.6 (confirmed)

`.github/workflows/cross-repo-check.yml:39-42` triggers on `push`, `pull_request` and
`workflow_dispatch`. `docs/01-decisions.md:28-35` records D15, scoped exactly as the issue asks
(this package's own CI only, ephemeral site checkouts, D0.2 and site CI unaffected), with a
separate note (lines 30-32) that branch-protection enrollment stays an owner setting. Playbook P16
(`docs/03-playbooks.md:344-361`) and the `AGENTS.md:102` pointer both describe the narrowed,
always-on exception rather than the old "advisory, weekly" framing. Matches the "Done when"
checklist in the issue exactly. Should be closed; `docs/plan/STATUS.md` already marks it `done`
against PR #277.

### 270, C3.7 (blocked)

Depends on `C3.6` (done), `A3.2` (todo, AI-Shipping-Labs/website#1692) and `D3.1e` (todo,
DataTalksClub/website#394, itself blocked behind `D3.1a`-`d`, all `todo`/`in-progress`). Cannot
start until both site-side prerequisites land. Leave open.

### 271, C4.3 (blocked)

Depends on `C4.2` (done) and `A4.1` (todo, AI-Shipping-Labs/website#1694). Leave open; this is also
the migration #249's `visibility` field is meant to ride along with.

### 272, C5.1f (confirmed)

`community_base/curriculum/models.py:48` defines `UNIT_KIND_CHECKLIST_ITEM`, included in
`UNIT_KINDS` at line 53. `Course._countable_units` (lines 155-170) excludes it from the progress
denominator, with a docstring explaining why. `community_base/curriculum/services.py:233`
`get_checklist_items`, line 240 `ChecklistItemState` (frozen dataclass), line 253
`get_checklist_state`. Every "Done when" box in the issue is met. Merged as commits `202bcb9` and
`ee82f30`. Should be closed; `docs/plan/STATUS.md` already marks it `done`.

### 273, C5.3 (blocked)

Depends on `C3.7` and `C4.3`, both still `todo`. Cannot start; the release itself explicitly must
not go out with the still-provisional identity and events migrations. Leave open.

### 274, C6.1 (blocked)

Depends on `A6.4` (todo, AI-Shipping-Labs/website#1700, a freeze-weekend issue). Leave open.

## Part 3: C7.1 candidate table, the four undecided rows

Research method: read-only, in `/home/alexey/git/dtc-website` and
`/home/alexey/git/ai-shipping-labs`, no files changed in either. File:line citations below are
against each repository's working tree as checked out during this triage (DTC head `3787481` for
the capability-declaration count).

### Capability declaration for Studio and admin API

Today: DTC has it, AISL has none. The candidate table cites 61 capabilities; a live count on DTC
head `3787481` (2026-09-17) gives 46 (`len(CAPABILITY_REGISTRY)`), one day after the evidence
doc's 61 figure with no capability-removing commit in between. Re-count before deciding; use 46,
not 61.

The mechanism: `core/capabilities.py` (344 lines) defines `AdapterMetadata`, a frozen `Capability`
dataclass (binding one service function to a Studio route, an admin-API route, permission,
idempotency/concurrency policy, audit action and redacted fields), `validate_capability`
(fail-closed structural validation) and `CapabilityRegistry` (raises at construction on any
invalid or duplicate entry). This file has no Django or DTC-model imports; it is generic.
`management_registry.py` (188 lines) is DTC's composition root, importing every app's
`*_CAPABILITIES` tuple. Consumption is `management_api/dispatch.py`'s `admin_capability(key)`
decorator (44 call sites), plus `studio/views.py`, `studio/auth.py` and `studio/checks.py`.

Coupling: the core dataclasses/registry are generic, but the 46 concrete declarations are DTC
domain code (sponsors, event Q&A, historical-registration imports, OAuth providers, credentials),
and the dispatcher additionally depends on DTC's own idempotency/rate-limiting/audit machinery,
which does not exist in the package today.

AISL: confirmed no equivalent. The nearest match, `api/openapi/decorator.py` (97 lines,
`@openapi_spec`), is a build-time-only documentation annotation with no runtime enforcement, no
Studio binding, no idempotency/audit/redaction coupling.

Package precedent: `community_base/api/registry.py` already has its own `@route` decorator (a
`Route` dataclass, method and path only) and `community_base/studio/registry.py` has a
`Destination`/`Section` sidebar registry. Neither matches DTC's unified shape, so absorbing DTC's
pattern means reconciling with, or superseding, two existing package registries — a design
decision, not a file move.

Recommendation: partial, deferred. Converge only the generic ~344-line mechanism into the package,
once it is reconciled against the existing `api.registry`/`studio.registry` shapes. Leave DTC's 46
declarations, `management_registry.py`, and the audit/rate-limit-coupled dispatcher DTC-owned;
they are domain code, not infrastructure.

### Optimistic concurrency and append-only model bases

Today: DTC only. The mechanism lives in `core/models.py:16-114` (about 100 of the file's 633
lines): `AppendOnlyViolation` and `RevisionConflict` exceptions, `AppendOnlyQuerySet` (overrides
`update`/`delete`/`bulk_create`/`bulk_update` to raise, with one narrow carve-out for
`AuditEvent` retention), `AppendOnlyManager` (a thin `from_queryset` wrapper), and
`RevisionedModel` (abstract, adds a `revision` field and a conditional
`UPDATE ... WHERE pk=... AND revision=<previous>` in `save()`, raising `RevisionConflict` on zero
rows matched — a portable compare-and-swap that works on both SQLite and Postgres).

Usage: 11 models inherit `RevisionedModel` across `core`, `management_auth`,
`historical_registrations` and `content` (`OperationalSetting`, `Sponsor`, `SiteNavigationMenu`,
`Operation`, `APIPrincipal`, `APICredential`, four historical-registration models, `ContentSource`,
`ContentRelease`). `AppendOnlyManager` has exactly one consumer, `AuditEvent`. The mechanism itself
has no domain imports — comparable in shape to `TimestampedModel`, which is currently duplicated
per package app rather than living in one place.

AISL: confirmed no equivalent. AISL's concurrency strategy is pessimistic `select_for_update()`,
used pervasively (roughly 50 call sites), a different paradigm, not a partial version of the same
thing.

Package fit: `community_base/kernel/` currently has no `models.py` at all, so this would be the
first kernel-level base model.

Recommendation: converge into the kernel. It is small (about 100 lines), clean, domain-agnostic,
proven against 11 real consumers, and fills a real gap (AISL has no portable optimistic-concurrency
primitive, and DTC's admin API already assumes these bases exist). The 11 consuming models
themselves stay DTC-owned; only the base classes move.

### Custom session model

Today: AISL only. `AccountSession` (`accounts/models/session.py:5-18`, 19 lines total) is a thin
`AbstractBaseSession` subclass adding one field, `account_id` (indexed, nullable), mapped
`managed = False` onto Django's own `django_session` table — a queryable view, not a parallel
table. No device info, no IP, no "sign out everywhere" flag, no admin UI. `accounts/
session_backend.py:17-32` (32 lines) is a `SessionStore(DatabaseSessionStore)` subclass that
populates `account_id` from the session payload's `_auth_user_id`, wired in purely through the
standard `SESSION_ENGINE` setting — no middleware, no signals, no special cache backend.

Consumers: exactly two outside tests. `accounts/services/privacy.py` (GDPR erasure, deletes rows
by `account_id`) and `jobs/tasks/cleanup.py` (a scheduled job that clears expired rows and
backfills `account_id` for legacy rows).

`community_base/accounts/` today has no session-related code at all.

DTC: confirmed no equivalent. DTC has an unrelated `StaffSession` model
(`core/models.py:185`) for Studio staff-impersonation audit, which never stores a browser cookie
key — a different concept, not a session-tracking mechanism.

Recommendation: converge into the accounts app. This is the cheapest of the four candidates: about
50 lines of mechanism total, no AISL-specific infrastructure dependency, generic against any
`AUTH_USER_MODEL` (it reads `_auth_user_id` off the session payload, not a hardcoded model name),
and only two call sites to port, both of which are exactly the kind of generic
privacy/cleanup service the package's `accounts` app would want regardless.

### Article storage shape

Today: AISL has a concrete `Article` model; DTC has a generic synced document.

AISL: `content/models/article.py:28-223`, a plain Django model with about 20 typed fields (title,
slug, markdown and rendered HTML body, cover image, banner fields, date, author, tags, page type,
status, a `source_event` FK). `save()` (lines 146-194) carries real logic: markdown rendering, tag
normalization, reading-time calculation, excerpt generation, banner-hash bookkeeping. It is
authored two ways: synced from a git repository via
`content/sync_parsers/families/articles.py` (414 lines), which itself runs through
`community_base.content_sync` (AISL already has a content-sync pipeline, contradicting any
assumption that adopting sync-only storage would be new for AISL); and edited directly in
Studio/admin (`content/admin/article.py`, `studio/views/articles.py`). 34 non-test files touch
`Article.objects`.

DTC: no dedicated Article model. `content/models.py:738-791` defines a generic `SyncedDocument`
(12 fields, including an opaque `record` JSONField) shared by 11 content kinds registered through
`register_parser` (articles, faq, podwiki, people, slack, books, podcasts, course, docs, media,
platforms). Article-specific fields live inside the JSON blob, produced by
`content/sync_parsers/articles.py`. A separate typed projection layer
(`content/article_content.py`, `content/catalogue.py`) turns the JSON into safe rendering data.
There is no direct-edit UI; DTC articles are git-only. `community_base/content_sync/models.py`
itself ships no generic document model (only `ContentSource`/`SyncLog`/`WebhookLog`) — DTC's
`SyncedDocument` is a site model, not something already shared.

Tradeoff: converging AISL onto DTC's shape loses AISL's direct Studio/admin editing (14 or more
call sites) and the model-level business logic in `save()`, forcing JSON-blob access plus a new
projection layer. Converging DTC onto AISL's shape means giving DTC's 11-content-kind generic
table a dedicated model per kind, a change far larger than "articles," for a site that has no
editing workflow to gain from it.

Recommendation: keep separate, site-owned. The genuinely shared part (sync orchestration,
checkout, webhooks) is already unified through `community_base.content_sync`. The divergence in
persistence shape is a deliberate fit to each site's real workflow, and forcing one shape optimizes
neither site while risking a much larger ripple through DTC's other ten content kinds.

## Summary of recommended next actions

- Close 256, 269, 272 — implemented and verified against the code on `main`.
- Update or split 252 and 253 — most of the design work shipped in C5.1e; each issue should be
  re-scoped to the concrete remainder (Studio tree editing, public submodule views, API shape, and
  the event/recording design question for 252; canonical format plus parser retirement for 253)
  rather than left as-is implying nothing happened.
- Leave 249 and 255 open as real, unstarted work.
- Leave 270, 271, 273, 274 open; each is correctly blocked on a site-side prerequisite that is
  still `todo`.
- 258 (C7.1) needs an owner decision on the four candidates above before it can close; this
  document is the research input for that decision, no decision is recorded here.
