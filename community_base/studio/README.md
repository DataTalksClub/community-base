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

`community_base/studio-nav.js` remembers each section's state per viewer in `localStorage` under
`community-base-studio-nav`. Storage is allowed to be missing, blocked or corrupt: every read and
write is guarded and falls back to the server-rendered state, so the sidebar renders correctly in a
private window or with site data cleared. A stored preference never hides the active section.

Run the route partition check after mounting Studio URLs:

```console
uv run python manage.py studio_routes --check
```

It exits unsuccessfully when a mounted route is unclaimed, claimed more than once, or when a
registration refers to a route that is not mounted.

Search providers accept `(request, query)` and return a mapping of group names to JSON-serializable
result lists. Dashboard providers accept `request` and return one card dictionary, an iterable of
cards, or `None`:

```python
from community_base.studio.providers import register_card_provider, register_search_provider

register_search_provider("members", search_members)
register_card_provider("delivery-health", delivery_health_cards)
```

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
`extra_js` and `header_actions`, plus the AISL compatibility blocks `studio_title`,
`studio_content` and `extra_scripts`.

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

Load `{% load studio_filters %}` for:

- `studio_list_filter`, `studio_empty_state`, `studio_status_badge` and `studio_list_action`
- `studio_header_actions` and `studio_overflow_menu`
- `studio_list_class` and `studio_action_class`
- `operator_date`, `operator_datetime`, `operator_datetime_seconds` and `operator_datetime_tz`
- `model_name` and `dict_get`

Use `studio_pagination_context` from `community_base.studio.utils` with the
`community_base/studio/includes/list_pager.html` include.

## CSS build

Run `make css-build` at the repository root. It installs the pinned local Tailwind dependency and
writes the committed `community_base/studio/static/community_base/studio.css` file.

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
