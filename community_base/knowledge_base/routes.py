"""Where a synced row of this app lives, and how a reference reaches it.

`FORMAT.md` section 3.4 says the package apps compute a default route from
`(kind, path)` and a site may map it; section 3.7 says a cross-reference
resolves to that route and that a reference into another source is answered by
a `routes(kind, target)` callable the toolkit is given. This module is both
halves for the three kinds this app stores, so a stored `public_path` and the
`href` inside rendered HTML are produced by one function and cannot drift.

The package ships public routes for `wiki` and `docs` (``urls.py``) and none
for `person` (decision D31); the path below is what a site that mounts its own
routes matches, and it is what a reference resolves to either way.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from community_base.content_sync.kinds import get_kind, is_registered

#: The kinds this app stores, and the section each `KnowledgeBasePage` takes.
PAGE_KINDS = ("wiki", "docs")
PERSON_KIND = "person"
PACKAGE_KINDS = (*PAGE_KINDS, PERSON_KIND)


def default_public_path(kind: str, path: str) -> str:
    """The kind's declared route as a root-relative path with a trailing slash.

    A tree kind's collection root has an empty path (the root `index.md`
    contributes no slug), so `docs` alone is `/docs/`.
    """

    route = None
    if is_registered(kind):
        route = get_kind(kind).route
    target = route(path) if route is not None else f"{kind}/{path}"
    trimmed = target.strip("/")
    return f"/{trimmed}/" if trimmed else f"/{kind}/"


def stored_route(kind: str, target: str) -> str | None:
    """The public path of the row a reference names, or None when there is none.

    Resolution happens at sync against the rows already synced (section 3.7),
    so this is a query and not a computation: a person synced by an earlier
    source is found here, and a page whose site stored its own `public_path`
    answers with that path rather than with the package default.
    """

    from community_base.knowledge_base.models import Person

    if kind == PERSON_KIND:
        person = Person.objects.filter(slug=target).first()
        return None if person is None else person.get_absolute_url()
    if kind in PAGE_KINDS:
        page = _page(kind, target)
        return None if page is None else page.get_absolute_url()
    return None


def route_resolver(declared: Iterable[str] = ()) -> Callable[[str, str], str | None]:
    """The `routes` callable the toolkit resolves cross-references through.

    A target this app already stores answers with its own path. A target of a
    kind the repository being synced declares itself answers with the default
    path, because the row is written by this very sync and does not exist yet
    when its siblings resolve; the toolkit has already checked that the item
    is in the repository before it asks. Every other kind answers None, which
    leaves the reference to the sync that owns it rather than reporting it.
    """

    names = frozenset(declared)

    def routes(kind: str, target: str) -> str | None:
        found = stored_route(kind, target)
        if found is not None:
            return found
        if kind in names and kind in PACKAGE_KINDS:
            return default_public_path(kind, target)
        return None

    return routes


def _page(kind: str, target: str):
    from community_base.knowledge_base.models import SECTION_WIKI, KnowledgeBasePage

    queryset = KnowledgeBasePage.objects.filter(section=kind)
    if kind == SECTION_WIKI:
        return queryset.filter(slug=target).first()
    # A docs target is a path, and the stored public path is that path: one
    # lookup instead of a walk down the parent chain.
    return queryset.filter(public_path=default_public_path(kind, target)).first()
