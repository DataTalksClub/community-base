"""URL partition checks for the installed Studio mount."""

from collections import defaultdict

from community_base.studio.registry import (
    mounted_sections,
    routes_without_home,
    section_only_routes,
)
from community_base.studio.route_names import urlconf_route_names


def mounted_route_names(*, mount="studio/", resolver=None) -> set[str]:
    return urlconf_route_names(prefix=mount, resolver=resolver)


def route_claims(*, resolver=None) -> dict[str, list[str]]:
    claims = defaultdict(list)
    for section in mounted_sections(resolver=resolver):
        for destination in section.destinations:
            for route_name in destination.route_names:
                claims[route_name].append(f"destination:{section.slug}/{destination.key}")
        for group in section.groups:
            for destination in group.destinations:
                for route_name in destination.route_names:
                    claims[route_name].append(
                        f"destination:{section.slug}/{group.key}/{destination.key}"
                    )
    for route_name, section_slug in section_only_routes.items():
        claims[route_name].append(f"section:{section_slug}")
    for route_name in routes_without_home:
        claims[route_name].append("without-home")
    return dict(claims)


def route_partition_errors(*, mount="studio/", resolver=None) -> list[str]:
    mounted = mounted_route_names(mount=mount, resolver=resolver)
    claims = route_claims(resolver=resolver)
    errors = []
    for route_name in sorted(mounted | claims.keys()):
        owners = claims.get(route_name, [])
        if route_name not in mounted:
            errors.append(f"{route_name}: claimed but not mounted")
        elif not owners:
            errors.append(f"{route_name}: mounted but unclaimed")
        elif len(owners) > 1:
            errors.append(f"{route_name}: claimed {len(owners)} times ({', '.join(owners)})")
    return errors
