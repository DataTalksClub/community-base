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

## 2. Package API keys are transferred by an account merge, not revoked -- CONFIRMED BY EXECUTION

`accounts/services/account_merge.py` carries explicit strategies for `accounts.Token` (delete) and
`accounts.MemberAPIKey` (revoke). It has none for `cb_api.APIKey`, so that model falls through to
the generic `update(user=canonical)` at line 644 and the credential is transferred to the surviving
account.

Today that is harmless, because no `cb_api.APIKey` rows exist on the site. After the move every
credential is one, so a merge would silently transfer credentials instead of revoking them. That
contradicts the acceptance criterion "reactivation restores nothing" and the behaviour
`api/tests/test_user_merge.py` pins today.

## 3. The copy makes every member's key metadata visible on a Studio page -- REFUTED AS STATED, but the data layer is as described

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

## Addendum, 2026-09-17: findings 2 and 3 executed rather than read

The AI-Shipping-Labs session ran both claims instead of leaving them as code
readings. One confirmed, one refuted as stated, and the refutation is the more
useful of the two.

### Finding 2 is confirmed, and it compounds with finding 1

Running the real `merge_accounts` against a real `cb_api.APIKey` row: `user_id`
repoints to the canonical account, `revoked_at` stays null, and
`APIKey.authenticate(plaintext)` still returns the row under its new owner. With
`kind="staff"` and `scopes=["*"]` the transferred key's `allows(("settings.write",))`
is still true, so a merge hands a full settings, mail and content-sync credential
to a different account. `MergePlan.to_dict()["credentials"]` reports zeros, so an
operator sees no signal that a live credential changed hands.

Mutation-checked: adding the missing merge strategy makes all three pinning tests
fail. Filed as AI-Shipping-Labs/website#1736.

### Finding 3 is refuted as stated, and the reason matters more than the claim

`/studio/api-keys/` leaks nothing today, because nothing renders at all. The page
returns HTTP 200 with the correct title and an otherwise empty Studio shell.
`community_base/api/api_keys.html` puts its body in `{% block content %}`, but the
site's `templates/community_base/studio/base.html` extends
`templates/studio/base.html`, which defines only `{% block studio_content %}`. The
block is silently dropped: no owner email, no key name, no masked prefix, no
scopes, no create form reaches the HTML.

The data layer is exactly as reported, though. `response.context["api_keys"]`
does contain a member-owned key the requesting superuser does not own; the
queryset is unfiltered. So the page is a loaded gun rather than a live leak: the
obvious fix for a blank Studio screen is to add a `studio_content` override, and
that alone turns the reported leak on. Mutation-checked: adding the override makes
two of the nine pinning tests fail. Filed as AI-Shipping-Labs/website#1737, which
states that the template block and the queryset scoping must land in the same
change.

A side effect worth recording: the page has presumably been non-functional since
`community_base.api.urls` was mounted, so there is currently no way to create or
revoke a package API key from the user interface, although the POST route still
works when hit directly. The site already ships a `studio_content` override for
the package settings page, so this reads as a missed override at mount time rather
than a deliberate omission.

### What this leaves for the owner

Two open questions rather than three, and neither now rests on an unexecuted code
reading. The pinning tests for both live uncommitted in
`/data/agents/ai-shipping-labs/worktrees/verify-1656`, and both issues point at
them, so whoever fixes each one inverts the tests rather than starting over.
