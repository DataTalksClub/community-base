# Studio

The Studio app provides the shared operator shell, route-aware navigation, reusable template
components, dashboard and search extension points, and audited user impersonation. Add
`"community_base.studio"` to `INSTALLED_APPS` and mount its routes first under the Studio prefix:

```python
(path("studio/", include("community_base.studio.urls")),)
```

All built-in views require staff access. Starting impersonation additionally requires a superuser;
restoration succeeds only when the session points back to an active superuser. Configure
`COMMUNITY_BASE["STUDIO_AUDIT_WRITER"]` with a callable accepting the keyword arguments `event`,
`actor_ref`, `target_ref` and `metadata`. Identifiers are opaque strings; the package does not put
email addresses in audit events.

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

Search providers accept `(request, query)` and return a mapping of group names to JSON-serializable
result lists. Dashboard providers accept `request` and return one card dictionary, an iterable of
cards, or `None`:

```python
from community_base.studio.providers import register_card_provider, register_search_provider

register_search_provider("members", search_members)
register_card_provider("delivery-health", delivery_health_cards)
```

## Templates

Shared Studio pages extend `community_base/studio/base.html`. The compatibility template
`studio/base.html` extends the same shell. The shell exposes `title`, `content`, `extra_head`,
`extra_js` and `header_actions`, plus the AISL compatibility blocks `studio_title`,
`studio_content` and `extra_scripts`.

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
