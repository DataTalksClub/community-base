"""URL partition checks for the installed Studio mount."""

from collections import defaultdict

from community_base.studio.registry import (
    destination_route_names,
    mounted_sections,
    routes_without_home,
    section_only_routes,
)
from community_base.studio.route_names import (
    qualify,
    studio_mount_prefix,
    studio_namespace,
    urlconf_route_names,
)


def mounted_route_names(*, mount=None, resolver=None) -> set[str]:
    """Route names under the Studio mount, found rather than assumed.

    Nothing reserves ``studio/``: a site is free to mount the Studio at
    ``manage/``, and hardcoding the prefix reported every claimed route as
    ``claimed but not mounted`` there. The default is where the site actually
    mounts the package's Studio URL module; pass ``mount`` for a site whose
    Studio routes live under a different path than that module.
    """

    if mount is None:
        mount = studio_mount_prefix(resolver=resolver)
    return urlconf_route_names(prefix=mount, resolver=resolver)


def route_claims(*, resolver=None) -> dict[str, list[str]]:
    """Which navigation entry owns each route, spelled as the URLconf mounts it."""

    studio_ns = studio_namespace(resolver=resolver)
    claims = defaultdict(list)
    for section in mounted_sections(resolver=resolver):
        for destination in section.destinations:
            for route_name in destination_route_names(destination, studio_ns=studio_ns):
                claims[route_name].append(f"destination:{section.slug}/{destination.key}")
        for group in section.groups:
            for destination in group.destinations:
                for route_name in destination_route_names(destination, studio_ns=studio_ns):
                    claims[route_name].append(
                        f"destination:{section.slug}/{group.key}/{destination.key}"
                    )
    for route_name, section_slug in section_only_routes.items():
        claims[qualify(route_name, studio_ns)].append(f"section:{section_slug}")
    for route_name in routes_without_home:
        claims[qualify(route_name, studio_ns)].append("without-home")
    return dict(claims)


def route_partition_errors(*, mount=None, resolver=None) -> list[str]:
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
