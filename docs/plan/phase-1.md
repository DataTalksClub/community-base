# Phase 1: jobs and mail through Relay

Goal: the package owns background-job dispatch and email sending behind one API each, with
backends `relay` (target), `django_q` and `ses_local` (transitional, decision D13) and `sync`
and `memory` (tests). Relay runs in production. DTC runs its jobs and mail on Relay. AISL adopts
the two apps on its local backends so that every app lifted in later phases can call
`community_base.mail.send` and `community_base.jobs.dispatch_after_commit`.

Freeze: DTC, one weekend (D1.3). AISL: none in this phase.

Exit criteria:

- DTC development and production task definitions contain no `qcluster` container:
  `grep -n qcluster ~/git/dtc-website/deploy/task_definitions.py` prints nothing.
- DTC has no Datamailer code: `grep -rln datamailer ~/git/dtc-website --include=*.py | grep -v migrations` prints nothing.
- Relay status contract for the DTC tenant is green for seven consecutive days.
- AISL `INSTALLED_APPS` contains `community_base.jobs` and `community_base.mail`, and
  `grep -rn "EmailService()" ~/git/ai-shipping-labs --include=*.py | grep -v tests` prints nothing.

Relay issues R1.1 to R1.5 are the critical path. Open them first.

## R1.1 Relay production environment

Repository: DataTalksClub/relay (code) and DataTalksClub/aws-infra (Terraform, by pull request).
Depends on: nothing.

Read first
- `~/git/relay/docs/relay-deployment.md`, `docs/infra-deploy.md`, `docs/operations.md`,
  `docs/unification-plan.md` Phase 4 (rules: own queues, own SES configuration set, own database,
  Elastic IP, worker in the deployment definition, region `eu-west-1`).
- `~/git/relay/AGENTS.md` (sandbox only today; do not describe sandbox as production).

Steps
1. In aws-infra, add a `prod/relay` root mirroring `sandbox/relay` with production naming, the
   SES domain identity for `datatalks.club` (DKIM, SPF, DMARC), an Elastic IP, encrypted EBS,
   and the two AWS-fed ingress queues. Open as a pull request; do not apply.
2. In relay, add a `deploy-prod.yml` workflow gated on a manual approval environment, reusing
   `scripts/deploy_relay_sandbox.sh` parameterised by environment.
3. Add a production tenant provisioning script: organisation `datatalksclub`, audience `dtc`,
   client `dtc-website`, default sender `DataTalks.Club <hello@datatalks.club>` (final address
   confirmed by the owner in the pull request), one API key stored in the DTC deployment secrets.
4. Add `docs/production.md` describing the environment, on-call checks and rollback.

Verification
- After apply and deploy: `curl -sS -X POST "$RELAY_URL/api/tasks" ... system.echo` (README
  example) -> `succeeded` within one minute.
- `GET /internal/ops/status` with the status token -> `worker.healthy: true`, `queue.pending: 0`.
- SES identity status in the AWS console: verified, DKIM enabled.

Done when
- [ ] the owner approved and applied the Terraform pull request
- [ ] a canary email to an owner-controlled mailbox was delivered from production

## R1.2 Webhook task hardening

Repository: DataTalksClub/relay. Depends on: nothing.

Read first
- `~/git/relay/docs/context.md` open decision 1 (timeout ceiling), `docs/worker-contracts.md`,
  `docs/unification-plan.md` 3b, the webhook task implementation under `mailing/workers/` and
  `taskdeck`.

Steps
1. Decide and document the timeout ceiling: 60 seconds synchronous. Add an ack-then-callback mode:
   the client returns `202` with `{"lease_seconds": N}` and later `POST /api/tasks/{id}/complete`
   or `/fail`; Relay marks the task `running` with a lease and fails it when the lease expires
   without a completion.
2. Retry classes: timeouts, `429`, `5xx` retry with exponential backoff up to a per-task
   `max_attempts` (default 5); `4xx` other than `429` fail immediately with the response body
   truncated to 2 KB stored on the task.
3. Per-client concurrency limit (default 4 in flight) and per-client rate limit on task creation.
4. Signed headers unchanged (`X-Relay-Task-Id`, `X-Relay-Correlation-Id`, `X-Relay-Timestamp`,
   `X-Relay-Signature`); add `X-Relay-Attempt`.
5. Dead-letter list in ops views: tasks failed after all attempts, with retry button.
6. Tests for every rule above, including replay of an old timestamp rejected by the reference
   receiver in `docs/api.md`.

Verification
- `uv run pytest tests -k webhook` -> pass.
- A sandbox task against a receiver that sleeps 70 seconds -> `failed` with reason `timeout`;
  against a receiver that returns `202` and completes in 90 seconds -> `succeeded`.

Done when
- [ ] `docs/api.md` documents the 202 lease protocol and the retry table

## R1.3 Template catalog: versions, preview, test send, typed context

Repository: DataTalksClub/relay. Depends on: nothing.

Read first
- `~/git/relay/docs/api.md` "Transactional Email API", the `email_templates` table in `docs/data-model.md`.
- `~/git/dtc-website/_docs/specs/05-events-registration-email.md` "Relay-owned email templates".
- `~/git/ai-shipping-labs/email_app/email_templates/` (the markdown format that must import cleanly) and
  `~/git/ai-shipping-labs/email_app/services/email_service.py` `_render_template_with_footer`.

Steps
1. Extend templates with immutable published versions: `PUT` writes a draft; `POST /api/transactional/templates/{key}/publish`
   creates version N; `GET .../versions` lists; a send names `template_key` and optional
   `template_version` (default: latest published).
2. Template format: markdown body with YAML frontmatter (`subject`, `required_context`, `category`),
   rendered to HTML with the same wrapper and footer conventions AISL uses (port
   `_render_template_with_footer` and the HTML wrapper into Relay). Validate `required_context`
   on send; missing keys fail the send with a clear error.
3. `POST .../preview` renders draft or version with a context and returns subject, HTML, text.
4. `POST .../test-send` sends a version to an allowlisted staff address.
5. Management command `import_templates --dir <path>` that reads a directory of AISL-format
   markdown files and creates drafts, used in Phase 6 and by DTC for its templates.
6. Tests: publish immutability, preview parity with send, required context validation.

Verification
- Import `~/git/ai-shipping-labs/email_app/email_templates/` into the sandbox with the command
  -> 50 drafts created, zero errors.
- Preview of `event_registration` with the AISL preview context
  (`email_app/services/preview_contexts.py`) renders without missing keys.

Done when
- [ ] `docs/api.md` documents versions, preview, test send and the frontmatter format

## R1.4 Client callbacks for delivery and engagement events

Repository: DataTalksClub/relay. Depends on: R1.2.

Steps
1. Per-client callback URL and secret. Relay posts `delivery.accepted`, `delivery.delivered`,
   `delivery.bounced` (hard or soft), `delivery.complained`, `delivery.suppressed`,
   `engagement.opened`, `engagement.clicked`, `subscription.changed` with a stable `event_id`,
   `message_id`, `client_reference` (the site's idempotency key), timestamp, and no body content.
2. Same HMAC scheme as webhook tasks; retry with backoff; ordered per message where possible.
3. `GET /api/transactional/messages?since=` for reconciliation.
4. Tests including duplicate delivery of the same `event_id`.

Verification
- Sandbox send to the SES simulator bounce address -> the reference receiver logs
  `delivery.bounced` with `client_reference` equal to the idempotency key sent.

Done when
- [ ] `docs/api.md` documents callback payloads and the reconciliation endpoint

## R1.5 Preference categories and double opt-in

Repository: DataTalksClub/relay. Depends on: nothing.

Read first
- `~/git/ai-shipping-labs/email_app/services/email_classification.py` (kinds and preference keys)
- `~/git/dtc-website/_docs/specs/05-events-registration-email.md` "Email preference and recipient semantics"

Steps
1. Subscriptions gain categories: `newsletter`, `events`, `courses`, `product`, `transactional`
   (always on). `POST /api/subscriptions/subscribe` and `unsubscribe` accept `category`.
2. Double opt-in: `POST /api/subscriptions/request-verification` sends a verification message
   through a named template; the confirm link lands on the site's public URL (link bridge) and
   the site calls `POST /api/subscriptions/confirm` with the token Relay issued.
3. Send-time check: a transactional send with `category` set is suppressed when the contact opted
   out of that category; the response says `suppressed`.
4. Tests.

Verification
- Sandbox: subscribe with `category=events`, unsubscribe from `events`, send with
  `category=events` -> `suppressed`; send with `category=transactional` -> `queued`.

Done when
- [ ] `docs/api.md` updated

## C1.1a Durable jobs core and local backends

Repository: community-base. Depends on: C0.5.

Goal: implement durable job behavior, signed ingress, and local execution without requiring a
running Relay service.

Read first
- `~/git/dtc-website/jobs/` (all files): `dispatch_after_commit`, `DurableJob`, leases, registry,
  `relay_due_jobs`, heartbeat, `schedules.py`.
- `~/git/ai-shipping-labs/jobs/` : `tasks/helpers.py`, `task_history.py`, `task_entities.py`,
  `views/`, `templates/studio/worker*.html`, `management/commands/setup_schedules.py`.
- `~/git/relay/README.md` (tasks and schedules API), `docs/api.md`.

Steps
1. Models (`label = "cb_jobs"`): `JobIntent(id uuid, handler, key_hash unique, payload json,
   payload_hash, status pending|submitted|running|succeeded|failed|dead, attempts, max_attempts,
   available_at, lease_token, lease_expires_at, correlation_id, external_id, last_error,
   created_at, updated_at)` from DTC `DurableJob` with the Relay task id in `external_id`.
2. `registry.py`: `register_handler(name)`, `get_handler`, `validate_payload` (DTC), and
   `schedule(handler, cron, payload, name=None)` collecting `ScheduleDefinition`s.
3. `dispatch.py`: `dispatch_after_commit(handler, key, payload, max_attempts=5, available_at=None)`
   from DTC; on commit call `backend.submit(intent)`.
4. Local backends in `community_base/jobs/backends/`:
   - `sync`: run the handler immediately after commit (tests).
   - `django_q`: `async_task("community_base.jobs.runner.run_intent", intent_id)`; schedules
     registered with `django_q.schedule` by the `sync_schedules` command; requires extra
     `community-base[django_q]`.
5. `runner.py`: `run_intent(intent_id)` claims with a lease (DTC `claim_job`), runs the handler
   with a `JobContext`, completes or fails with backoff; `RetryableJobError` and
   `PermanentJobError` from DTC.
6. `ingress.py`: `POST /internal/jobs/run` verifying `X-Relay-Signature` (HMAC-SHA256 over
   `<timestamp>.<raw body>` with `RELAY_WEBHOOK_SECRET`), timestamp within 5 minutes, task id
   deduplicated against `external_id`; runs `run_intent`; returns 200, or 202 with
   `lease_seconds` when the handler declares `chunked=True`. Completion transport is C1.1b.
7. Management commands: `sync_schedules` (local-backend aware), `jobs_run_due` (django_q and sync:
   run intents whose `available_at` passed, used by a django_q schedule every minute),
   `jobs_ingress_selftest` (signs a request to itself and expects 200),
   `jobs_sweep` (expired leases, from DTC `sweep_expired_jobs`).
8. Studio page (standalone template until Phase 2): pending, running, failed, dead intents;
   retry and discard actions; schedules with last and next run.
9. Tests: dispatch inside and outside a transaction, dedup conflict, lease fencing, backoff,
   ingress signature and replay rejection, local backends, schedule diff.

Verification
- `make check && make test` -> pass, `tests/jobs` has at least 25 tests.
- `uv run python testproject/manage.py jobs_ingress_selftest` with a dummy secret -> `OK`.

Done when
- [ ] `community_base/jobs/README.md` documents the API, backends, settings keys
  (`JOBS_BACKEND`, `SITE_URL`, `RELAY_BASE_URL`, `RELAY_API_KEY`, `RELAY_WEBHOOK_SECRET`)

## C1.1b Relay jobs client and contract tests

Repository: community-base. Depends on: C1.1a.

Goal: add the Relay transport behind the durable jobs contract without making package acceptance
depend on a live Relay deployment. Real conformance remains in R1.2 and site adoption.

Steps
1. Add the `relay` backend: `POST /api/tasks` with `type=webhook`,
   `url=<SITE_URL>/internal/jobs/run`, `idempotency_key=<SITE_KEY>:<key_hash>`, and params
   `{"intent_id": ...}`; persist the returned task id.
2. Add completion/failure calls for chunked 202 leases and preserve lease fencing locally.
3. Register schedules with Relay using its idempotent `POST /api/schedules` upsert keyed by name.
   Delete remote schedules no longer declared with `DELETE /api/schedules/{id}`; dry-run prints
   the exact diff.
4. Add `sync_relay_schedules` and Relay worker-health projection for the standalone Studio page.
5. Test submit, lease completion, retries, schedule create/update/delete, timeouts and malformed
   responses against the package FakeRelay transport contract.

Verification
- `make check && make test` -> pass.
- FakeRelay task lifecycle reaches `succeeded`; schedule reconciliation is idempotent.
- Real Relay sandbox conformance is listed under `Not run here, needs: R1.2`.

## C1.2a Durable mail core, memory backend, and local surfaces

Repository: community-base. Depends on: C1.1a.

Goal: implement the durable mail projection and all transport-independent behavior locally.

Read first
- `~/git/dtc-website/_docs/specs/05-events-registration-email.md` sections "Durable delivery model",
  "Relay callbacks and reconciliation", "Worker semantics", "Relay sender and provider boundary".
- `~/git/dtc-website/email_app/` (link bridge, `PendingUnsubscribe`, replay job).
- `~/git/ai-shipping-labs/email_app/services/email_classification.py` (kinds, sender per kind,
  preference decision), `email_service.py` `_delivery_decision`.

Steps
1. Models (`label = "cb_mail"`): `EmailDelivery(id uuid, idempotency_key unique, purpose,
   category, template_key, template_version, recipient_email, recipient_user FK null,
   context_hash, sender_id, state pending|queued|leased|provider_accepted|delivered|retryable|
   ambiguous|suppressed|dead|hard_bounced|complained, external_message_id, reason_code,
   job FK to JobIntent, related_object_type, related_object_id, created_at, updated_at)`;
   `PendingUnsubscribe` from DTC; `CallbackEvent(event_id unique, received_at)` for dedup.
2. `service.py`: `send(purpose, to, context, idempotency_key, category=None, user=None,
   related=None, sender=None)`: preference check through hook `MAIL_PREFERENCE_RESOLVER`
   (default: allow; Phase 3 wires the user's preferences), creates `EmailDelivery(pending)` and a
   `JobIntent` for handler `cb_mail.deliver` in the caller's transaction.
3. Backends in `community_base/mail/backends/`:
   - `memory`: appends to `outbox` list (tests), exposes `outbox.clear()`.
   - `ses_local`: see C1.3.
4. Transport-independent callback state machine: deduplicate `event_id` and apply only monotonic
   delivery transitions. C1.2b owns Relay signature and HTTP transport.
5. Link bridge from DTC: `tracking_open`, `tracking_click`, `public_unsubscribe` views and
   `relay_links.py` with the same fail-closed rules; URL names kept.
6. Studio pages (standalone until Phase 2): deliveries list with filters and state pills and
   delivery detail with redacted context hash and callback history.
7. API endpoints: `GET /api/v1/mail/deliveries`, `GET /api/v1/mail/deliveries/{id}`,
   `POST /api/v1/mail/deliveries/{id}/resend` (creates a new audited delivery related to the
   original, never a retry).
8. Tests: send inside transaction only, dedup conflict, preference suppression, monotonic
   projection with reordered callbacks, link bridge fail-closed cases moved from DTC, memory
   backend.

Verification
- `make check && make test` -> pass, DTC's link bridge tests pass unchanged in `tests/mail`.

Done when
- [ ] `community_base/mail/README.md` documents `send`, states, backends, hooks
  (`MAIL_PREFERENCE_RESOLVER`, `MAIL_SEND_RECORDER`, `MAIL_TEMPLATE_OVERRIDE_LOADER`)

## C1.2b Relay mail, catalog, callback, and reconciliation clients

Repository: community-base. Depends on: C1.1b, C1.2a.

Goal: implement every Relay mail transport contract against FakeRelay before real conformance.

Steps
1. Add the Relay delivery backend for `POST /api/transactional/send`, persisting template version
   and external message id without exposing recipient or context in logs.
2. Add signed callback ingress, event deduplication, and the C1.2a monotonic state projection.
3. Add `reconcile_deliveries` using `GET /api/transactional/messages?since=`.
4. Add Relay template catalog list, preview, publish, and test-send clients and standalone Studio
   pages.
5. Cover success, suppression, retryable and malformed responses, reordered callbacks,
   reconciliation and catalog operations with FakeRelay.

Verification
- `make check && make test` -> pass.
- FakeRelay send reaches `provider_accepted` and reordered callbacks converge on `delivered`.
- Real Relay checks are listed under `Not run here, needs: R1.3, R1.4`.

## C1.3 ses_local backend (transitional, for AISL)

Repository: community-base. Depends on: C1.2a.

Read first
- `~/git/ai-shipping-labs/email_app/services/email_service.py` (whole file),
  `email_app/services/ses_identity.py`, `email_app/checks.py`, `integrations/services/ses.py`.

Steps
1. Port `EmailService` into `community_base/mail/backends/ses_local.py`: markdown template lookup
   in `COMMUNITY_BASE["MAIL_TEMPLATE_DIR"]`, HTML wrapper and footer, unsubscribe URL through
   `MAIL_UNSUBSCRIBE_URL_BUILDER(delivery) -> str | None`, SES v2 client built from
   `community_base.config` keys `AWS_SES_REGION`,
   `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (declared by the backend).
2. Logging and overrides go through hooks so AISL keeps its `EmailLog` and
   `EmailTemplateOverride` tables until Phase 6: `MAIL_SEND_RECORDER(delivery, rendered, result)`
   and `MAIL_TEMPLATE_OVERRIDE_LOADER(template_key) -> (subject, body) | None`.
3. The handler `cb_mail.deliver` under this backend renders, sends, and sets
   `provider_accepted` with the SES message id; SES event ingress stays in AISL for now.
4. Tests with a stubbed SES client: render parity with AISL fixtures for three templates
   (`free_welcome`, `event_registration`, `password_reset`) using AISL's preview contexts.

Verification
- `make test tests/mail/test_ses_local.py` -> pass; rendered HTML for the three templates equals
  the fixtures captured from AISL (byte-equal after whitespace normalisation).

Done when
- [ ] backend marked transitional in the README with a pointer to Phase 6

## C1.4 Test doubles exported for sites

Repository: community-base. Depends on: C1.1a, C1.1b, C1.2a, C1.2b.

Steps
1. `community_base/testing/__init__.py`: `sync_jobs()` context manager, `mail_outbox()` fixture
   helper, `FakeRelay` (in-process HTTP stub for the task, send, template and callback endpoints
   using `responses` or a `requests` adapter), `signed_relay_request(...)` helper.
2. Document usage in `docs/testing.md`.

Verification
- The package's own tests use these helpers; `grep -rn "requests_mock\|responses" tests/` shows
  only `FakeRelay`.

## C1.5 Release 0.2.0

Repository: community-base. Depends on: C1.1a, C1.1b, C1.2a, C1.2b, C1.3, C1.4. Playbook P15.

## D1.1 Replace DTC jobs with the package jobs app (relay backend)

Repository: DataTalksClub/website. Depends on: C1.5, R1.1, R1.2.

Read first
- `jobs/` (every handler registered with `register_handler`), `jobs/schedules.py`,
  `deploy/task_definitions.py`, `website/settings/{development,production}.py`.

Steps
1. Install `community_base.jobs` (P2). Move every handler registration to
   `community_base.jobs.register_handler` keeping names. Move schedule definitions.
2. Data migration copying pending `DurableJob` rows to `JobIntent` (P6, tiny table).
3. Settings: `COMMUNITY_BASE["SITE_URL"]`, `RELAY_BASE_URL`, `RELAY_API_KEY`,
   `RELAY_WEBHOOK_SECRET` from deployment secrets; `JOBS_BACKEND="relay"` in deployed settings,
   `"sync"` in `test.py` and `local.py`.
4. Add `sync_relay_schedules` to the deploy steps after migrate.
5. Remove `django_q` from `INSTALLED_APPS`, the `qcluster` container from
   `deploy/task_definitions.py`, `jobs/` app and its tests (moved to the package).
6. Ingress route `path("internal/jobs/run", ...)` allowed in `core.middleware` request boundary
   rules (CSRF exempt, no session).

Verification
- `uv run pytest -q` -> pass.
- Development deploy: `manage.py jobs_ingress_selftest` in the container -> `OK`;
  `sync_relay_schedules --dry-run` -> no diff after the first real run; Relay ops view shows
  the DTC schedules with a next run.
- One schedule fires in development and its `JobIntent` reaches `succeeded`.

Done when
- [ ] `_docs/architecture/app-boundaries.md` says `jobs` is provided by the package and Relay executes it

## D1.2 Replace DTC email_app and the Datamailer outbox with the package mail app

Repository: DataTalksClub/website. Depends on: D1.1, R1.3, R1.4, R1.5.

Read first
- `email_app/`, `course_management/datamailer_outbox*.py`, `course_management/datamailer/`,
  `data/models.py`, `studio_courses/views/datamailer*.py`, `courses/deadline_reminder_*.py`,
  `_docs/specs/05-events-registration-email.md` purpose catalog.

Steps
1. Install `community_base.mail` (P2). Move `PendingUnsubscribe` rows (P6).
2. Templates: write the DTC purposes as markdown templates in `email_templates/` in the repo
   (deadline reminder, course registration confirmation, enrollment confirmation, certificate
   ready, Slack access), import them into Relay with `import_templates`, publish version 1.
   Commit `email_templates/` as the source of truth mirrored into Relay by a deploy step.
3. Replace every `enqueue_datamailer_outbox_event(...)` with `community_base.mail.send(...)`.
   Keep the idempotency keys the outbox used.
4. Delete `course_management/datamailer*`, `data` app (migration drops its tables after a
   development deploy with counts recorded), `studio_courses/views/datamailer*.py` and their
   templates; Studio email pages come from the package.
5. Link bridge URLs keep their paths; `RELAY_LINK_BRIDGE_*` settings become `COMMUNITY_BASE`
   keys declared by the mail app.

Verification
- `uv run pytest -q` -> pass; `grep -rln datamailer --include=*.py . | grep -v migrations` -> nothing.
- Development: register for a course cohort -> `EmailDelivery` reaches `delivered` for an
  owner-controlled address; open pixel and click bridge respond as before (existing tests).

Done when
- [ ] spec 05 "Datamailer remains read-only migration input" line removed; Datamailer named only in history

## D1.3 Freeze weekend: DTC on Relay in production

Repository: DataTalksClub/website. Depends on: D1.1, D1.2. Freeze required: yes. Playbook P13.

Production checks after deploy:
- `jobs_ingress_selftest` in the production container -> `OK`.
- One scheduled job fires and succeeds within its cron interval.
- One real transactional send to an owner mailbox reaches `delivered`.
- Relay status contract green; DTC Studio jobs page shows no `dead` intents.

Done when
- [ ] the checks above are pasted into the issue and the freeze label is removed

## A1.1 Adopt the package jobs app on the django_q backend

Repository: AI-Shipping-Labs/website. Depends on: C1.5.

Steps
1. Install `community_base.jobs` with extra `django_q`; `JOBS_BACKEND="django_q"`; migrate.
2. Add the `jobs_run_due` and `jobs_sweep` schedules to `setup_schedules`.
3. No existing task changes. New code and lifted apps use `dispatch_after_commit`.
4. Studio: keep the local worker page; add a link to the package intents page.

Verification
- `uv run python manage.py test jobs --parallel 4` -> pass; `make test-affected` -> pass.
- Development: dispatch a `system.noop` intent from `manage.py shell` -> `succeeded` within one
  minute under `qcluster`.

## A1.2 Adopt the package mail app on the ses_local backend

Repository: AI-Shipping-Labs/website. Depends on: C1.5, A1.1.

Read first
- the 35 `EmailService` call sites: `grep -rn "EmailService" --include=*.py . | grep -v tests`.

Steps
1. Install `community_base.mail`; `MAIL_BACKEND="ses_local"`,
   `MAIL_TEMPLATE_DIR=BASE_DIR / "email_app" / "email_templates"`; implement hooks:
   `email_app/hooks.py` with `record_send` (writes `EmailLog` exactly as today),
   `template_override_loader` (reads `EmailTemplateOverride`), `preference_resolver` (port
   `_delivery_decision`), `unsubscribe_url_builder` (returns `None` for transactional mail and
   otherwise ports `_build_unsubscribe_url`).
2. Replace `EmailService().send(user, template, context, dedupe_key=...)` call sites with
   `community_base.mail.send(purpose=template, to=user.email, user=user, context=context,
   idempotency_key=dedupe_key or <derived>)`, one app per pull request. `cc`/`bcc` become
   `extra={"cc": ..., "bcc": ...}` understood by `ses_local` only.
3. Reduce `email_app/services/email_service.py` to a shim raising `DeprecationWarning`, then
   delete it in the last pull request.
4. Campaign sending (`campaign_dispatch.py`) keeps its own SES path until Phase 6; it does not
   go through `send()`.

Verification
- After each pull request: `make test-affected` -> pass; `uv run python manage.py test email_app <app> --parallel 4` -> pass.
- Development: trigger a password reset -> `EmailLog` row written as before and an
  `EmailDelivery` row in `provider_accepted`.
- Final: `grep -rn "EmailService" --include=*.py . | grep -v tests` -> nothing.

Done when
- [ ] `_docs/configuration.md` email section names `community_base.mail` and the hooks
