# A3.2c stop report: three escalations before the credential move can run

Date: 2026-09-17. Raised while implementing A3.2c (AI-Shipping-Labs/website#1692, groomed as
#1656) after decision D32 settled the scope-enforcement contradiction. The D32 enforcement change
shipped on its own branch; the credential move did not start. These three items need an owner
ruling first. Two are correctness, one is a security defect in the issue as written.

## 1. The prescribed wildcard scope is a privilege escalation

Issue #1656 says a copied operator `Token` maps onto `community_base.api.APIKey` with
`scopes=["*"]`. That is not a no-op label. `community_base.api` is already mounted on the AISL site
(`website/urls.py:50` serves `/api/v1/`, `studio/urls.py:1488` serves `/studio/api-keys/`) with
twelve registered bearer routes carrying `settings.read`, `settings.write`, `mail.read`,
`mail.write`, `content_sync.read` and `content_sync.write`. `APIKey.authenticate` is
prefix-agnostic, so it does not care that the credential began life as an AISL operator token.

Verified empirically, not inferred:

| Copied token scopes | `allows(("settings.write",))` |
|---|---|
| `["*"]` as #1656 prescribes | True |
| `["asl.staff_api"]` | False |

So running the copy as written would turn every existing AISL operator token into a full settings,
mail and content-sync credential over `Authorization: Bearer`. The mapping rule needs replacing
before any copy runs. It was not improvised into the repository.

## 2. Package API keys are transferred by an account merge, not revoked

`accounts/services/account_merge.py` carries explicit strategies for `accounts.Token` (delete) and
`accounts.MemberAPIKey` (revoke). It has none for `cb_api.APIKey`, so that model falls through to
the generic `update(user=canonical)` at line 644 and the credential is transferred to the surviving
account.

Today that is harmless, because no `cb_api.APIKey` rows exist on the site. After the move every
credential is one, so a merge would silently transfer credentials instead of revoking them. That
contradicts the acceptance criterion "reactivation restores nothing" and the behaviour
`api/tests/test_user_merge.py` pins today.

## 3. The copy makes every member's key metadata visible on a Studio page

The package's `/studio/api-keys/` page lists `APIKey.objects.select_related("user")` unfiltered,
and its template renders `{{ api_key.user }}`, `{{ api_key.kind }}`, `{{ api_key.masked_prefix }}`
and `{{ api_key.scopes }}`.

Today a member's personal key metadata is visible only to its owner at `/account/`. After the copy
it appears on a superuser Studio page. That is a visibility change on a Studio page whose copy
#1656 forbids changing, so it cannot be resolved by editing the page.

## Two blockers that turned out not to need escalation

`Token.key_prefix` renders 8 characters where `APIKey.masked_prefix` renders 24. The site keeps the
render byte-identical with `{{ key.lookup_prefix|slice:":8" }}...` in
`templates/studio/api_tokens/list.html`. That is a data-path change, not a copy change.

`Token.rotate_key()` has no package equivalent. The site can rotate an `APIKey` in four lines, but
that reimplements package-owned credential minting inside a site. An `APIKey.rotate()` in the
package is the better shape; either way it is not a hard stop.

## What is settled

The digest property holds, verified twice independently. A real `Token` and `MemberAPIKey` were
minted, their `key_hash` and `lookup_prefix` copied verbatim onto `APIKey` rows, and both
re-authenticated. `Token.id` is 32 characters against `APIKey.id` max_length 40, and both hashes
fit max_length 128. Existing credentials would keep authenticating, so that stop condition is not
what halted the move.

`Token.name` is optional on the site and required by `APIKey`; `APIKey(name="").save()` raises.
#1656 blesses a fallback, but `templates/studio/api_tokens/list.html` renders
`{{ token.name|default:"-" }}`, so any fallback changes what Studio shows for unnamed tokens. No
fallback was chosen, because #1656 forbids Studio copy changes.

## Context that reduces the blast radius of D32 itself

D32 restores behaviour rather than inventing it. Scopes were enforced from 2026-07-02 until commit
`9eea1358` on 2026-08-29 removed the check from `MemberAPIKey.authenticate` and replaced
`request.member_api_scopes` with the full supported set. No key ever had broader capability than
its stored scopes outside that window.

`MemberAPIKey.create_for_user(scopes=...)` is never called outside tests. The only production
minting path is `accounts/views/account.py:553`, which passes no `scopes`, so every real key stores
`DEFAULT_SCOPES` as of its mint date. `DEFAULT_SCOPES` grew six times, so the affected keys are
exactly those minted before 2026-08-29.

| Mint window | Scopes it lacks today | Route groups newly refused |
|---|---|---|
| 2026-07-02 to 07-05 | `plans:write`, all `books:*`, all `events:*` | 17 |
| 2026-07-06 to 08-05 | all `books:*`, all `events:*` | 9 |
| 2026-08-06 | `books:write_notes`, `books:write_profile`, `events:read`, `events:register` | 5 |
| 2026-08-07 morning | `books:write_profile`, `events:read`, `events:register` | 4 |
| 2026-08-07 afternoon to 08-28 | `events:read`, `events:register` | 3 |
| 2026-08-29 onward | none | 0 |

The `asl` CLI is unaffected: it uses the operator `Token` and a `community_base` staff key, and
makes no member-API call.

## A forward hazard D32 creates

Under D32, adding a tenth scope silently narrows every existing key. Whenever `SUPPORTED_SCOPES`
grows, a data migration must add the new scope to existing rows, or grant them a wildcard. This is
the problem #1495 was reacting to when it removed enforcement; the answer is the migration, not
removing the check again.
