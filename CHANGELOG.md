# Changelog

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
