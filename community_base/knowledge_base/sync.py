"""The ``content_sync`` upsert contract for knowledge base pages and people.

The package parsers for the `wiki`, `docs` and `person` kinds
(``knowledge_base.content_sync_parsers``, decision D24) apply each item through
:func:`upsert_page` and :func:`upsert_person`. A site that fills these models
from a shape of its own registers its own parser with
``community_base.content_sync.parsers.register_parser`` and applies items the
same way. The contract:

- item identity is the page slug within its parent, so the same leaf slug
  may repeat under different parents; a site whose slugs are unique across the
  section (AISL) is the special case where the parent never matters;
- ``source_checksum`` is the change signal -- the parser folds everything the
  record derives from (including resolved parent references) into it, the way
  the DataTalks.Club docs parser does;
- ``discover`` returns items ordered so a parent's item precedes every child's
  item; :func:`upsert_page` refuses a parent reference that does not exist yet
  rather than silently dropping hierarchy. A parent is named either by
  ``parent_slug`` (section-wide, which must resolve to exactly one page) or by
  ``parent_path`` (the slug chain from the section root down to the parent),
  which is the shape a tree with repeated leaf slugs needs;
- a site that needs to keep more than the app's fields passes ``record``, a
  JSON object the package stores and never interprets;
- a site that renders the page itself passes ``body_html``, which is
  sanitized and stored instead of the app's markdown rendering;
- a site that owns its routes passes ``public_path``; a site that does not
  leaves it out and keeps the ancestor-chain path the app derives;
- a synced row names its content source with the ``source`` foreign key, which
  is the ownership scope of :func:`delete_missing` and of the second lookup in
  :func:`_existing_page`. ``source_content_id`` holds the item's own
  ``content_id`` and nothing else, as ``content_sync/FORMAT.md`` section 3.4
  requires and as ``curriculum.importing`` already does. The two meanings once
  shared this one ``UUIDField``, so nothing raised; migration 0006 separated
  them. A parser that has no ``content_id`` to pass (a site shape that carries
  none) leaves it null, and the provenance constraint no longer counts it;
- ``status`` is the declared status of the item: a repository that declares
  ``status: draft`` gets a draft page (section 3.3, "a draft is imported and
  hidden"), and a parser that says nothing gets a published one;
- a page that vanishes from the repository is drafted, not deleted, the way
  curriculum drafts vanished courses.

Studio-authored pages carry no provenance and are never touched by sync.
"""

import hashlib

from django.db import transaction

from community_base.knowledge_base.models import (
    BODY_HTML_MARKDOWN,
    SECTION_CHOICES,
    SECTION_WIKI,
    STATUS_CHOICES,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    KnowledgeBasePage,
    Person,
)

ACTION_CREATED = "created"
ACTION_UPDATED = "updated"
ACTION_UNCHANGED = "unchanged"

SECTIONS = tuple(value for value, _label in SECTION_CHOICES)
STATUSES = tuple(value for value, _label in STATUS_CHOICES)


class KnowledgeBaseSyncError(Exception):
    """A sync item violates the contract (unknown parent, cycle, section, status)."""


def _stable_commit(source_path: str, checksum: str) -> str:
    """A 40-hex stand-in for checkouts that expose no real git commit."""

    return hashlib.sha256(f"{source_path}\0{checksum}".encode()).hexdigest()[:40]


def upsert_page(
    source,
    *,
    section: str,
    slug: str,
    title: str,
    body: str = "",
    summary: str = "",
    parent_slug: str | None = None,
    parent_path: str | None = None,
    nav_order: int = 0,
    public_path: str | None = None,
    body_html: str | None = None,
    record: dict | None = None,
    status: str = STATUS_PUBLISHED,
    content_id: str | None = None,
    commit_sha: str,
    source_path: str,
    checksum: str,
) -> tuple[KnowledgeBasePage, str]:
    """Create, update or leave unchanged one page; returns ``(page, action)``.

    The parent must already exist within the same section, so a parser
    discovers parents before children. Name it with ``parent_slug`` when the
    section's slugs are unique, or with ``parent_path`` (the slug chain from
    the section root, ``"activities/book-of-the-week"``) when leaf slugs
    repeat; passing both is an error. ``public_path`` is the site's own public
    URL for the page; left out, the page keeps the ancestor-chain path the app
    derives. ``body_html`` is the site's own rendering of the page, sanitized
    and stored as-is; left out, the app renders ``body`` as markdown.
    ``record`` is the row's own metadata, stored opaquely. ``status`` is the
    item's declared status, so a repository that declares ``status: draft``
    gets a draft page. ``content_id`` is the item's own identifier from the
    content format and is what ``source_content_id`` holds; a parser whose
    shape carries none leaves it out. An unchanged page (same checksum, commit
    and status) is left completely alone, so a page drafted because it had
    vanished is republished when it returns -- its return is itself a change.
    """

    if section not in SECTIONS:
        raise KnowledgeBaseSyncError(f"Unknown knowledge base section: {section!r}")
    if status not in STATUSES:
        raise KnowledgeBaseSyncError(f"Unknown knowledge base page status: {status!r}")
    if not slug:
        raise KnowledgeBaseSyncError("A knowledge base page requires a slug.")
    if not title:
        raise KnowledgeBaseSyncError(f"Knowledge base page {slug!r} requires a title.")
    if parent_slug and parent_path:
        raise KnowledgeBaseSyncError(
            f"Knowledge base page {slug!r} names its parent twice; "
            "pass parent_slug or parent_path, not both."
        )
    if section == SECTION_WIKI and (parent_slug or parent_path):
        raise KnowledgeBaseSyncError(
            f"Knowledge base page {slug!r} is a wiki page; wiki pages cannot have a parent."
        )
    commit_sha = commit_sha or _stable_commit(source_path, checksum)

    parent = _resolve_parent(section, slug, parent_slug, parent_path)

    with transaction.atomic():
        page = _existing_page(source, section, slug, parent, source_path)
        if page is None:
            page = KnowledgeBasePage(section=section, slug=slug)
            action = ACTION_CREATED
        elif (
            page.source_checksum == checksum
            and page.source_commit_sha == commit_sha
            and page.status == status
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
        if body_html is None:
            page.body_html_source = BODY_HTML_MARKDOWN
        else:
            page.set_site_rendered_html(body_html)
        page.parent = parent
        page.nav_order = nav_order
        page.public_path = public_path or None
        page.record = dict(record) if record else {}
        page.status = status
        page.source = source if getattr(source, "pk", None) else None
        page.source_content_id = content_id
        page.source_path = source_path
        page.source_commit_sha = commit_sha
        page.source_checksum = checksum
        page.full_clean()
        page.save()
    return page, action


def _resolve_parent(
    section: str, slug: str, parent_slug: str | None, parent_path: str | None
) -> KnowledgeBasePage | None:
    """The parent row a ``parent_slug`` or ``parent_path`` reference names."""

    if parent_path:
        parent = None
        for segment in [part for part in parent_path.split("/") if part]:
            candidates = KnowledgeBasePage.objects.filter(section=section, slug=segment)
            candidates = (
                candidates.filter(parent__isnull=True)
                if parent is None
                else candidates.filter(parent=parent)
            )
            parent = candidates.first()
            if parent is None:
                raise KnowledgeBaseSyncError(
                    f"Knowledge base page {slug!r} references parent path {parent_path!r} "
                    f"whose segment {segment!r} does not exist yet; "
                    "discover parents before children."
                )
        return parent
    if not parent_slug:
        return None
    matches = list(KnowledgeBasePage.objects.filter(section=section, slug=parent_slug)[:2])
    if not matches:
        raise KnowledgeBaseSyncError(
            f"Knowledge base page {slug!r} references parent {parent_slug!r} "
            "that does not exist yet; discover parents before children."
        )
    if len(matches) > 1:
        raise KnowledgeBaseSyncError(
            f"Knowledge base page {slug!r} references parent {parent_slug!r}, "
            "which names more than one page in this section; pass parent_path instead."
        )
    return matches[0]


def _existing_page(
    source, section: str, slug: str, parent: KnowledgeBasePage | None, source_path: str
) -> KnowledgeBasePage | None:
    """The row this item already owns, if any.

    The key is ``(section, parent, slug)``. A page whose parent changed is not
    found by that key, so the same source file under the same source is
    matched as a second step and updated in place instead of duplicated.
    """

    page = KnowledgeBasePage.objects.filter(section=section, slug=slug, parent=parent).first()
    if page is not None:
        return page
    if getattr(source, "pk", None) is None or not source_path:
        return None
    return KnowledgeBasePage.objects.filter(
        section=section,
        slug=slug,
        source_path=source_path,
        source=source,
    ).first()


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


def delete_missing(
    source,
    section: str,
    seen_slugs: set[str] | frozenset[str] | None = None,
    *,
    seen_source_paths: set[str] | frozenset[str] | None = None,
):
    """Draft this source's published pages of the section that the repository no
    longer lists. Rows synced by other sources, and Studio-authored rows, are
    never touched: the scope is the ``source`` foreign key, so a row with no
    source is out of scope and a caller with no source drafts nothing.

    Name what the repository still lists by slug, or -- for a section whose
    leaf slugs repeat under different parents, where a slug identifies no
    single page -- by ``seen_source_paths``. Exactly one of the two.
    """

    if (seen_slugs is None) == (seen_source_paths is None):
        raise KnowledgeBaseSyncError(
            "delete_missing needs exactly one of seen_slugs or seen_source_paths."
        )
    if getattr(source, "pk", None) is None:
        return []
    missing = KnowledgeBasePage.objects.filter(
        section=section,
        status=STATUS_PUBLISHED,
        source=source,
    )
    if seen_slugs is not None:
        missing = missing.exclude(slug__in=set(seen_slugs))
    else:
        missing = missing.exclude(source_path__in=set(seen_source_paths))
    missing = missing.order_by("slug")
    drafted: list[KnowledgeBasePage] = []
    for page in missing:
        page.status = STATUS_DRAFT
        page.save(update_fields=["status", "updated_at"])
        drafted.append(page)
    return drafted


def upsert_person(
    source,
    *,
    slug: str,
    title: str,
    body: str = "",
    summary: str = "",
    image: str = "",
    links: list | None = None,
    record: dict | None = None,
    status: str = STATUS_PUBLISHED,
    content_id: str | None = None,
    body_html: str | None = None,
    commit_sha: str,
    source_path: str,
    checksum: str,
) -> tuple[Person, str]:
    """Create, update or leave unchanged one person; returns ``(person, action)``.

    The same contract as :func:`upsert_page`, for the record the ``person``
    kind fills: ``title`` is the display name, ``summary`` the short bio,
    ``image`` the picture and the body the long bio, and ``links`` is a list
    of ``{label, url}``. The row is keyed by its slug, which is what a
    ``person:`` reference names.
    """

    if status not in STATUSES:
        raise KnowledgeBaseSyncError(f"Unknown person status: {status!r}")
    if not slug:
        raise KnowledgeBaseSyncError("A person requires a slug.")
    if not title:
        raise KnowledgeBaseSyncError(f"Person {slug!r} requires a title (the display name).")
    commit_sha = commit_sha or _stable_commit(source_path, checksum)

    with transaction.atomic():
        person = Person.objects.filter(slug=slug).first()
        if person is None:
            person = Person(slug=slug)
            action = ACTION_CREATED
        elif (
            person.source_checksum == checksum
            and person.source_commit_sha == commit_sha
            and person.status == status
        ):
            return person, ACTION_UNCHANGED
        else:
            action = ACTION_UPDATED

        person.title = title
        person.summary = summary
        person.body = body
        if body_html is None:
            person.body_html_source = BODY_HTML_MARKDOWN
        else:
            person.set_site_rendered_html(body_html)
        person.image = image or ""
        person.links = list(links) if links else []
        person.record = dict(record) if record else {}
        person.status = status
        person.source = source if getattr(source, "pk", None) else None
        person.source_content_id = content_id
        person.source_path = source_path
        person.source_commit_sha = commit_sha
        person.source_checksum = checksum
        person.full_clean()
        person.save()
    return person, action


def delete_missing_people(source, seen_source_paths: set[str] | frozenset[str]):
    """Draft this source's published people that the repository no longer lists.

    The same ownership scope as :func:`delete_missing`: the ``source`` foreign
    key, so people from another source and Studio-authored people are never
    touched.
    """

    if getattr(source, "pk", None) is None:
        return []
    missing = (
        Person.objects.filter(status=STATUS_PUBLISHED, source=source)
        .exclude(source_path__in=set(seen_source_paths))
        .order_by("slug")
    )
    drafted: list[Person] = []
    for person in missing:
        person.status = STATUS_DRAFT
        person.save(update_fields=["status", "updated_at"])
        drafted.append(person)
    return drafted
