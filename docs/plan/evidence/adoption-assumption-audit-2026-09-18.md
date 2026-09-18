# Adoption assumption audit, 2026-09-18

The class of defect C7.19 exposed: a package behaviour that matches how the one adopting site
(AI-Shipping-Labs/website) happens to be configured, is untested against any other legal Django
shape, and fails silently for the second site. The package's own suite cannot see the gap because
`testproject/settings.py` and `testproject/urls.py` were written alongside that site and mirror it
exactly: one `base.html` carrying precisely the five contracted blocks, every Studio module mounted
at `studio/` with no namespace, SQLite, no content security policy, plain static storage.

Method, following P7's both-directions rule (`docs/03-playbooks.md`). End 1 walked out from the
package: every place it reads something about the site (URL and route names, template blocks and
overrides, static assets, `kernel.conf` keys, the access policy and authorizer hooks, app labels,
`_meta.get_fields()`, `INSTALLED_APPS`, URLconf walks, string equality on site-supplied names,
signals and checks). End 2 walked in from `../dtc-website`, comparing its real configuration
against `../ai-shipping-labs` wherever the package touches it. Both repositories were read only;
nothing was changed, committed or stashed in either.

Classification is by evidence. Confirmed means reproduced, with the command and its real output
recorded below. Plausible means the code path clearly depends on the assumption but the failure
was not constructed, and says what stopped it. Checked and fine is listed too, because a list of
what was cleared is what makes the rest worth trusting.

Ranking is by how badly it fails. Silent wrong behaviour outranks a loud error, because the loud
error gets fixed the day the site first runs the command.

## The configuration difference that drives most of this

| Thing the package reads | AI-Shipping-Labs | DataTalks.Club |
|---|---|---|
| `base.html` blocks | `title`, `meta_description`, `robots`, `page_head_metadata`, `canonical`, `og_tags`, `verification`, `structured_data`, `extra_head`, `messages`, `body`, `extra_scripts` (`templates/base.html`) | `title`, `meta_robots`, `extra_css`, `body_class`, `nav_links`, `breadcrumbs_nav`, `breadcrumbs`, `content`, `extra_js` (`course_platform_templates/base.html`; there is no `templates/base.html`) |
| Studio URLconf namespace | none | `app_name = "studio"` (`studio/urls.py:7`) |
| Studio mount path | `studio/` | `studio/`, and `community_base.studio` is not installed yet |
| `AUTHENTICATION_BACKENDS` | `ModelBackend` plus the allauth backend | `["accounts.backends.DurableAccountBackend"]` only |
| Content security policy | none | `script-src 'self' 'unsafe-inline'`, no external hosts (`core/middleware.py:77-83`) |
| Static storage in local development | plain `StaticFilesStorage` while `DEBUG` | `CompressedManifestStaticFilesStorage` in every environment but `test` |
| `COMMUNITY_BASE["SITE_URL"]` | not set | set to the canonical origin |
| `AUTH_USER_MODEL` | `accounts.User`, no `username` field | `accounts.CustomUser`, live `username` column |
| Database | SQLite in development, PostgreSQL deployed, one PostgreSQL CI job | SQLite in development and in the whole suite, PostgreSQL deployed, no PostgreSQL CI job |

## Findings

| # | Classification | Package location | AISL shape | Other legal shape | Consequence |
|---|---|---|---|---|---|
| 1 | confirmed | 41 templates with `{% extends "base.html" %}`; contract in `docs/02-architecture.md` section 5 | `base.html` defines `title`, `meta_description`, `page_head_metadata`; no `content`, no `extra_js` | `base.html` defines `content` and `extra_js`; no `meta_description`, no `page_head_metadata` | Django drops a block the site's base does not define, silently. On AISL every shared public page it has not overridden renders an empty `<body>` behind a correct `<title>`: the mounted unsubscribe page has no form, so the member cannot unsubscribe. On DTC the `noindex, nofollow` those pages set in `page_head_metadata` disappears. Neither site satisfies all five blocks and neither errors |
| 2 | confirmed | `community_base/studio/impersonation.py:13`, `AUTH_BACKEND = "django.contrib.auth.backends.ModelBackend"` | `ModelBackend` is in `AUTHENTICATION_BACKENDS` | a site whose `AUTHENTICATION_BACKENDS` does not list `ModelBackend`, which is DTC's actual value | `login()` accepts the backend without validating it, so the POST returns 302 and the session records the target. On the next request `auth.get_user` cannot load the backend, the operator becomes anonymous and is bounced to the login page, and `stop` cannot restore them because it logs in through the same backend. No exception anywhere |
| 3 | confirmed | `community_base/studio/route_names.py` `walk()`, `registry._is_live`, `registry._destination_url`, `registry.route_name_for` | Studio URLconf has no `app_name` | `app_name = "studio"`, DTC's actual URLconf | The archetype, already open as C7.19 and reproduced again here: the mounted set holds bare names while `reverse()` needs the namespaced one, so either the destinations are dropped or the hrefs are empty. Reproduced below so the audit's own method is calibrated against a known answer |
| 4 | confirmed | `community_base/curriculum/apps.py:16`, `"community_base.events" in set(installed_apps)` | `INSTALLED_APPS` spells apps as module paths | `"community_base.events.apps.EventsConfig"`, the AppConfig path, which Django accepts everywhere | The curriculum Studio section and its API views are never registered. No error, no log line; the section is simply absent from the sidebar and the routes 404. The nine sibling gates in `accounts`, `comments`, `community`, `onboarding`, `questionnaires` and `curriculum/views.py` use `apps.is_installed()`, which handles both spellings; this is the one that does not |
| 5 | confirmed | `community_base/accounts/mail_context.py:10`, `community_base/events/mail_context.py:15`; default `"SITE_URL": ""` in `kernel/conf.py` | `SITE_URL` is not set at all | `SITE_URL` set to an absolute origin | With the default the verification, password-reset, email-change and registration links in outbound mail become relative paths (`/api/verify-email?token=...`) and are dead in a mail client. Nothing raises and no system check asks for the value, while `events/integrations/calendar.py:77` and `jobs/relay.py:76` raise loudly on the same empty value |
| 6 | confirmed | `community_base/studio/templates/community_base/studio/base.html:37,44,134`, `{% url 'studio_dashboard' %}` and `{% url 'studio_global_search' %}` | bare names reverse | under a namespace they do not | `NoReverseMatch`, so every Studio page 500s rather than losing a link. This is a second half of C7.19 that its issue text does not cover: its steps change `route_names.py` and `registry.py` only, and the shell would still hard-reverse two bare names afterwards. Loud, and total |
| 7 | confirmed | `community_base/studio/templatetags/studio_filters.py:199`, `tuple(get("STUDIO_EXTRA_CSS") or ())` | the key is unset | a site sets it to a single stylesheet path as a string, the obvious reading of a setting whose default is documented as a sequence | A string is a sequence of characters, so the shell emits one stylesheet link per character. On AISL's development storage that is fifteen dead links and no error; under DTC's manifest storage it is a `ValueError` on every Studio page |
| 8 | confirmed | `community_base/studio/impersonation.py:14-20`, `SENSITIVE_RETURN_PREFIXES` | Studio is at `/studio`, the account pages at `/account` and `/accounts`, notifications at `/notifications` | any other mount for any of the five | The guard that stops an impersonation from returning the operator into a sensitive surface matches literal path prefixes. A site mounting the Studio elsewhere keeps the guard's shape and loses its effect, silently: nothing reports a prefix that matches nothing |
| 9 | confirmed | `community_base/studio/route_checks.py:13,36`, `mount="studio/"`; `community_base/studio/management/commands/studio_routes.py` has no mount argument | Studio at `studio/` | Studio at any other prefix | `studio_routes --check` reports every claimed route as "claimed but not mounted" and exits non-zero. The two halves also disagree in the same shape as C7.19: claims come from `mounted_sections()`, which reads the whole URLconf, while the mounted set is prefix-filtered. Loud, and it blocks a site's CI rather than corrupting a page |
| 10 | confirmed | `community_base/studio/templates/community_base/studio/base.html:21`, `https://unpkg.com/lucide@latest/dist/umd/lucide.js` | no content security policy | `script-src 'self' 'unsafe-inline'` | Every Studio icon disappears on DTC, with a console message and no server-side symptom. Independently, `@latest` means the icon library is unpinned and the shell's rendering can change without a package release. Already scoped as C7.20 |
| 11 | confirmed | the same shell: no block before the sidebar, no `id` on `<main>` | no accessibility registry | a site running automated accessibility checks needs a skip link and a named main landmark | The site must fork the 152-line shell to add them, which is the failure mode community-base#279 exists to prevent. Already scoped as C7.20 |
| 12 | plausible | two public templates carry an inline `<script>`: `accounts/templates/accounts/account.html`, `curriculum/templates/curriculum/unit_detail.html` | no policy | DTC allows `'unsafe-inline'` today, so neither breaks now | A site tightening `script-src` to `'self'` alone loses the behaviour with no server-side symptom. Not reproduced because no current site has that policy; recorded so a future tightening finds it here |
| 13 | plausible | `docs/02-architecture.md` section 5 lists fifteen `cb-` class hooks; the templates use 49 | AISL styles what it serves | a site styling exactly the documented fifteen | Thirty-four hooks have no documented contract, so an adopting site's stylesheet leaves those elements unstyled. Not reproduced as a failure because neither site's stylesheet was diffed against the list; it is a documentation drift with a rendering consequence |
| 14 | plausible | `testproject/settings.py` `database_name()` rejects any non-SQLite `DATABASE_URL` | SQLite here, PostgreSQL deployed | PostgreSQL | No package behaviour was ever executed against the database both sites deploy. Nothing vendor-specific was found (see cleared, below), so this is not a known defect; it is an unmeasured surface, and the package cannot be made to measure it without changing its settings module, which is out of scope for an audit |

## What was reproduced, and how

Finding 1, both site block vocabularies against one shared public template. The two base
templates are synthetic copies of each real site's block names, so the render needs no site code:

```
uv run pytest .tmp/repro/test_repro_base_blocks.py -q -s

--- AISL base.html vocabulary (no `content` block) ---
<title>Email preferences</title>
<meta name="description" content="Update your email preferences.">
<meta name="robots" content="noindex, nofollow">
</head>
<body>
</body>
HAS FORM: False | HAS noindex: True

--- DTC base.html vocabulary (no `meta_description`/`page_head_metadata`) ---
<title>Email preferences</title>
</head>
<body class="">
<main class="cb-page">
  ... <form class="cb-form" method="post"> ...
HAS FORM: True | HAS noindex: False
```

The AISL shape is not hypothetical: `grep -n "block" ~/git/ai-shipping-labs/templates/base.html`
has no `content` and no `extra_js`, that site mounts `community_base.mail.urls` at the root
(`website/urls.py:66`), and `git show v0.4.6:community_base/mail/templates/community_base/mail/unsubscribe.html`
already put the form inside `{% block content %}`, so the page has been serving an empty body since
the pin. The four knowledge-base public templates are overridden in `templates/knowledge_base/`,
which is why the same defect has been invisible everywhere else.

Finding 2, impersonation against two backend lists:

```
with ModelBackend (AISL shape) | POST: 302 | session user: 2 (target is 2) | next GET: 403
without ModelBackend          | POST: 302 | session user: 2 (target is 2) | next GET: 302 /accounts/login/?next=/studio/
```

Finding 3, the C7.19 archetype, against a synthetic URLconf declaring `app_name = "studio"`:

```
MOUNTED NAMES: ['studio_dashboard', 'studio_global_search', 'studio_impersonate', ...]
HAS studio_dashboard: True
HAS studio:studio_dashboard: False
REVERSE bare: NoReverseMatch Reverse for 'studio_dashboard' not found.
REVERSE namespaced: /studio/
```

Finding 4:

```
module-path spelling: True
appconfig-path spelling: False
apps.is_installed('community_base.events'): True
```

Finding 5:

```
SITE_URL unset (package default, AISL shape) -> /api/verify-email?token=eyJhbGciOi...
SITE_URL set (DTC shape)                     -> https://example.test/api/verify-email?token=eyJhbGciOi...
```

Finding 6, the same namespaced URLconf, requesting `/studio/` as a staff user:

```
django.urls.exceptions.NoReverseMatch: Reverse for 'studio_dashboard' not found.
```

Finding 8, `_safe_public_next` with three candidate return paths:

```
next='/studio/users/'         -> '/'
next='/manage/users/'         -> '/manage/users/'
next='/backoffice/users/'     -> '/backoffice/users/'
```

Findings 7 and 9:

```
ERRORS: 15
    studio_dashboard: claimed but not mounted
    studio_global_search: claimed but not mounted
    ...
mounted names with default mount: []
mounted names with mount='manage/': ['community_base_job_discard', 'community_base_job_retry', ...]

STUDIO_EXTRA_CSS = "site/studio.css" -> ('s', 'i', 't', 'e', '/', 's', 't', 'u', 'd', 'i', 'o', '.', 'c', 's', 's')
```

The reproduction scripts live under `.tmp/repro/` in the audit worktree and are not committed: a
reproduction of a defect the package still has cannot be a passing test, and a failing test in the
tree reads as a broken build to the next person.

## Checked and fine

Each of these was looked at because it could have carried the same shape, and does not.

| Area | Why it holds |
|---|---|
| Unknown `COMMUNITY_BASE` keys | `kernel/conf.get` raises `ImproperlyConfigured` for a name it does not declare, so a typo cannot silently take a default |
| Studio user search | `user_views._model_fields()` intersects `SEARCH_FIELDS` with the actual user model, so a site whose user has no `username`, `first_name` or `date_joined` still searches and orders correctly |
| Destination hrefs | `registry._destination_url` returns an empty string rather than letting `NoReverseMatch` escape, so one unmounted destination cannot take down the shell |
| Route name resolution | `registry.route_name_for` degrades to an empty string for an unresolvable path, a request with no `resolver_match`, and an empty target |
| External destinations | `_is_live` treats an `external_url` destination as live without a mounted route, under every URLconf shape tried |
| Registration and the mount path | `mounted_sections()` reads the whole URLconf, so registration itself is independent of where a site mounts the Studio; only the `route_checks` prefix is not (finding 9) |
| Tags accessor | `AttributeTagsAccessor.set` raises `ImproperlyConfigured` naming `USER_TAGS_ACCESSOR` when the user model has no `tags` attribute, rather than writing nothing |
| `INSTALLED_APPS` feature detection | the nine `apps.is_installed()` gates compare `AppConfig.name`, so both the module-path and the AppConfig-path spelling work; `config/apps.py` walks `app_config.name` for the same reason, and re-raises a nested `ModuleNotFoundError` instead of swallowing a broken `settings_keys` module |
| Static references | every literal `{% static %}` path in the package tree resolves to a file the package ships, so DTC's manifest storage has nothing to miss. Pinned by a new test |
| Public template classes | every class in every public template is `cb-` prefixed; no colour, spacing or typography utility leaked in. Pinned by a new test |
| Public template blocks | no public template fills a block outside the contracted five, and every one of them fills `content`. Pinned by a new test |
| External hosts in public templates | none; the only external reference in the package is the Studio shell's icon script (finding 10). Pinned by a new test |
| Database vendor | no `connection.vendor` branch, no raw SQL, no cursor use, no `.extra()`, no `.distinct("field")`, no `bulk_create(update_conflicts=...)`, no `__has_key` or `KeyTransform` JSON lookups. `JSONField` is used only as a column type. So the SQLite-only suite is a smaller risk than it looks, though still unmeasured (finding 14) |
| P7's own defect class | the package has no service that enumerates relations off `User` (`_meta.related_objects`, `_meta.many_to_many`, `apps.get_models()`): merge and privacy export resolve models by name through `apps.get_model`. The AISL-side defect that P7 documents has no package-side instance today |
| Empty required values | `jobs/relay.py`, `jobs/relay_scheduling.py` and `events/integrations/calendar.py` raise `ImproperlyConfigured` or a domain error on an empty `SITE_KEY` or `SITE_URL` rather than composing a broken string; finding 5 is the exception, not the rule |
| Language attribute | the Studio shell hardcodes `<html lang="en">`; both sites are `en-us` and neither is localised, so this has no consequence today and is recorded only so it is not rediscovered |

## Tests added

All pass on this commit. They pin shapes that are correct today, so that the next change cannot
quietly break them; none of them asserts a defect above.

- `tests/template_tree.py`: reads the package template tree as text, so the assertions hold for
  every consuming site rather than for the one whose settings this suite loads.
- `tests/test_template_contract.py`: the file `docs/02-architecture.md` section 5 has named as the
  public template guard since the architecture was written, and which did not exist. Seven
  assertions: the scan matches something, only contracted blocks are filled, every public template
  fills `content`, every class hook is `cb-` prefixed, no inline `<style>`, every `{% static %}`
  path resolves to a shipped file, no external host.
- `tests/studio/test_adoption_shapes.py` and `tests/studio/site_with_studio_at_another_path.py`:
  ten assertions over the cleared list above, including a Studio mounted at `manage/`.

## What this audit did not reach

- Nothing was executed against PostgreSQL. `testproject/settings.py` refuses a non-SQLite
  `DATABASE_URL` by design, and changing that is a separate issue. Migrations, index name lengths,
  collation and ordering, and `JSONField` behaviour on the database both sites deploy are
  unverified here.
- `content_sync` was surveyed for vendor and settings assumptions but its parsers, resolution and
  rendering were not audited for site-shape assumptions. The kind registry and the opaque `record`
  contract are where the next instance of this class would most plausibly sit.
- The API registry's scopes and authentication, the Relay jobs ingress, and the mail backends were
  read only far enough to answer the settings and vendor questions. Their own site-shape
  assumptions are unexamined.
- App-label collision was not exercised. Both sites own an `accounts` app at the label
  `community_base.accounts` claims, and DTC additionally owns `accounts.CustomUser` with a live
  `username` column. That is the subject of P7 and phase 3 and was left there.
- `STUDIO_AUTHORIZER`, `STUDIO_AUDIT_WRITER` and the access policy were read but not exercised
  against a second implementation. `kernel/access.can_access` resolves whatever the site names and
  calls `can_access` on it; a policy implementing only `user_level` would fail, and that was not
  constructed.
- Neither site's own test suite was run. This branch changes no package code, only tests and this
  document, so the consumer risk is nil; the cross-repository check (P16) covers it on push.
- The audit is a snapshot of `main` at `b1a5b49`. C7.19 and C7.20 are in progress on their own
  branches and were not read, so findings 3, 10 and 11 restate what those issues already own, and
  finding 6 is the part of the namespace problem C7.19's text does not currently cover.

## Suggested disposition

One issue per finding, not one branch. Findings 1, 2, 4 and 5 are the ones that fail silently and
that a second site would pay for; finding 1 is already costing the first site. Findings 6 and 9
belong with C7.19, which is open and touching those files.
