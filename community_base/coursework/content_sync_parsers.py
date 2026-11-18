"""``content_sync`` parser for standalone ``review_criteria`` YAML sets."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import PurePosixPath

from django.db import transaction

from community_base.content_sync.documents import MANIFEST_NAME, read_repository
from community_base.content_sync.kinds.review_criteria import (
    SPEC as REVIEW_CRITERIA_SPEC,
)
from community_base.content_sync.kinds.review_criteria import (
    review_criteria_diagnostics,
)
from community_base.content_sync.parsers import SourceItem
from community_base.coursework.models import ReviewCriteriaSet
from community_base.coursework.project_criteria import CriteriaError, parse_criteria_set

CONTENT_TYPE = "coursework_review_criteria"


class ReviewCriteriaParseError(ValueError):
    """Raised when authored review criteria YAML fails validation."""


def _document_checksum(document) -> str:
    payload = json.dumps(
        {
            "slug": document.slug,
            "content_id": document.content_id,
            "values": document.values,
        },
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ReviewCriteriaParser:
    """Sync standalone ``review_criteria`` YAML files into :class:`ReviewCriteriaSet`."""

    kind = REVIEW_CRITERIA_SPEC.name

    def __init__(self) -> None:
        self._checkout = None
        self._result = None
        self._mine = False
        self._documents: dict[str, tuple[object, dict]] = {}

    def discover(self, checkout, source):
        self._checkout = checkout
        self._result = None
        self._mine = False
        self._documents = {}

        if not any(path.as_posix() == MANIFEST_NAME for path in checkout.files()):
            return ()

        result = read_repository(checkout)
        self._result = result
        collections = [c for c in result.collections if c.kind.name == self.kind]
        if not collections:
            return ()

        self._mine = True
        diagnostics = [
            d
            for d in result.diagnostics
            if any(
                d.path == c.path or d.path.startswith(f"{c.path}/") or c.path == "."
                for c in collections
            )
        ]
        diagnostics.extend(review_criteria_diagnostics(result))
        errors = [d.render() for d in diagnostics if d.severity == "error"]
        if errors:
            raise ReviewCriteriaParseError(
                f"{self.kind} collection cannot be read: " + "; ".join(errors[:5])
            )

        items = []
        for document in result.by_kind(self.kind):
            raw = {
                **document.values,
                "slug": document.slug,
                "content_id": document.content_id,
            }
            try:
                parsed = parse_criteria_set(raw, document.source_path, default_slug=document.slug)
            except CriteriaError as error:
                raise ReviewCriteriaParseError(str(error)) from error
            self._documents[document.source_path] = (document, parsed)
            items.append(SourceItem(document.source_path, PurePosixPath(document.source_path), {}))
        return tuple(items)

    def upsert(self, item, source, media):
        from community_base.content_sync.orchestration import UpsertResult

        if self._checkout is None or item.key not in self._documents:
            raise RuntimeError("discover() must run before review_criteria upsert")

        document, parsed = self._documents[item.key]
        checksum = _document_checksum(document)
        commit_sha = getattr(self._checkout, "commit_sha", "") or ""
        status = str(document.values.get("status") or ReviewCriteriaSet.STATUS_PUBLISHED)
        defaults = {
            "source_id": source.pk,
            "source_content_id": uuid.UUID(str(document.content_id)),
            "source_path": document.source_path,
            "source_commit_sha": commit_sha,
            "source_checksum": checksum,
            "slug": parsed["slug"],
            "title": parsed["title"],
            "description": parsed["description"],
            "criteria": parsed["criteria"],
            "status": status,
        }

        with transaction.atomic():
            existing = ReviewCriteriaSet.objects.filter(
                source_content_id=document.content_id
            ).first()
            if existing is None:
                existing = ReviewCriteriaSet.objects.filter(slug=parsed["slug"]).first()
            if existing is None:
                obj = ReviewCriteriaSet(**defaults)
                obj.full_clean()
                obj.save()
                return UpsertResult(obj, "created")

            changed = any(getattr(existing, field) != value for field, value in defaults.items())
            if not changed:
                return UpsertResult(existing, "unchanged")

            for field, value in defaults.items():
                setattr(existing, field, value)
            existing.full_clean()
            existing.save()
            return UpsertResult(existing, "updated")

    def soft_delete_missing(self, seen_keys: set, source):
        if not self._mine:
            return 0
        missing = ReviewCriteriaSet.objects.filter(source_id=source.pk).exclude(
            source_path__in=set(seen_keys)
        )
        affected = 0
        for criteria_set in missing:
            if criteria_set.project_assignments.exists():
                if criteria_set.status != ReviewCriteriaSet.STATUS_DRAFT:
                    criteria_set.status = ReviewCriteriaSet.STATUS_DRAFT
                    criteria_set.save(update_fields=["status", "updated_at"])
                    affected += 1
            else:
                criteria_set.delete()
                affected += 1
        return affected
