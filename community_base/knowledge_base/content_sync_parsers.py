"""Package parsers for the `wiki`, `docs` and `person` kinds (D24).

The document toolkit remains the only reader, resolver and renderer. Page
imports live in :mod:`page_import`; this module keeps the person mapping and
the public imports used by existing sites.
"""

from pathlib import PurePosixPath

from community_base.content_sync.parsers import SourceItem
from community_base.knowledge_base import sync
from community_base.knowledge_base.models import STATUS_PUBLISHED
from community_base.knowledge_base.page_import import (
    DocsParser,
    KnowledgeBaseParseError,
    WikiParser,
)
from community_base.knowledge_base.page_repository import RepositoryView, repository_view
from community_base.knowledge_base.page_values import (
    RECORD_KEYS,
    checksum_of,
    page_fields,
    record_of,
)
from community_base.knowledge_base.routes import PERSON_KIND


class PersonParser:
    """Map the package-owned `person` kind onto the shared person model."""

    kind = PERSON_KIND

    def __init__(self) -> None:
        self._view: RepositoryView | None = None
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
        items = []
        for document in self._view.read.by_kind(self.kind):
            items.append(SourceItem(document.source_path, PurePosixPath(document.source_path), {}))
        return tuple(items)

    def upsert(self, item, source, media):
        from community_base.content_sync.orchestration import UpsertResult

        view = self._require_view()
        resolved = view.resolve(media)
        if not resolved.ok:
            messages = []
            for diagnostic in resolved.errors[:5]:
                messages.append(diagnostic.render())
            raise KnowledgeBaseParseError(
                "person collection has unresolved references or assets: " + "; ".join(messages)
            )
        document = view.document(media, item.key)
        obj, action = sync.upsert_person(source, **_person_fields(document, view.commit_sha))
        return UpsertResult(obj, action)

    def soft_delete_missing(self, seen_keys: set, source):
        if not self._mine:
            return ()
        return sync.delete_missing_people(source, set(seen_keys))

    def _require_view(self) -> RepositoryView:
        if self._view is None:
            raise RuntimeError("discover() must run before person import")
        return self._view


def _person_fields(document, commit_sha: str) -> dict:
    values = document.values
    return {
        "slug": document.document.slug,
        "title": str(values.get("title") or ""),
        "summary": str(values.get("summary") or ""),
        "body": document.document.body,
        "body_html": document.html,
        "image": str(values.get("image") or ""),
        "links": list(values.get("links") or []),
        "record": record_of(document),
        "status": str(values.get("status") or STATUS_PUBLISHED),
        "content_id": document.document.content_id,
        "commit_sha": commit_sha,
        "source_path": document.source_path,
        "checksum": checksum_of(document),
    }


def register_parsers() -> None:
    """Register package parsers in reference dependency order."""

    from community_base.content_sync.parsers import register_parser

    register_parser("knowledge_base_person", PersonParser())
    register_parser("knowledge_base_docs", DocsParser())
    register_parser("knowledge_base_wiki", WikiParser())


__all__ = [
    "RECORD_KEYS",
    "DocsParser",
    "KnowledgeBaseParseError",
    "PersonParser",
    "WikiParser",
    "page_fields",
    "register_parsers",
    "repository_view",
]
