"""Documentation hierarchy resolution for the knowledge base.

Lifted from the DataTalks.Club docs projection (``content/docs_projection.py``):
the explicit parent link is the only ancestry input -- URL segments and titles
are never used to guess a parent -- siblings order by ``nav_order`` with title
and slug as deterministic tie-breakers, and the depth-first pre-order is the
reading order behind Previous/Next navigation. The wiki section resolves to a
flat, title-ordered set instead: a wiki page has no parent by model rule.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from django.db.models.functions import Lower

from community_base.knowledge_base.models import (
    SECTION_DOCS,
    SECTION_WIKI,
    STATUS_PUBLISHED,
    KnowledgeBasePage,
)


@dataclass(frozen=True)
class NavigationItem:
    """One immutable page position in the documentation tree."""

    page: KnowledgeBasePage
    children: tuple["NavigationItem", ...]

    @property
    def title(self) -> str:
        return self.page.title

    @property
    def slug(self) -> str:
        return self.page.slug


@dataclass(frozen=True)
class NavigationTree:
    """A validated hierarchy and its deterministic depth-first reading order.

    ``by_pk`` is the total index. ``by_slug`` is a convenience for a section
    whose slugs are unique; where a leaf slug repeats under different parents
    it holds only one of them, so look a page up by ``pk``.
    """

    section: str
    roots: tuple[NavigationItem, ...]
    preorder: tuple[NavigationItem, ...]
    by_slug: Mapping[str, NavigationItem]
    by_pk: Mapping[int, NavigationItem]


def _nav_key(page: KnowledgeBasePage) -> tuple[int, str, str]:
    """Sibling order: nav_order, then title casefolded, then slug."""

    return page.nav_order, page.title.casefold(), page.slug


def _raise_hierarchy_error(code: str, page: KnowledgeBasePage) -> ImproperlyConfigured:
    return ImproperlyConfigured(f"Knowledge base hierarchy {code}: {page.slug}")


def published_pages(section: str) -> QuerySet[KnowledgeBasePage]:
    """The published rows of one section, in the model's canonical order."""

    return KnowledgeBasePage.objects.filter(section=section, status=STATUS_PUBLISHED)


def wiki_pages() -> QuerySet[KnowledgeBasePage]:
    """The flat wiki set, A-Z by title (casefolded), then slug."""

    return published_pages(SECTION_WIKI).order_by(Lower("title"), "slug")


def _detect_cycles(pages: Iterable[KnowledgeBasePage]) -> None:
    """Refuse every parent cycle, including ones no root can reach."""

    parent_ids = {page.pk: page.parent_id for page in pages if page.parent_id is not None}
    resolved: set[int] = set()
    for start_id in parent_ids:
        if start_id in resolved:
            continue
        chain: list[int] = []
        positions: dict[int, int] = {}
        current: int | None = start_id
        while current is not None and current in parent_ids:
            if current in resolved:
                break
            if current in positions:
                slug = KnowledgeBasePage.objects.get(pk=current).slug
                raise ImproperlyConfigured(f"Knowledge base hierarchy parent_cycle: {slug}")
            positions[current] = len(chain)
            chain.append(current)
            current = parent_ids[current]
        resolved.update(chain)


def navigation_tree(section: str = SECTION_DOCS) -> NavigationTree:
    """Validate and build the section's tree from the published parent links.

    A published page whose parent row is not itself published renders as a
    top-level page: a draft parent must not hide the published pages under it.
    Every other anomaly -- a self-parent or a cycle, which only unvalidated
    writes can produce -- raises before any tree is returned.
    """

    pages = list(published_pages(section))
    _detect_cycles(pages)
    known_ids = {page.pk for page in pages}

    children_by_parent: dict[int | None, list[KnowledgeBasePage]] = {}
    for page in pages:
        parent_id = page.parent_id if page.parent_id in known_ids else None
        children_by_parent.setdefault(parent_id, []).append(page)
    for children in children_by_parent.values():
        children.sort(key=_nav_key)

    by_slug: dict[str, NavigationItem] = {}
    by_pk: dict[int, NavigationItem] = {}

    def build_item(page: KnowledgeBasePage) -> NavigationItem:
        item = NavigationItem(
            page=page,
            children=tuple(build_item(child) for child in children_by_parent.get(page.pk, ())),
        )
        by_slug[page.slug] = item
        by_pk[page.pk] = item
        return item

    roots = tuple(build_item(page) for page in children_by_parent.get(None, ()))
    preorder: list[NavigationItem] = []

    def visit(item: NavigationItem) -> None:
        preorder.append(item)
        for child in item.children:
            visit(child)

    for root in roots:
        visit(root)
    return NavigationTree(
        section=section,
        roots=roots,
        preorder=tuple(preorder),
        by_slug=MappingProxyType(dict(by_slug)),
        by_pk=MappingProxyType(dict(by_pk)),
    )


def children_of(page: KnowledgeBasePage) -> tuple[KnowledgeBasePage, ...]:
    """The page's published children in sibling order."""

    if page.section == SECTION_WIKI:
        return ()
    siblings = published_pages(page.section).filter(parent=page)
    return tuple(siblings.order_by("nav_order", Lower("title"), "slug"))


def breadcrumbs(page: KnowledgeBasePage) -> tuple[KnowledgeBasePage, ...]:
    """The page's ancestors from the root down to its direct parent."""

    chain: list[KnowledgeBasePage] = []
    current = page
    seen = {page.pk}
    while current.parent_id is not None:
        current = current.parent
        if current.pk in seen:
            break
        seen.add(current.pk)
        chain.append(current)
    chain.reverse()
    return tuple(chain)


def sequential_navigation(
    page: KnowledgeBasePage,
) -> tuple[KnowledgeBasePage | None, KnowledgeBasePage | None]:
    """Adjacent detail pages in depth-first pre-order: (previous, next)."""

    tree = navigation_tree(page.section)
    # By pk, not slug: a repeated leaf slug would otherwise find a namesake
    # under another parent and report that page's neighbours.
    item = tree.by_pk.get(page.pk)
    if item is None:
        return None, None
    items = tree.preorder
    index = items.index(item)
    previous = items[index - 1].page if index else None
    following = items[index + 1].page if index + 1 < len(items) else None
    return previous, following


def sibling_navigation(
    page: KnowledgeBasePage,
) -> tuple[KnowledgeBasePage | None, KnowledgeBasePage | None]:
    """Adjacent siblings in sibling order: (previous, next)."""

    siblings = list(
        published_pages(page.section)
        .filter(parent_id=page.parent_id)
        .order_by("nav_order", Lower("title"), "slug")
    )
    for index, sibling in enumerate(siblings):
        if sibling.pk == page.pk:
            previous = siblings[index - 1] if index else None
            following = siblings[index + 1] if index + 1 < len(siblings) else None
            return previous, following
    return None, None
