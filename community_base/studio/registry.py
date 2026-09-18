"""Registration and active-route state for the shared Studio sidebar."""

from dataclasses import dataclass, field

from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from community_base.kernel import conf
from community_base.studio.route_names import urlconf_route_names


@dataclass(frozen=True)
class Destination:
    """One sidebar link.

    A destination normally points at a mounted Studio route through `url_name`.
    Set `external_url` instead for a link that leaves the Studio URLconf, such
    as generated API documentation; such a destination claims no route names and
    is never the active link. `icon` names one lucide icon and defaults to the
    unadorned label the shell rendered before icons existed.
    """

    key: str
    title: str
    url_name: str
    route_names: tuple[str, ...]
    order: int
    superuser_only: bool = False
    feature_flag: str = ""
    icon: str = ""
    external_url: str = ""
    new_tab: bool = False


@dataclass(frozen=True)
class DestinationGroup:
    """A disclosure subsection inside a section, rendered as a nested group."""

    key: str
    title: str
    order: int
    destinations: tuple[Destination, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Section:
    slug: str
    title: str
    order: int
    icon: str
    destinations: tuple[Destination, ...] = field(default_factory=tuple)
    groups: tuple[DestinationGroup, ...] = field(default_factory=tuple)


_sections: dict[str, Section] = {}

# Routes may deliberately own a section without claiming a destination, or
# render outside the shell altogether. Extensions populate these alongside
# their section registration.
section_only_routes: dict[str, str] = {}
routes_without_home: set[str] = set()


def _iter_destinations(section: Section):
    """Yield every destination of a section, flat and grouped."""

    yield from section.destinations
    for group in section.groups:
        yield from group.destinations


def register(section: Section) -> Section:
    """Register one section, rejecting ambiguous navigation ownership."""

    existing_section = _sections.get(section.slug)
    if existing_section and (
        existing_section.title,
        existing_section.order,
        existing_section.icon,
    ) != (section.title, section.order, section.icon):
        raise ValueError(f"Studio section metadata conflicts: {section.slug}")

    seen_group_keys = set()
    for group in section.groups:
        if group.key in seen_group_keys:
            raise ValueError(f"Studio destination group already registered: {group.key}")
        seen_group_keys.add(group.key)

    claimed_keys = {
        item.key for existing in _sections.values() for item in _iter_destinations(existing)
    }
    claimed_routes = {
        route_name
        for existing in _sections.values()
        for item in _iter_destinations(existing)
        for route_name in item.route_names
    }
    for destination in _iter_destinations(section):
        if destination.key in claimed_keys:
            raise ValueError(f"Studio destination already registered: {destination.key}")
        overlap = claimed_routes.intersection(destination.route_names)
        if overlap:
            route_name = sorted(overlap)[0]
            raise ValueError(f"Studio route already registered: {route_name}")
        claimed_keys.add(destination.key)
        claimed_routes.update(destination.route_names)

    if existing_section:
        merged_groups: dict[str, DestinationGroup] = {
            group.key: group for group in existing_section.groups
        }
        for group in section.groups:
            current = merged_groups.get(group.key)
            if current is None:
                merged_groups[group.key] = group
            elif (current.title, current.order) != (group.title, group.order):
                raise ValueError(f"Studio destination group conflicts: {section.slug}/{group.key}")
            else:
                merged_groups[group.key] = DestinationGroup(
                    key=current.key,
                    title=current.title,
                    order=current.order,
                    destinations=current.destinations + group.destinations,
                )
        section = Section(
            slug=existing_section.slug,
            title=existing_section.title,
            order=existing_section.order,
            icon=existing_section.icon,
            destinations=existing_section.destinations + section.destinations,
            groups=tuple(merged_groups.values()),
        )
    _sections[section.slug] = section
    return section


def sections() -> tuple[Section, ...]:
    """Return sections, destinations and groups in deterministic display order."""

    ordered = []
    for section in sorted(_sections.values(), key=lambda item: (item.order, item.slug)):
        destinations = tuple(sorted(section.destinations, key=lambda item: (item.order, item.key)))
        groups = tuple(
            DestinationGroup(
                key=group.key,
                title=group.title,
                order=group.order,
                destinations=tuple(
                    sorted(group.destinations, key=lambda item: (item.order, item.key))
                ),
            )
            for group in sorted(section.groups, key=lambda group: (group.order, group.key))
        )
        ordered.append(
            Section(section.slug, section.title, section.order, section.icon, destinations, groups)
        )
    return tuple(ordered)


def _is_live(destination, mounted: set[str]) -> bool:
    """Whether a destination is reachable on this site.

    A destination whose link is an ``external_url`` has no route to mount, so it
    is always live: it points off the URLconf by design (C7.14) and claims no
    route name. Every other destination is live when its home route is mounted.
    """

    if getattr(destination, "external_url", ""):
        return True
    return destination.url_name in mounted


def _mounted_section(section: Section, mounted: set[str]) -> Section:
    """Rebuild one section from the destinations whose home route is mounted."""

    destinations = tuple(item for item in section.destinations if _is_live(item, mounted))
    groups = []
    for group in section.groups:
        group_destinations = tuple(item for item in group.destinations if _is_live(item, mounted))
        if group_destinations:
            groups.append(
                DestinationGroup(
                    key=group.key,
                    title=group.title,
                    order=group.order,
                    destinations=group_destinations,
                )
            )
    return Section(
        slug=section.slug,
        title=section.title,
        order=section.order,
        icon=section.icon,
        destinations=destinations,
        groups=tuple(groups),
    )


def mounted_sections(*, resolver=None) -> tuple[Section, ...]:
    """Return the sections restricted to destinations the site actually mounts.

    Installing an app registers its destinations; mounting the app's Studio URL
    module is what makes them real. A destination is live when its ``url_name``
    is mounted, and a section that registered destinations but kept none of them
    is dropped entirely. The URLconf is read here rather than at registration
    time, so ``AppConfig.ready()`` never has to resolve URLs.
    """

    mounted = urlconf_route_names(resolver=resolver)
    live = []
    for section in sections():
        restricted = _mounted_section(section, mounted)
        registered_anything = bool(section.destinations or section.groups)
        kept_anything = bool(restricted.destinations or restricted.groups)
        if kept_anything or not registered_anything:
            live.append(restricted)
    return tuple(live)


def route_name_for(target) -> str:
    """Resolve a request or path to a URL name, degrading safely to empty."""

    resolver_match = getattr(target, "resolver_match", None)
    if resolver_match is not None:
        return getattr(resolver_match, "url_name", "") or ""
    path = target if isinstance(target, str) else getattr(target, "path", "")
    if not path:
        return ""
    try:
        return resolve(path).url_name or ""
    except Resolver404:
        return ""


def _collapse_threshold() -> int:
    """Return the destination count above which unrelated sections start closed."""

    try:
        return int(conf.get("STUDIO_NAV_COLLAPSE_THRESHOLD"))
    except (TypeError, ValueError):
        return 24


def _apply_collapse_state(rendered_sections: list[dict]) -> None:
    """Decide which sections render expanded, in place, once the active one is known.

    A section without a title has no header to click, so it is never collapsible.
    Below the threshold every section renders expanded, which is the behaviour a
    site with a small registry had before collapse existed. Above it only the
    active section starts open; the rest are one click away.

    The active section can itself be headerless, such as the built-in `home`
    section that owns the landing route: there is then no header for the
    active-route guarantee to open, and a dense registry would render every
    titled section collapsed on the page the viewer just landed on. When that
    happens, the first titled section (in the same display order as the
    sidebar) falls open instead, so the landing page never opens on a wall of
    closed headers. This never overrides a real active titled section, and it
    has no effect below the threshold, where every section is already open.
    """

    visible = sum(
        len(item["destinations"]) + sum(len(row["destinations"]) for row in item["groups"])
        for item in rendered_sections
    )
    dense = visible > _collapse_threshold()

    active_titled_section = any(
        item["active"] and item["section"].title for item in rendered_sections
    )
    fallback_slug = ""
    if dense and not active_titled_section:
        for item in rendered_sections:
            if item["section"].title:
                fallback_slug = item["section"].slug
                break

    for item in rendered_sections:
        collapsible = bool(item["section"].title)
        item["collapsible"] = collapsible
        item["expanded"] = (
            not collapsible or not dense or item["active"] or item["section"].slug == fallback_slug
        )


def _destination_url(destination: Destination) -> str:
    """Resolve a destination to a href, degrading safely to an empty string."""

    if destination.external_url:
        return destination.external_url
    if not destination.url_name:
        return ""
    try:
        return reverse(destination.url_name)
    except NoReverseMatch:
        return ""


def _visible(destination: Destination, is_superuser: bool) -> bool:
    """Render a destination only when its staff scope and feature flag allow it."""

    if destination.superuser_only and not is_superuser:
        return False
    if destination.feature_flag and not conf.get(destination.feature_flag):
        return False
    return True


def active_state(request) -> dict:
    """Build render-ready sections and active state from the resolved route."""

    route_name = route_name_for(request)
    active_section = section_only_routes.get(route_name, "")
    active_destination = ""
    rendered_sections = []
    is_superuser = bool(getattr(getattr(request, "user", None), "is_superuser", False))

    for section in mounted_sections():
        rendered_destinations = []
        for destination in section.destinations:
            if not _visible(destination, is_superuser):
                continue
            is_active = route_name in destination.route_names
            if is_active:
                active_section = section.slug
                active_destination = destination.key
            url = _destination_url(destination)
            rendered_destinations.append(
                {"destination": destination, "active": is_active, "url": url}
            )
        rendered_groups = []
        for group in section.groups:
            rendered_group_destinations = []
            group_active = False
            for destination in group.destinations:
                if not _visible(destination, is_superuser):
                    continue
                is_active = route_name in destination.route_names
                if is_active:
                    active_section = section.slug
                    active_destination = destination.key
                    group_active = True
                url = _destination_url(destination)
                rendered_group_destinations.append(
                    {"destination": destination, "active": is_active, "url": url}
                )
            if rendered_group_destinations:
                rendered_groups.append(
                    {
                        "group": group,
                        "active": group_active,
                        "destinations": rendered_group_destinations,
                    }
                )
        rendered_sections.append(
            {
                "section": section,
                "destinations": rendered_destinations,
                "groups": rendered_groups,
                "active": section.slug == active_section,
            }
        )

    _apply_collapse_state(rendered_sections)

    return {
        "active_section": active_section,
        "active_destination": active_destination,
        "route_name": route_name,
        "sections": rendered_sections,
    }


def _clear() -> None:
    """Reset process-local registrations for isolated tests."""

    _sections.clear()
    section_only_routes.clear()
    routes_without_home.clear()
