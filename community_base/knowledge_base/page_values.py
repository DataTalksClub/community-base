"""Default storage values for package-owned wiki and docs pages."""

import hashlib
import json

from community_base.content_sync.resolution import ResolvedDocument
from community_base.knowledge_base.models import STATUS_PUBLISHED
from community_base.knowledge_base.page_adaptation import PageWrite
from community_base.knowledge_base.routes import default_public_path

RECORD_KEYS = ("values", "headings", "references", "assets")


def page_write(document: ResolvedDocument, section: str, commit_sha: str) -> PageWrite:
    values = document.values
    return PageWrite(
        section=section,
        page_path=document.path,
        slug=document.document.slug,
        title=str(values.get("title") or ""),
        summary=str(values.get("summary") or ""),
        body=document.document.body,
        body_html=document.html,
        parent_slug=None,
        parent_path=_parent_path(document, section),
        nav_order=document.document.sort_order,
        public_path=default_public_path(document.kind, document.path),
        record=record_of(document),
        status=str(values.get("status") or STATUS_PUBLISHED),
        content_id=document.document.content_id,
        commit_sha=commit_sha,
        source_path=document.source_path,
        checksum=checksum_of(document),
    )


def _parent_path(document: ResolvedDocument, section: str) -> str | None:
    if section != "docs":
        return None
    parts = []
    for part in document.path.split("/"):
        if part:
            parts.append(part)
    parent = "/".join(parts[:-1])
    if not parent:
        return None
    return parent


def record_of(document: ResolvedDocument) -> dict:
    headings = []
    for heading in document.headings:
        headings.append(dict(heading))
    assets = []
    for asset in document.assets:
        assets.append(asset.path)
    return {
        "values": json.loads(json.dumps(document.values, default=str)),
        "headings": headings,
        "references": document.reference_records(),
        "assets": assets,
    }


def checksum_of(document: ResolvedDocument) -> str:
    payload = {
        "document": document.document.checksum,
        "html": document.html,
        "record": record_of(document),
        "path": document.path,
    }
    rendered = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def page_fields(document: ResolvedDocument, commit_sha: str) -> dict:
    """Compatibility import for callers of the former mapping helper."""

    write = page_write(document, document.kind, commit_sha)
    fields = write.storage_fields()
    fields.pop("section")
    fields.pop("parent_slug")
    fields.pop("parent_path")
    return fields


def page_identity(write: PageWrite) -> tuple:
    """The immutable document and provenance identity of a projected page."""

    return write.identity
