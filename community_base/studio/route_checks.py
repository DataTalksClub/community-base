"""URL partition checks for the installed Studio mount."""

from collections import defaultdict

from django.urls import URLPattern, URLResolver, get_resolver

from community_base.studio.registry import routes_without_home, section_only_routes, sections


def mounted_route_names(*, mount="studio/", resolver=None) -> set[str]:
    names = set()

    def walk(patterns, prefix=""):
        for entry in patterns:
            path = prefix + str(entry.pattern)
            if isinstance(entry, URLResolver):
                walk(entry.url_patterns, path)
            elif isinstance(entry, URLPattern) and path.startswith(mount) and entry.name:
                names.add(entry.name)

    walk((resolver or get_resolver()).url_patterns)
    return names


def route_claims() -> dict[str, list[str]]:
    claims = defaultdict(list)
    for section in sections():
        for destination in section.destinations:
            for route_name in destination.route_names:
                claims[route_name].append(f"destination:{section.slug}/{destination.key}")
    for route_name, section_slug in section_only_routes.items():
        claims[route_name].append(f"section:{section_slug}")
    for route_name in routes_without_home:
        claims[route_name].append("without-home")
    return dict(claims)


def route_partition_errors(*, mount="studio/", resolver=None) -> list[str]:
    mounted = mounted_route_names(mount=mount, resolver=resolver)
    claims = route_claims()
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
