# D32: which member API keys start being refused, and why

Date recorded 2026-09-18. Produced by the A3.2c work in AI-Shipping-Labs/website before the
enforcement change, at the owner's constraint that the inventory comes first. It is here so the
ruling can be made from a durable record rather than from a chat thread.

## What D32 changes

`member_api_key_required` currently ignores a key's stored scopes and grants the full
`SUPPORTED_SCOPES` set. Under D32 it enforces them, returning 401 with
`code: "insufficient_scope"` and the required scope in `details`.

This restores behaviour rather than inventing it. Scopes were enforced from 2026-07-02 until
commit `9eea1358` on 2026-08-29 removed the check. No key ever had broader capability than its
stored scopes outside that window.

## Why the affected set is knowable exactly

`MemberAPIKey.create_for_user(scopes=...)` is never called outside tests. The only production
minting path is `accounts/views/account.py:553`, which passes no `scopes`, so every real key stores
`DEFAULT_SCOPES` as of its mint date. `DEFAULT_SCOPES` grew six times, so the affected set is
exactly the keys minted in each window.

| Mint window | Commit that set the default | Scopes it lacks today | Route groups newly refused |
|---|---|---|---|
| 2026-07-02 to 07-05 | `a648f53b` | `plans:write`, all `books:*`, all `events:*` | 17 |
| 2026-07-06 to 08-05 | `c9d4728d` | all `books:*`, all `events:*` | 9 |
| 2026-08-06 | `d90cdde5` | `books:write_notes`, `books:write_profile`, `events:read`, `events:register` | 5 |
| 2026-08-07 morning | `7dfd5811` | `books:write_profile`, `events:read`, `events:register` | 4 |
| 2026-08-07 afternoon to 08-28 | `f1184312` | `events:read`, `events:register` | 3 |
| 2026-08-29 onward | `9eea1358` | none | 0, unaffected |

Routes newly refused, per window, verified against the decorators and the per-method
`_require_scope` guards:

- `a648f53b`: `PATCH /v1/plans/{id}` and its eleven `plans:write` sub-resources, every `books`
  route, every `events` route.
- `c9d4728d`: every `books` route, every `events` route.
- `d90cdde5`: `PUT` and `DELETE /v1/books/{slug}/chapters/{n}/note`, `PUT /v1/books/reader-profile`,
  all three `events` routes.
- `7dfd5811`: `PUT /v1/books/reader-profile`, all three `events` routes.
- `f1184312`: all three `events` routes.
- `GET /member-api/openapi.json` requires no scope and is unaffected in every window.

## What reduces the blast radius

The `asl` CLI is unaffected. A grep over `asl_cli/` finds no member-API usage at all: it uses the
operator `Token`, which carries no scopes, and a `community_base` staff key with `settings.read`
and `settings.write`.

The local development database carries zero `accounts_memberapikey` rows, so no local key is
affected and local data cannot answer the production question. The table above is derived from
source, which is why it is exact rather than sampled.

## A forward hazard the decision creates

Under D32, adding a tenth scope silently narrows every existing key, because a key stores the
scope set that existed when it was minted. Whenever `SUPPORTED_SCOPES` grows, a data migration must
add the new scope to existing rows, or grant them a wildcard.

This is the problem the 2026-08-29 change was reacting to when it removed enforcement. The answer
is the migration, not removing the check again.

## Where the ruling belongs

The enforcement change is in the AI-Shipping-Labs repository and affects credentials in its
production database, so the ruling is that repository's owner's, on its own tracker
(AI-Shipping-Labs/website#1656 and #1692). This record exists so the ruling can be made on the
evidence; it does not make it.
