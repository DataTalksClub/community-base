# Studio

The Studio app provides the shared operator shell, route-aware navigation, reusable template
components, dashboard and search extension points, and audited user impersonation. Add
`"community_base.studio"` to `INSTALLED_APPS` and mount its routes first under the Studio prefix:

```python
(path("studio/", include("community_base.studio.urls")),)
```

All built-in views require staff access. Set `COMMUNITY_BASE["STUDIO_AUTHORIZER"]` to a callable
that receives the request and returns a truthy value to allow access; it replaces the default
`is_staff` check on every shared Studio view, so a site can keep its own staff-role rules.
Authentication is always required before the authorizer runs. Starting impersonation additionally
requires a superuser; restoration succeeds only when the session points back to an active
superuser. Configure `COMMUNITY_BASE["STUDIO_AUDIT_WRITER"]` with a callable accepting the keyword
arguments `event`, `actor_ref`, `target_ref` and `metadata`. Identifiers are opaque strings; the
package does not put email addresses in audit events.

## Navigation registration

Apps register sections during `AppConfig.ready()`:

```python
from community_base.studio.registry import Destination, Section, register

register(
    Section(
        slug="operations",
        title="Operations",
        order=80,
        icon="settings",
        destinations=(
            Destination(
                key="jobs",
                title="Jobs",
                url_name="community_base_jobs",
                route_names=("community_base_jobs", "community_base_job_retry"),
                order=10,
            ),
        ),
    )
)
```

Every detail, form and action route belongs in its destination's `route_names`, so a deep route
keeps the correct link active. Put section-owned routes without a link in
`section_only_routes[route_name] = section_slug`. Add JSON or redirect routes that never render
the shell to `routes_without_home`.

Multiple apps may contribute to the same section when its slug, title, order and icon match. The
registry merges their destinations and still rejects duplicate destination keys or route claims.
The config, API, jobs and mail apps use this to populate the built-in Operations section.

Destinations that belong together can render as a nested disclosure group inside their section.
Groups are declared on the section and merge across apps under the same rules as destinations:

```python
from community_base.studio.registry import Destination, DestinationGroup, Section, register

register(
    Section(
        slug="operations",
        title="Operations",
        order=80,
        icon="settings",
        groups=(
            DestinationGroup(
                key="triggers",
                title="Triggers",
                order=30,
                destinations=(
                    Destination(
                        key="webhooks",
                        title="Webhooks",
                        url_name="community_base_webhooks",
                        route_names=("community_base_webhooks", "community_base_webhook_retry"),
                        order=10,
                    ),
                ),
            ),
        ),
    )
)
```

A destination can carry one lucide icon and can point outside the Studio URLconf:

```python
Destination(
    key="api_docs",
    title="API docs",
    url_name="",
    route_names=(),
    order=40,
    icon="file-json",
    external_url="/api/docs",
    new_tab=True,
)
```

Both fields are optional. `icon` defaults to the unadorned label the shell rendered before icons
existed. `external_url` replaces `url_name` for a link that leaves the Studio URLconf; such a
destination claims no route names, never becomes the active link, and is invisible to
`studio_routes --check`. Set `new_tab` to open it in a new tab with `rel="noopener"` and an
external-link marker. A destination with neither `url_name` nor `external_url` renders nothing, as
an unresolvable `url_name` always has.

Groups sort deterministically by `order`, then `key`, and their destinations sort like flat ones.
A group is hidden when none of its destinations are visible to the current user, and the shell
opens the group that contains the active route. Flat registrations stay unchanged; `route_names`
claims and `studio_routes --check` cover grouped destinations the same way.

The global search box matches grouped destinations too, under the same `pages` result group as
flat ones. Each match's `summary` names its section and, for a grouped destination, its group,
joined with ` · `, so a result found inside a disclosure subsection is not mistaken for a
top-level link. A grouped destination hidden from the viewer by `superuser_only` or a feature flag
is left out of the results the same way a hidden flat destination is.

## Sidebar density and collapse

Every titled section renders a header button that collapses and expands the section. The section
without a title carries no header, so it is never collapsible and its links are always visible.

The shell decides the starting state from how many destinations the viewer can see:

| Visible destinations | Starting state |
|---|---|
| at or below `STUDIO_NAV_COLLAPSE_THRESHOLD` | every section expanded |
| above it | only the active section expanded |

The threshold defaults to 24, which keeps a small registry rendering exactly as it did before
collapse existed. Set it to 0 to collapse from the first destination, or to a large number to
never collapse:

```python
COMMUNITY_BASE = {
    "STUDIO_NAV_COLLAPSE_THRESHOLD": 24,
}
```

The section owning the active route always renders expanded, including when the active route is a
deep detail, form or action route listed in a destination's `route_names`. That holds server-side,
so it survives a viewer with no JavaScript.

The Studio landing route (`studio_dashboard`) lives in the built-in `home` section, which carries
no title because it has nothing to disclose. A headerless section has no header to expand, so a
site above the threshold arriving on the landing page would otherwise open on a sidebar of closed
headers. When the active section is headerless, the first titled section, in the same order the
sidebar renders, falls open instead. This needs no site configuration: it is the smaller of the two
shapes considered, the alternative being a setting naming which section to open, which every
adopting site would then have to carry even though only the landing page needs it. A section that
genuinely owns the active route is never affected; the fallthrough only ever applies when no titled
section does.

`community_base/studio-nav.js` remembers each section's state per viewer in `localStorage` under
`community-base-studio-nav`. Storage is allowed to be missing, blocked or corrupt: every read and
write is guarded and falls back to the server-rendered state, so the sidebar renders correctly in a
private window or with site data cleared. A stored preference never hides the active section.

## Mounted routes decide what registers

Registering a destination says what an app offers; mounting the app's Studio URL module is
what makes the destination real. A destination is live only when its `url_name` is mounted in
the site URLconf. A section that registered destinations but kept none of them is not rendered
and claims no routes. A site can therefore install an app without mounting its Studio URLs, and
`studio_routes --check` stays green.

The URLconf is read when the shell renders and when the check runs, never during
`AppConfig.ready()`, so registration never forces URL resolution during startup.
`registry.sections()` returns everything that registered; `registry.mounted_sections()` returns
what the site mounts, and the shell and the route check both use the second.

A deep route is claimed only through its destination's home route. Mounting an app's Studio URL
module while the destination's `url_name` is missing leaves that module's routes `mounted but
unclaimed`, so a wrong `url_name` stays an error instead of disappearing quietly.

Run the route partition check after mounting Studio URLs:

```console
uv run python manage.py studio_routes --check
```

It exits unsuccessfully when a mounted route is unclaimed, claimed more than once, or when a live
destination claims a route that is not mounted.

Search providers accept `(request, query)` and return a mapping of group names to JSON-serializable
result lists. Dashboard providers accept `request` and return one card dictionary, an iterable of
cards, or `None`:

```python
from community_base.studio.providers import register_card_provider, register_search_provider

register_search_provider("members", search_members)
register_card_provider("delivery-health", delivery_health_cards)
```

The sidebar search box renders these groups the way the sidebar renders sections: one header per
group, then each result's label with its `summary` underneath. The header text is derived from the
group name, so `event_series` reads as `Event series`; a provider needs no extra field. Groups keep
the order the JSON response lists them in, and an empty group is skipped.

## User management extensions

The shared `/studio/users/` list works with `get_user_model()` and uses only standard Django auth
fields. It supports search, active/staff/inactive status filters, normalized tag filtering, CSV
export and 25-row pagination. Detail pages include tags and `MemberNote` CRUD. Internal notes are
staff-only; code serving notes elsewhere must use `MemberNote.objects.visible_to(user)`.

Sites add their own list and detail data without replacing these views:

```python
from community_base.studio.user_registry import (
    register_user_badge,
    register_user_column,
    register_user_panel,
)

register_user_column("tier", "Tier", render_tier)
register_user_badge(render_subscription_badge)
register_user_panel("Enrollments", "studio/extensions/enrollments.html", enrollment_context)
```

Column and badge renderers receive the displayed user. Panel context providers receive
`(request, user)` and return a context dictionary; the registered template also receives
`detail_user`.

Tags are read and written through `COMMUNITY_BASE["USER_TAGS_ACCESSOR"]`. The configured object
implements `get(user) -> iterable[str]` and `set(user, tags)`. The default accessor uses a `tags`
attribute when the user model provides one and otherwise returns an empty list; configure a site
adapter before enabling tag edits on a user model without that attribute.

## Templates

Shared Studio pages extend `community_base/studio/base.html`. The compatibility template
`studio/base.html` extends the same shell. The shell exposes `title`, `content`, `extra_head`,
`extra_js`, `header_actions`, `body_start` and `studio_icon_script`, plus the AISL compatibility
blocks `studio_title`, `studio_content` and `extra_scripts`.

Every block except `content` and `studio_content` ships empty or with exactly the markup described
below, so a site that overrides nothing renders what it renders today.

### The content-block contract

Every shared Studio page fills its body inside both `{% block content %}` and, nested inside it,
`{% block studio_content %}`, never just one. A site is free to replace
`community_base/studio/base.html` outright with its own shell instead of using the package's
(AI-Shipping-Labs' and DataTalksClub's own Studio bases both do this today), but that replacement
must expose a reachable slot for at least one of the two names. Filling both in every package page
means a site exposing either name renders every page unchanged, with no site-side template change
required; a replacement exposing neither renders the page as an empty shell -- HTTP 200, correct
title, no body, nothing in the response to say why (community-base#279).

`community_base.studio.checks.check_studio_content_block_contract` runs on every `manage.py check`
and raises `community_base.studio.E001` when the resolved `community_base/studio/base.html`
exposes neither name, so a genuinely incompatible site shell fails the check instead of shipping a
silently empty page.

### Skip link and the main landmark

`body_start` is an empty block immediately inside `<body>`, above the impersonation banner and the
sidebar, and `<main>` carries `id="main-content"` with `tabindex="-1"`. Together they let a site
put its own skip link on every Studio page without replacing the shell:

```html
{% block body_start %}
<a class="skip-link" href="#main-content">Skip to content</a>
{% endblock %}
```

`main-content` is the id DataTalksClub/website's skip link and accessibility tests already target,
and the conventional one for this landmark; it is a contract, so it does not change. `tabindex="-1"`
is what makes the jump move keyboard focus and not only the viewport. The package ships no skip
link and no styling for one: the markup, the visually-hidden-until-focused CSS and the wording are
the site's, because they belong to the site's design system and its language.

The block takes anything that must come first in the body, not only a skip link: a live region, a
consent strip, an analytics `noscript` pixel.

### Vendored icon library

The shell loads lucide from the package's own static files, inside the `studio_icon_script` block:

```html
<script src="{% static 'community_base/vendor/lucide.min.js' %}"></script>
```

It is served same-origin because it must run under a `script-src 'self'` Content-Security-Policy,
which DataTalksClub/website sets, and because an unpinned third-party script on a staff surface
executes whatever that host serves that day. The file is the unmodified UMD build of a pinned
lucide release; `community_base/studio/static/community_base/vendor/README.txt` records the
version, the upstream URL, the license and the sha256, and says how to re-derive and verify it.

Override the block when the site already loads lucide itself, to avoid downloading it twice:

```html
{% block studio_icon_script %}{% endblock %}
```

Emptying the block with nothing else providing lucide leaves every `data-lucide` element blank,
because `community_base/studio.js` calls `window.lucide.createIcons()` and finds nothing. The
package cannot tell from the template whether a site loads the library elsewhere, so no check
catches that; it is a deliberate opt-out and a site that takes it owns loading an equivalent build.
Any replacement must define `window.lucide` with `createIcons()` and honour `data-lucide`, and must
load before `community_base/studio.js`, which the head position gives it.

A site that uses lucide icons in its own templates and runs `collectstatic` gets this file for
free at `community_base/vendor/lucide.min.js`; there is no need to vendor a second copy.

### Sidebar footer

The shell exposes `studio_sidebar_footer`, an empty block at the bottom of the sidebar below the
navigation. It ships with no markup, so a site that does not override it sees no change. Use it for
the things only the site knows, such as a version line, a link back to the public site, or a theme
toggle:

```html
{% block studio_sidebar_footer %}
<div class="mt-6 space-y-1 border-t border-border pt-4">
  <a href="/" class="block px-3 py-2 text-sm text-muted-foreground">Back to website</a>
  <button type="button" data-studio-theme-toggle class="px-3 py-2 text-sm">Theme</button>
  <p class="px-3 text-xs text-muted-foreground">v{{ VERSION }}</p>
</div>
{% endblock %}
```

Any element carrying `data-studio-theme-toggle` flips the `dark` class on the document and stores
the choice under the `theme` key the shell reads on the next page load. Both the read and the write
are guarded, so a blocked or empty storage falls back to the viewer's `prefers-color-scheme`.

### Messages

The shell renders Django's message queue at the top of the content region, inside the
`studio_messages` block. The default region carries `data-testid="messages-region"`, and each
message carries `data-message-tag` holding that message's `tags` plus a tint keyed on its level, so
a site that overrides nothing can still tell success from error. A message whose level the package
does not know keeps the neutral card look the shell rendered before tints existed.

Override the block to render a site region instead. The package markup is then not rendered at all,
so the page carries exactly one region:

```html
{% block studio_messages %}
{% include "_partials/messages.html" %}
{% endblock %}
```

An empty override suppresses the shell's messages entirely, which is what a site that drains the
queue somewhere else wants.

### Content banner

`studio_banner` is an empty block between `<main>` and the padded content column. It is where a
full-bleed strip goes, such as an environment-mismatch warning; overriding `content` instead puts
the strip inside the column's padding. The block ships with no markup.

### Navigation hooks

Every sidebar link carries `data-testid="studio-nav-<destination key>"` and the focus-visible ring
`focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent`. The test id derives
from the destination key, which the registry keeps unique, so it survives a change of title,
section, order or grouping.

### Quick jump

Ctrl-K and Cmd-K open a command palette, `studio_quick_jump`, over the same `studio_global_search`
endpoint and grouped results the sidebar search box renders; there is no second endpoint and no
second copy of the fetch or render logic. The overlay carries `data-studio-quick-jump` and
`data-testid="studio-quick-jump"`, its input `data-testid="studio-quick-jump-input"` and its
results list `data-testid="studio-quick-jump-results"`, matching the donor hook so an adopting
site's own tests keep selecting the right elements without a remap.

The package already claimed the Ctrl/Cmd-K chord to focus the sidebar search box before this
overlay existed, so the chord is not double-handled: it opens the overlay when
`studio_quick_jump` renders one, and falls back to focusing the sidebar box, unchanged, when a
site overrides the block away. Inside the overlay, Escape or a click on the backdrop closes it and
returns focus to whatever had it before opening; Tab and Shift+Tab cycle without leaving the
dialog; ArrowUp and ArrowDown move the selection over the rendered results and Enter follows the
selected (or first) result's link. A destination hidden from the viewer by `superuser_only` or a
feature flag is absent from the palette for the same reason it is absent from the sidebar box:
both read the one JSON response.

### Mobile sidebar scroll affordance

`#studio-sidebar-scroll-affordance` is a gradient hint at the foot of the sidebar nav, shown only
while the mobile drawer can scroll further and hidden again once scrolled to the bottom. It ships
`md:hidden`, so it never renders at the desktop breakpoint, and it sits inside `<nav>` so the
`studio_sidebar_footer` hook stays empty by default.

Load `{% load studio_filters %}` for:

- `studio_list_filter`, `studio_empty_state`, `studio_status_badge` and `studio_list_action`
- `studio_message_class`, the tint one flash message gets from its level
- `studio_header_actions` and `studio_overflow_menu`
- `studio_list_class` and `studio_action_class`
- `operator_date`, `operator_datetime`, `operator_datetime_seconds` and `operator_datetime_tz`
- `model_name` and `dict_get`

Use `studio_pagination_context` from `community_base.studio.utils` with the
`community_base/studio/includes/list_pager.html` include.

## CSS build

Run `make css-build` at the repository root. It installs the pinned local Tailwind dependency and
writes the committed `community_base/studio/static/community_base/studio.css` file.

The build scans package templates, Python modules and the JavaScript under `static/`, so a class
used only from a script is generated too.

A site that uses utility classes not present in package templates must run its own Tailwind build.
Use `community_base/studio/assets/tailwind.config.js` as a preset, add the site's template paths to
`content`, and include `community_base/studio/assets/tailwind.css` as the input source.

## Site extension stylesheets

Set `COMMUNITY_BASE["STUDIO_EXTRA_CSS"]` to a tuple of static paths that the shell loads after its
own `community_base/studio.css`:

```python
COMMUNITY_BASE = {
    "STUDIO_EXTRA_CSS": ("css/studio-site.css",),
}
```

Every path is resolved with `{% static %}` from the site's static files. Keep package generic CSS
and site extension CSS separate: the shell never loads or copies site assets into the package, and
the extension stylesheet adds site classes instead of overriding the shell's generic ones.
