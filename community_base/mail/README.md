# Mail

`community_base.mail.send()` records one durable logical delivery and one job inside the caller's
transaction. It requires `purpose`, recipient address, JSON context and an idempotency key. Exact
replays return the original delivery; changed work under the same key raises `MailConflict`.

The projection states are `pending`, `queued`, `leased`, `provider_accepted`, `delivered`,
`retryable`, `ambiguous`, `suppressed`, `dead`, `hard_bounced` and `complained`. Provider acceptance
does not mean delivery. Callback transitions are monotonic and callback event IDs are deduplicated.

`MAIL_BACKEND` defaults to `memory`. Its `outbox` is a process-local test surface and supports
`outbox.clear()`. The `relay` backend submits the durable delivery to
`POST /api/transactional/send`; connection failures retry, an uncertain acknowledgement becomes
`ambiguous`, and Relay suppression is terminal.

`ses_local` is a transitional AISL migration backend. It renders frontmatter markdown from
`MAIL_TEMPLATE_DIR`, sends through SES v2 and accepts `extra={"cc": ..., "bcc": ...}` on
`send()`. A delivery-level `sender` wins over the `SES_FROM_EMAIL` runtime setting. The backend
declares `AWS_SES_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `SES_FROM_EMAIL` in the
runtime configuration registry. SES event ingress remains site-owned. Phase 6 removes this backend
after AISL templates and delivery move to Relay.

Mount `community_base.mail.urls` at the site root. It owns the exact recipient-link routes plus
`POST /internal/mail/callback`. Relay callbacks use HMAC-SHA256 over
`<X-Relay-Timestamp>.<raw body>` with `RELAY_WEBHOOK_SECRET`, accept at most five minutes of clock
skew, deduplicate `event_id`, and monotonically project delivery state. Bodies and signatures are
never logged.

`reconcile_deliveries(since)` reads `GET /api/transactional/messages?since=`, matches
`client_reference` to the local idempotency key and applies the same projection. The Relay client
also provides draft upsert, catalog/version listing, publish, preview and allowlisted test-send
operations. Mount `community_base.mail.studio_urls` under `/studio/` for delivery and template
operations.

The catalog, versioned send, callback and reconciliation endpoints are package-pinned contracts for
Relay issues R1.3 and R1.4. FakeRelay proves them locally; real conformance is not claimed until
those issues merge.

Hooks:

- `MAIL_CONTEXT_RESOLVER`: callable receiving `delivery` and its persisted `context`; returns the
  ephemeral context passed to the selected backend. The default accounts resolver creates signed
  verification, password-reset and email-change links in the worker so bearer tokens are never
  retained in `EmailDelivery.context_data`.
- `MAIL_PREFERENCE_RESOLVER`: callable receiving `purpose`, `category`, `to`, and `user`; return
  true/none to allow, false or a safe reason code to suppress. The default accounts resolver
  suppresses globally unsubscribed users, permanent bounces and categories explicitly set false;
  users without shared preference fields remain allowed for composability.
- `MAIL_SEND_RECORDER`: optional callable `(delivery, rendered, result)` for transitional audit
  integration.
- `MAIL_TEMPLATE_OVERRIDE_LOADER`: optional callable `(template_key) -> (subject, body) | None`.
  Transitional sites may return `(subject, body, footer_note)` to preserve their existing footer.
- `MAIL_UNSUBSCRIBE_URL_BUILDER`: optional callable `(delivery) -> str | None` used only by the
  transitional `ses_local` backend. It returns `None` for mail that must not carry an unsubscribe
  action.
- `MAIL_VERIFY_EMAIL_URL_BUILDER`: optional callable `(delivery) -> str | None` used by
  `ses_local` to resolve short-lived verification links in the worker instead of durable context.

Delivery rows retain the non-secret JSON template context needed for durable execution and its
canonical hash, but never rendered bodies or bearer URLs. Callers must pass only retention-approved
template inputs; secret-bearing values are resolved by the worker at send time. Recipient addresses,
stored context and raw
unsubscribe tokens must never be logged, returned by APIs or placed in job payloads.

The DTC link-bridge contract tests were adapted for the package settings and URL configuration.
Site-owned exclusions are the legacy-path inventory, site branding, site response middleware,
Gunicorn access-log class and observability backend wiring; the package tests retain the route,
forwarding, outage, redirect, token-confidentiality and durable replay behavior.
