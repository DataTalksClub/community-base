# Phase 6: AISL cutover to Relay

Goal: AISL sends every email and runs every background job through Relay; templates, contacts,
subscriptions, campaigns, SES events and the email log history live in Relay (decisions D3, D4,
D13). The transitional `ses_local` and `django_q` backends are removed from the package.

Gate (decision D13): DTC has run on Relay in production for at least four consecutive weeks with
no P1 incident attributed to Relay and a green status contract. Record the dates in R6.1 before
opening the rest.

Freeze: AISL one weekend (A6.4).

Exit criteria:

- AISL task definitions have no `qcluster`; AISL has no `boto3` SES client:
  `grep -rn "sesv2\|django_q" ~/git/ai-shipping-labs --include=*.py | grep -v migrations` -> nothing.
- `email_app` directory removed from AISL; `EmailLog`, `SesEvent`, `EmailCampaign`,
  `CampaignDelivery`, `EmailTemplateOverride` tables dropped after their history is in Relay.
- Package has no `ses_local` or `django_q` backend.

## R6.1 AISL tenant and SES identity in Relay production

Repository: DataTalksClub/relay, aws-infra by pull request. Depends on: D1.3, D5.2 (and the D13 gate: four clean weeks of DTC production on Relay).

Steps
1. Record the gate evidence in the issue: DTC production start date, incident log, status
   contract screenshots for four weeks.
2. Provision organisation `aisl`, audience `aisl`, client `aisl-website`, senders matching
   `email_classification.get_sender_for_kind` (transactional, promotional, team), API key.
3. SES domain identity for `aishippinglabs.com` in Relay's configuration set; DKIM, SPF, DMARC.
   AISL's own SES identity stays until A6.4 completes, then is retired in aws-infra.

Verification
- canary from Relay production with the AISL sender to an owner mailbox -> delivered, DKIM pass.

## R6.2 History import

Repository: DataTalksClub/relay. Depends on: R6.1.

Read first
- `~/git/ai-shipping-labs/email_app/models/` (`EmailLog`, `SesEvent`, `EmailCampaign`,
  `CampaignDelivery`), `email_app/services/email_log_history.py`.

Steps
1. `POST /api/import/messages` (batch, idempotent on `client_reference`) creating historical
   `transactional_messages` rows with original timestamps, status, template key, recipient;
   `POST /api/import/events` for bounce, complaint, open and click events;
   `POST /api/import/campaigns` for campaigns and their recipient rows.
2. Contact history must show imported rows in order with the rest.
3. Management command `import_history --from-json <file>` for operators.

Verification
- Import a 10,000-row synthetic fixture twice -> second run creates zero rows; contact history
  for one address shows the imported messages.

## R6.3 Campaign parity for AISL

Repository: DataTalksClub/relay. Depends on: R1.5.

Read first
- `~/git/ai-shipping-labs/email_app/services/campaign_audience.py`, `campaign_recipients.py`,
  `studio/views/campaigns.py`, `specs/10-email.md`.

Steps
1. Audience filters by tag set, category subscription and a client-provided recipient list
   (`recipient-lists` API already exists); recount endpoint; campaign detail with per-recipient
   disposition as AISL shows today; retry a failed delivery; "assume sent" operator action.
2. Tags sync: AISL pushes `tier:<slug>`, `newsletter`, and Studio user tags as contact tags on
   change (`subscription.changed` callback closes the loop).

Verification
- Sandbox: create a campaign for tag `tier:main` with 3 contacts -> recount 3 -> send -> 3
  recipient rows with dispositions.

## C6.1 Remove transitional backends

Repository: community-base. Depends on: A6.4 merged and deployed.

Steps
1. Delete `community_base/mail/backends/ses_local.py`, `jobs/backends/django_q.py`, the
   `MAIL_TEMPLATE_DIR`, `MAIL_SEND_RECORDER`, `MAIL_TEMPLATE_OVERRIDE_LOADER` hooks, the
   `django_q` and `ses_local` extras, the `jobs_run_due` command.
2. Release `1.0.0`.

Verification
- `grep -rn "ses_local\|django_q" community_base/` -> nothing; `make check && make test` -> pass.

## A6.1 Templates into Relay

Repository: AI-Shipping-Labs/website. Depends on: R6.1, R1.3.

Steps
1. Export every `EmailTemplateOverride` back into the markdown files (the override wins), commit
   the result to `email_templates/`.
2. `import_templates --dir email_templates/` against Relay production for the AISL tenant; publish
   version 1 of each; preview all 50 with `preview_contexts.py` contexts through the Relay
   preview endpoint and compare with `ses_local` renders (whitespace-normalised diff attached to
   the pull request; differences must be explained).
3. Add the deploy step that re-imports drafts on change.

Verification
- 50 published templates in Relay; preview diff report attached.

## A6.2 Contacts and preferences into Relay

Repository: AI-Shipping-Labs/website. Depends on: R6.3, R1.5.

Steps
1. One-off `sync_contacts_to_relay` command: every user with `unsubscribed`, `email_preferences`,
   `bounce_state`, tags and tier tag; newsletter subscribers with their verification state.
2. Ongoing: `MAIL_PREFERENCE_RESOLVER` continues to read the user; changes to preferences call
   Relay subscription endpoints through a job handler; `subscription.changed` callbacks update
   the user (`unsubscribed`, `bounce_state`).
3. Double opt-in for `/subscribe` moves to Relay's verification flow through the link bridge.

Verification
- Contact count in Relay for the AISL audience equals `User.objects.count()` plus subscriber
  count; a preference toggle in the account page changes the Relay subscription within one minute
  (development environment).

## A6.3 Switch backends, campaigns and SES events

Repository: AI-Shipping-Labs/website. Depends on: A6.1, A6.2, R6.2.

Steps
1. `MAIL_BACKEND="relay"`, `JOBS_BACKEND="relay"` in production settings (development first);
   `sync_relay_schedules` in deploy; register every remaining django-q task as a handler and
   every schedule from `setup_schedules` in the registry; remove `django_q` from
   `INSTALLED_APPS`; remove the `qcluster` container from the task definition.
2. Campaign pages switch to the package's Relay-proxied pages; delete
   `email_app/services/campaign_*.py`, `studio/views/campaigns.py`, SES events pages
   (`ses_events.py`, `ses_explain.py`), `/api/ses-events` ingress (SNS subscription re-pointed to
   Relay's ingress in aws-infra by pull request).
3. History: `export_email_history` command writes `EmailLog`, `SesEvent`, campaigns and
   deliveries to JSON; import into Relay with R6.2; verify counts; then a migration drops the
   five tables and the `email_app` app is deleted; the `record_send` and override hooks are
   removed.

Verification
- Development: password reset -> `EmailDelivery` reaches `delivered` through Relay callbacks;
  a campaign to a 3-user test tag sends; a scheduled job fires from Relay.
- Relay contact history for a long-standing test user shows imported sends followed by new ones.
- `grep -rn "EmailLog\|SesEvent\|EmailCampaign" --include=*.py . | grep -v migrations` -> nothing.

## A6.4 Freeze weekend: AISL production on Relay

Repository: AI-Shipping-Labs/website. Depends on: A6.3. Freeze required: yes. Playbook P13.

Production checks
- `jobs_ingress_selftest` -> `OK`; the 15-minute health schedule fires from Relay;
- one welcome email, one event reminder and one password reset delivered; open and click bridge
  respond; unsubscribe link works;
- Studio campaigns page lists historical campaigns from Relay; email log page shows the imported
  history for a known user;
- no `qcluster` container in the running service.

Done when
- [ ] checks pasted, freeze removed, C6.1 opened, AISL SES identity retirement pull request opened in aws-infra
