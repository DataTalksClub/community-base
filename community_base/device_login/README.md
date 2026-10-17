# Device login app

`community_base.device_login` is the shared admin device login flow (RFC 8628-shaped).
The CLI prints a user code and a verification URL; a signed-in admin approves it in the
browser; the CLI polls for the resulting credential. It replaces copying admin API
tokens by hand. Existing admin tokens keep working; device login is the preferred way.

## Install

1. Add `"community_base.device_login"` to `INSTALLED_APPS` after `community_base.api`.
2. Mount the URLs at the site root so `/device/` and `/api/auth/device/*` resolve:
   `path("", include("community_base.device_login.urls"))`.
3. Run `uv run python manage.py migrate`.
4. Optional `COMMUNITY_BASE` keys (see `community_base/kernel/conf.py` for defaults):
   `DEVICE_LOGIN_TTL_SECONDS` (600), `DEVICE_LOGIN_POLL_INTERVAL` (5),
   `DEVICE_LOGIN_SCOPES` (`["*"]` for the default minter),
   `DEVICE_LOGIN_TOKEN_MINTER` (dotted `minter(*, user, label, request) -> dict`
   carrying at least `token`; the default mints a staff `community_base.api` key),
   `DEVICE_LOGIN_ADMIN_CHECK` (dotted `check(user) -> bool`; default
   `is_staff or is_superuser`).

## Wire

- `POST /api/auth/device/` with optional `{"label": "user@host"}` starts a grant and
  returns `device_code`, `user_code` (`XXXX-XXXX`), `verification_uri`,
  `verification_uri_complete`, `expires_in` (600), `interval` (5).
- `POST /api/auth/device/token` with `device_code` (and optionally the RFC 8628
  `grant_type`) polls: `authorization_pending` while waiting, `slow_down` when
  polling too fast, `access_denied` once on denial, `expired_token` for
  expired/consumed/unknown grants, and the minted credential exactly once on
  approval. The grant is single use.
- `GET /device/` is the verification page. A signed-in user enters the code,
  reviews the machine label, request IP and times, then authorizes or denies.
  Anonymous users are sent to `LOGIN_URL` with `next=` so Google sign-in works
  as today.
- `GET /api/auth/device/pending?user_code=` and `POST /api/auth/device/approve`
  (`{"user_code": ..., "approve": true|false}`) back the page for JSON clients.

## Admin only

Only admins (default: staff or superuser) can approve. A normal user gets a clear
`admin_only` refusal (HTTP 403 on the API, an inline message on the page) and no
token is issued. If the approver lost admin status before the CLI polls, the poll
reports `access_denied` instead of minting.

## Limits

Short-lived grants (10 minutes), 5-second poll pacing enforced server-side,
10 starts per 10 minutes and 240 polls per 10 minutes per IP, a shared
5-lookup/decision budget per grant (the 6th kills it), and SHA-256 hashes only
at rest (no plaintext codes in the database).

## CLI

Site CLIs wrap `community_base.device_login.client.device_login(base_url, label=...)`,
which prints the standard prompt, polls to approval/denial/expiry, and returns the
credential dict. Store it with `storage.save_private_json(path, payload)` (atomic
0600 file, 0700 directory) and document the refresh path as "run login again".
`login` runs the flow, `logout` best-effort revokes server-side and deletes the
file, `whoami` proves the stored credential against the server.
