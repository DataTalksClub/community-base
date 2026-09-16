# Changelog

## 0.4.3 - 2026-09-16

- Restore `config.service.unset`, which a merge resolution dropped after v0.3.9: sites calling it failed startup against v0.4.0 to v0.4.2.

## 0.4.3 - 2026-09-16

- Restore `config.service.unset`, which a merge resolution dropped after v0.3.9: sites calling it failed startup against v0.4.0 to v0.4.2.

## 0.4.4 - 2026-09-16

- Curriculum's events-dependent API and Studio surfaces register only when the package events app is installed, so a site can install `community_base.curriculum` for the knowledge base provenance models without owning the package events tables (A7.1).

## 0.4.4 - 2026-09-16

- Curriculum's events-dependent API and Studio surfaces register only when the package events app is installed, so a site can install `community_base.curriculum` for the knowledge base provenance models without owning the package events tables (A7.1).

## 0.4.5 - 2026-09-16

- Import the events `Host` lazily in the curriculum importer so the sync parsers register on sites that install curriculum without the package events app (A7.1).

## 0.4.5 - 2026-09-16

- Import the events `Host` lazily in the curriculum importer so the sync parsers register on sites that install curriculum without the package events app (A7.1).

## 0.4.2 - 2026-09-16

- Restore the `requires_restart` declaration metadata that `declare()` accepted at v0.3.9 and a merge resolution dropped: sites declaring restart-affecting keys failed startup against v0.4.0 and v0.4.1.

## 0.4.1 - 2026-09-16

- C7.2: ship the knowledge base fixture repository as regular files instead of a mode-160000 gitlink, so git-dependency installs (uv, pip) resolve the package and fresh clones run the fixture tests.

## 0.4.1 - 2026-09-16

- C7.2: ship the knowledge base fixture repository as regular files instead of a mode-160000 gitlink, so git-dependency installs (uv, pip) resolve the package and fresh clones run the fixture tests.

## 0.4.0 - 2026-09-16

- C4.1e: remove `EventAlias`, `add_alias`, the `event_alias` view and the trailing `<path:alias>/` route (decision D17). An event is addressed only by its canonical URL and a path below `events/` that matches no event returns 404. Breaking for any site that mounted the alias route, created `EventAlias` rows, or resolved superseded paths through them.
- C7.2: add the `knowledge_base` app (`cb_knowledge_base`): wiki and documentation pages with `content_sync` provenance, the donor docs hierarchy resolution, the lifted donor sanitizer allowlist, a search-corpus service, Studio inspection screens and overridable default public routes for `/wiki/` and `/docs/` (community-base#260).
## 0.3.8 - 2026-09-13

- C6.2a: surface the verified email on the double opt-in `RelayVerificationConfirmation` so the adopting site can mirror the confirmation onto its own user.

## 0.3.7 - 2026-09-12

- C6.2: add the Relay contacts, subscriptions and tags clients (`RelayContactsClient`) with FakeRelay contract coverage; contact-level callbacks record transition `sequence` and `occurred_at` and emit `relay_callback_processed` for site `unsubscribed` and `bounce_state` updates.

## 0.3.6 - 2026-09-12

- Studio: add nested destination groups and the `COMMUNITY_BASE["STUDIO_EXTRA_CSS"]` shell stylesheet hook (community-base#220).

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
