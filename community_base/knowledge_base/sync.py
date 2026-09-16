"""The ``content_sync`` upsert contract for knowledge base pages.

Sites own the parsers. A site parser registers its content type with
``community_base.content_sync.parsers.register_parser`` and, in ``upsert``,
applies each item through :func:`upsert_page`. The contract:

- item identity is the page slug, unique within the section;
- ``source_checksum`` is the change signal -- the parser folds everything the
  record derives from (including resolved parent references) into it, the way
  the DataTalks.Club docs parser does;
- ``discover`` returns items ordered so a parent's item precedes every child's
  item; :func:`upsert_page` refuses a parent slug that does not exist yet
  rather than silently dropping hierarchy;
- synced rows carry the source's id in ``source_content_id``, which gives
  :func:`delete_missing` its ownership scope;
- a page that vanishes from the repository is drafted, not deleted, the way
  curriculum drafts vanished courses.

Studio-authored pages carry no provenance and are never touched by sync.
"""

from django.db import transaction

from community_base.knowledge_base.models import (
    SECTION_CHOICES,
    SECTION_WIKI,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    KnowledgeBasePage,
)

ACTION_CREATED = "created"
ACTION_UPDATED = "updated"
ACTION_UNCHANGED = "unchanged"

SECTIONS = tuple(value for value, _label in SECTION_CHOICES)


class KnowledgeBaseSyncError(Exception):
    """A sync item violates the page contract (unknown parent, cycle, section)."""


def upsert_page(
    source,
    *,
    section: str,
    slug: str,
    title: str,
    body: str = "",
    summary: str = "",
    parent_slug: str | None = None,
    nav_order: int = 0,
    commit_sha: str,
    source_path: str,
    checksum: str,
) -> tuple[KnowledgeBasePage, str]:
    """Create, update or leave unchanged one page; returns ``(page, action)``.

    The parent must already exist within the same section, so a parser
    discovers parents before children. An unchanged page (same checksum and
    commit) is left completely alone except that a previously drafted page is
    republished -- its return to the repository is itself a change.
    """

    if section not in SECTIONS:
        raise KnowledgeBaseSyncError(f"Unknown knowledge base section: {section!r}")
    if not slug:
        raise KnowledgeBaseSyncError("A knowledge base page requires a slug.")
    if not title:
        raise KnowledgeBaseSyncError(f"Knowledge base page {slug!r} requires a title.")
    if section == SECTION_WIKI and parent_slug:
        raise KnowledgeBaseSyncError(
            f"Knowledge base page {slug!r} is a wiki page; wiki pages cannot have a parent."
        )

    parent = None
    if parent_slug:
        parent = KnowledgeBasePage.objects.filter(section=section, slug=parent_slug).first()
        if parent is None:
            raise KnowledgeBaseSyncError(
                f"Knowledge base page {slug!r} references parent {parent_slug!r} "
                "that does not exist yet; discover parents before children."
            )

    with transaction.atomic():
        page = KnowledgeBasePage.objects.filter(section=section, slug=slug).first()
        if page is None:
            page = KnowledgeBasePage(section=section, slug=slug)
            action = ACTION_CREATED
        elif (
            page.source_checksum == checksum
            and page.source_commit_sha == commit_sha
            and page.status == STATUS_PUBLISHED
        ):
            return page, ACTION_UNCHANGED
        else:
            action = ACTION_UPDATED

        if parent is not None and _would_create_cycle(page, parent):
            raise KnowledgeBaseSyncError(
                f"Knowledge base page {slug!r} cannot be nested under {parent.slug!r}: "
                "the parent chain already reaches the page."
            )

        page.title = title
        page.summary = summary
        page.body = body
        page.parent = parent
        page.nav_order = nav_order
        page.status = STATUS_PUBLISHED
        page.source_content_id = getattr(source, "pk", None)
        page.source_path = source_path
        page.source_commit_sha = commit_sha
        page.source_checksum = checksum
        page.full_clean()
        page.save()
    return page, action


def _would_create_cycle(page: KnowledgeBasePage, parent: KnowledgeBasePage) -> bool:
    """Whether making ``parent`` the parent of ``page`` closes a cycle."""

    current: KnowledgeBasePage | None = parent
    seen: set[int] = set()
    while current is not None:
        if current.pk == page.pk or current.pk in seen:
            return current.pk == page.pk
        seen.add(current.pk)
        current = current.parent
    return False


def delete_missing(source, section: str, seen_slugs: set[str] | frozenset[str]):
    """Draft this source's published pages of the section that the repository no
    longer lists. Rows synced by other sources, and Studio-authored rows, are
    never touched.
    """

    missing = (
        KnowledgeBasePage.objects.filter(
            section=section,
            status=STATUS_PUBLISHED,
            source_content_id=getattr(source, "pk", None),
        )
        .exclude(slug__in=set(seen_slugs))
        .order_by("slug")
    )
    drafted: list[KnowledgeBasePage] = []
    for page in missing:
        page.status = STATUS_DRAFT
        page.save(update_fields=["status", "updated_at"])
        drafted.append(page)
    return drafted
