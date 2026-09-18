"""The package parsers for the `wiki`, `docs` and `person` kinds (D24).

These three kinds are parsed by the package because the package owns their
storage; the article parser stays per site because article storage is
site-owned (D21). A parser here is thin on purpose. It walks no files, parses
no YAML and validates no key: :func:`~.documents.read_repository` is the one
reader, :func:`~.resolution.resolve_repository` the one resolver, and
`rendering.py` the one renderer and sanitizer. What is left is the mapping onto
the models, which is what this module is.

One repository, one read. The three parsers are registered separately, and the
sync orchestration calls each in turn over the same checkout, so the read and
the resolution are memoised per checkout: resolving twice would render every
document twice and upload every asset twice for one repository.

A repository that declares none of these kinds is not this parser's, and a
repository the toolkit cannot read at all (no `content.yaml`, the shape every
site repository still has before its conversion) declares nothing. Both cases
yield no items, and -- this is the part that matters -- no soft deletion
either: an empty item list from a repository that was never ours must not draft
the pages another source owns.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath

from community_base.content_sync.documents import ReadResult, read_repository
from community_base.content_sync.parsers import SourceItem
from community_base.content_sync.resolution import (
    ResolutionResult,
    ResolvedDocument,
    hosting_url_for,
    resolve_repository,
)
from community_base.knowledge_base import sync
from community_base.knowledge_base.models import SECTION_DOCS, SECTION_WIKI, STATUS_PUBLISHED
from community_base.knowledge_base.routes import (
    PERSON_KIND,
    default_public_path,
    route_resolver,
)

#: What the parsers write into ``record``: the format's own derived metadata.
RECORD_KEYS = ("values", "headings", "references", "assets")


class KnowledgeBaseParseError(Exception):
    """The repository declares one of these kinds and does not satisfy it."""


class _RepositoryView:
    """One checkout, read once and resolved once, for all three parsers.

    ``read`` is the reading half and needs nothing but the checkout, so
    ``discover`` can have it. ``resolved`` is the resolving half and needs the
    media store, which the orchestration only hands over at ``upsert``; it is
    produced on first use and reused after that.
    """

    def __init__(self, checkout, source) -> None:
        self.checkout = checkout
        self.commit_sha = str(getattr(checkout, "commit_sha", "") or "")
        self.source = source
        self.read: ReadResult = read_repository(checkout)
        self.declared = frozenset(
            collection.kind.name for collection in self.read.manifest.collections
        )
        self._resolved: ResolutionResult | None = None
        self._by_path: dict[str, ResolvedDocument] = {}

    def resolve(self, media) -> ResolutionResult:
        if self._resolved is None:
            self._resolved = resolve_repository(
                self.read,
                media=media,
                source=self.source,
                routes=route_resolver(self.declared),
                hosting_url=hosting_url_for(self.source, self.commit_sha),
            )
            self._by_path = self._resolved.by_path()
        return self._resolved

    def document(self, media, source_path: str) -> ResolvedDocument:
        self.resolve(media)
        return self._by_path[source_path]

    def read_errors(self) -> tuple[str, ...]:
        """The reading errors of this repository, rendered.

        Resolution errors are not included: they are found on first upsert,
        when the media store exists, and are raised there.
        """

        return tuple(item.render() for item in self.read.errors)


_last_view: tuple[tuple[str, str, str], _RepositoryView] | None = None


def repository_view(checkout, source) -> _RepositoryView:
    """The view of this checkout, read once for every parser that asks.

    Keyed by the checkout (a fresh directory per sync), its commit and the
    source, and only the last one is kept: the cache exists so that the three
    parsers of one sync share one read, not to survive between syncs.
    """

    global _last_view
    key = (
        str(getattr(checkout, "root", "")),
        str(getattr(checkout, "commit_sha", "")),
        str(source),
    )
    if _last_view is not None and _last_view[0] == key:
        return _last_view[1]
    view = _RepositoryView(checkout, source)
    _last_view = (key, view)
    return view


class _KnowledgeBaseParser:
    """What the three parsers share: one read, one resolution, one guard."""

    kind = ""

    def __init__(self) -> None:
        self._view: _RepositoryView | None = None
        self._mine = False

    def discover(self, checkout, source):
        self._view = repository_view(checkout, source)
        self._mine = self.kind in self._view.declared
        if not self._mine:
            return ()
        errors = self._view.read_errors()
        if errors:
            raise KnowledgeBaseParseError(
                f"{self.kind} collection cannot be read: " + "; ".join(errors[:5])
            )
        return tuple(
            SourceItem(
                key=document.source_path,
                path=PurePosixPath(document.source_path),
                data={},
            )
            for document in self._view.read.by_kind(self.kind)
        )

    def upsert(self, item, source, media):
        from community_base.content_sync.orchestration import UpsertResult

        view = self._view
        resolved = view.resolve(media)
        if not resolved.ok:
            raise KnowledgeBaseParseError(
                f"{self.kind} collection has unresolved references or assets: "
                + "; ".join(diagnostic.render() for diagnostic in resolved.errors[:5])
            )
        obj, action = self.apply(view.document(media, item.key), source, view.commit_sha)
        return UpsertResult(obj, action)

    def soft_delete_missing(self, seen_keys: set, source):
        if not self._mine:
            return ()
        return self.delete_missing(set(seen_keys), source)

    def apply(self, document: ResolvedDocument, source, commit_sha: str):
        raise NotImplementedError

    def delete_missing(self, seen_source_paths: set, source):
        raise NotImplementedError


class WikiParser(_KnowledgeBaseParser):
    """The `wiki` kind: a flat set of pages in the `wiki` section."""

    kind = SECTION_WIKI

    def apply(self, document: ResolvedDocument, source, commit_sha: str):
        return sync.upsert_page(source, section=SECTION_WIKI, **page_fields(document, commit_sha))

    def delete_missing(self, seen_source_paths: set, source):
        return sync.delete_missing(source, SECTION_WIKI, seen_source_paths=seen_source_paths)


class DocsParser(_KnowledgeBaseParser):
    """The `docs` kind: the directory tree, in the `docs` section.

    The page key is the leaf slug inside its parent, so the same leaf slug
    under different parents is two pages, and the chain is carried by
    ``parent_path``. The chain comes from the item's derived path, not from the
    file's directory: the collection root's `index.md` contributes no slug, so
    a top-level section is a root page and the root document is a root page
    beside it.
    """

    kind = SECTION_DOCS

    def apply(self, document: ResolvedDocument, source, commit_sha: str):
        chain = [part for part in document.path.split("/") if part][:-1]
        return sync.upsert_page(
            source,
            section=SECTION_DOCS,
            parent_path="/".join(chain) or None,
            **page_fields(document, commit_sha),
        )

    def delete_missing(self, seen_source_paths: set, source):
        return sync.delete_missing(source, SECTION_DOCS, seen_source_paths=seen_source_paths)


class PersonParser(_KnowledgeBaseParser):
    """The `person` kind: the record `authors`, `instructors` and `guests` name."""

    kind = PERSON_KIND

    def apply(self, document: ResolvedDocument, source, commit_sha: str):
        values = document.values
        return sync.upsert_person(
            source,
            slug=document.document.slug,
            title=str(values.get("title") or ""),
            summary=str(values.get("summary") or ""),
            body=document.document.body,
            body_html=document.html,
            image=str(values.get("image") or ""),
            links=list(values.get("links") or []),
            record=record_of(document),
            status=str(values.get("status") or STATUS_PUBLISHED),
            content_id=document.document.content_id,
            commit_sha=commit_sha,
            source_path=document.source_path,
            checksum=checksum_of(document),
        )

    def delete_missing(self, seen_source_paths: set, source):
        return sync.delete_missing_people(source, seen_source_paths)


def page_fields(document: ResolvedDocument, commit_sha: str) -> dict:
    """The upsert keywords a `wiki` or `docs` item maps onto, minus the parent.

    The rendered HTML, the heading list and the resolved reference list are the
    three things the issue asks a page to store; the first is the body, the
    other two ride in the record with the item's resolved values.
    """

    values = document.values
    return {
        "slug": document.document.slug,
        "title": str(values.get("title") or ""),
        "summary": str(values.get("summary") or ""),
        "body": document.document.body,
        "body_html": document.html,
        "nav_order": document.document.sort_order,
        "public_path": default_public_path(document.kind, document.path),
        "record": record_of(document),
        "status": str(values.get("status") or STATUS_PUBLISHED),
        "content_id": document.document.content_id,
        "commit_sha": commit_sha,
        "source_path": document.source_path,
        "checksum": checksum_of(document),
    }


def record_of(document: ResolvedDocument) -> dict:
    """Everything the format derived that the model has no column for.

    One rule rather than a list of favourites: the item's values as the
    resolution left them (assets rewritten to their stored URLs), the heading
    list and the resolved references. A site adds its own keys to what is
    already here.
    """

    return {
        "values": json.loads(json.dumps(document.values, default=str)),
        "headings": [dict(heading) for heading in document.headings],
        "references": document.reference_records(),
        "assets": [asset.path for asset in document.assets],
    }


def checksum_of(document: ResolvedDocument) -> str:
    """The change signal: everything the stored row derives from.

    The toolkit's own checksum covers the derived record -- the file, its
    place and its values. A stored row also derives from what resolution
    produced, so a rewritten asset URL or a reference whose target moved is a
    change even when the file did not move and its bytes did not change.
    """

    payload = json.dumps(
        {
            "document": document.document.checksum,
            "html": document.html,
            "record": record_of(document),
            "path": document.path,
        },
        sort_keys=True,
        default=str,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def register_parsers() -> None:
    """Register the three package parsers; called from ``AppConfig.ready``."""

    from community_base.content_sync.parsers import register_parser

    # Registered in dependency order (`kind_order`): a `person:` reference in
    # a wiki body resolves against rows already written when it can.
    register_parser("knowledge_base_person", PersonParser())
    register_parser("knowledge_base_docs", DocsParser())
    register_parser("knowledge_base_wiki", WikiParser())


__all__ = [
    "RECORD_KEYS",
    "DocsParser",
    "KnowledgeBaseParseError",
    "PersonParser",
    "WikiParser",
    "register_parsers",
    "repository_view",
]
