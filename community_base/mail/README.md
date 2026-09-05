# Mail

`community_base.mail.send()` records one durable logical delivery and one job inside the caller's
transaction. It requires `purpose`, recipient address, JSON context and an idempotency key. Exact
replays return the original delivery; changed work under the same key raises `MailConflict`.

The projection states are `pending`, `queued`, `leased`, `provider_accepted`, `delivered`,
`retryable`, `ambiguous`, `suppressed`, `dead`, `hard_bounced` and `complained`. Provider acceptance
does not mean delivery. Callback transitions are monotonic and callback event IDs are deduplicated.

`MAIL_BACKEND` defaults to `memory`. Its `outbox` is a process-local test surface and supports
`outbox.clear()`. Relay transport is added separately by C1.2b; `ses_local` is transitional and is
added by C1.3.

Hooks:

- `MAIL_PREFERENCE_RESOLVER`: callable receiving `purpose`, `category`, `to`, and `user`; return
  true/none to allow, false or a safe reason code to suppress. Default: allow.
- `MAIL_SEND_RECORDER`: optional callable `(delivery, rendered, result)` for transitional audit
  integration.
- `MAIL_TEMPLATE_OVERRIDE_LOADER`: optional callable `(template_key) -> (subject, body) | None`.

Delivery rows retain the JSON template context needed for durable execution and its canonical hash,
but never rendered bodies. Callers must pass only retention-approved template inputs; secret-bearing
values must be resolved by the worker at send time. Recipient addresses, stored context and raw
unsubscribe tokens must never be logged, returned by APIs or placed in job payloads.

The DTC link-bridge contract tests were adapted for the package settings and URL configuration.
Site-owned exclusions are the legacy-path inventory, site branding, site response middleware,
Gunicorn access-log class and observability backend wiring; the package tests retain the route,
forwarding, outage, redirect, token-confidentiality and durable replay behavior.
