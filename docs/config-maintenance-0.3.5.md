# Config maintenance release 0.3.5

## Baseline and release scope

This maintenance branch starts at `v0.3.0` (`fae109b4e34c0afe20c935c6778a476eb968e9cb`).
Later tags contain provisional kept-label account and event migrations; this branch includes
none of those apps or migrations. It must be released from the maintenance branch, rather than
merged into current `main` before tagging. Existing tagged migrations remain unchanged.

`A0.2` adds optional integer clearing, audited `service.unset`, `Definition.requires_restart`
and standard Django save feedback. These contracts are documented in the config README.

## Required non-provisional backports

The consuming website already uses transactional mail behavior introduced after `v0.3.0`.
The maintenance release preserves it using these source changes:

| Source commits | Files carried into maintenance release | Contract |
|---|---|---|
| `9d48b28` | `mail/service.py`, `mail/backends/ses_local.py`, `tests/mail/test_ses_local.py` | SES reply-to, configuration set and plain text |
| `57b57c5`, `a03f8e8` | `config/registry.py`, `mail/settings_keys.py`, config registry tests | Preserve site-declared backend metadata and package docs |
| `8a1663b`, `1b2f1c9` | `mail/context.py`, `mail/jobs.py`, `mail/relay.py`, `mail/backends/relay.py` | Resolve ephemeral context in worker and pass it to delivery backend |

The mail README is copied from `v0.3.3`. Only `MAIL_CONTEXT_RESOLVER` is added to the kernel
configuration keys. Its default is the package context resolver. The `v0.3.0`
`MAIL_PREFERENCE_RESOLVER` default remains `allow_all`, because shared accounts are excluded;
sites must supply their own preference resolver as the website already does.

These are file-level backports, rather than entire source commits, so provisional apps and their
migration dependencies cannot enter through unrelated source changes. No migration is added,
removed or edited. Tests retain the maintenance baseline's synthetic Django user fixtures.

## Consumer integration

Pin the released `v0.3.5` tag and regenerate the lock with `uv lock --upgrade-package community-base`.
Remove any site monkeypatch of `SettingsGroupForm.cleaned_updates`. The shared save view applies
both `cleaned_updates()` and `cleaned_clears()`; a custom consumer must also apply both atomically.
Pass `requires_restart` when declaring startup settings. A template override may read
`setting.requires_restart` and render standard Django success/warning messages.

The website cutover's 30 distinct package import combinations were inventoried against this
branch; their modules and imported contracts are present. Website affected tests and deployed
smoke checks still belong to the website pipeline. A package-local pass does not prove them.

## Release limitations

This release does not contain the later shared accounts, events or curriculum capabilities,
or the `v0.3.4` Studio authorizer hook. A consumer requiring those must not switch to this tag.
Package compatibility checkpoints for kept-label apps stay open.

Not run here, needs: website affected tests, website CI/development deploy, development-copy
migration rehearsal, and donor/deployed parity checks under the website process.
