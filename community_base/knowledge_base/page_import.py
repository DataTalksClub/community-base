"""Package-owned wiki/docs import lifecycle with bounded site projection."""

from __future__ import annotations

import sys
from pathlib import PurePosixPath

from community_base.content_sync.checkout import CheckoutError
from community_base.content_sync.documents import MANIFEST_NAME, Diagnostic
from community_base.content_sync.parsers import SourceItem
from community_base.knowledge_base import sync
from community_base.knowledge_base.models import SECTION_DOCS, SECTION_WIKI
from community_base.knowledge_base.page_adaptation import (
    PageBoundaryFailure,
    PageCounts,
    PageDetail,
    PageError,
    PageImportContext,
    PageImportReport,
    registered_page_site_adapter,
    validate_described_error,
    validate_projection,
)
from community_base.knowledge_base.page_diagnostics import (
    diagnostic_error,
    family_diagnostics,
    is_missing_image,
    redact_page_error,
)
from community_base.knowledge_base.page_repository import RepositoryView, repository_view
from community_base.knowledge_base.page_values import page_write

ACTIONS = ("created", "updated", "unchanged", "deleted")


class KnowledgeBaseParseError(Exception):
    """A declared package knowledge-base collection does not satisfy its contract."""


class PageParser:
    """Package-owned per-item continuation, cleanup and final reporting."""

    kind = ""
    content_type = ""

    def __init__(self) -> None:
        self._view: RepositoryView | None = None
        self._mine = False
        self._adapter = None
        self._context: PageImportContext | None = None
        self._reset_state()

    def discover(self, checkout, source):
        self._reset_state()
        self._view = repository_view(checkout, source)
        self._mine = self.kind in self._view.declared
        self._adapter = registered_page_site_adapter()
        self._context = self._make_context(checkout, source)
        if not self._mine:
            return ()
        if self._adapter is None:
            self._refuse_default_read_errors()
        else:
            self._record_read_diagnostics()
        items = []
        for document in self._view.read.by_kind(self.kind):
            items.append(SourceItem(document.source_path, PurePosixPath(document.source_path), {}))
        return tuple(items)

    def upsert(self, item, source, media):
        if self._adapter is None:
            return self._default_upsert(item, source, media)
        try:
            return self._adapted_upsert(item, source, media)
        except PageBoundaryFailure as failure:
            self._fail_boundary(self._safe_error(failure.error), failure)
        except CheckoutError as error:
            described = self._describe_error(item.key, error, sys.exc_info()[2])
            self._fail_boundary(described, error)
        except Exception as error:
            self._failed_paths.add(item.key)
            described = self._describe_error(item.key, error, sys.exc_info()[2])
            if described.filesystem_boundary:
                self._fail_boundary(described, error)
            self._errors.append(described)
            return self._outcome(None, "unchanged")

    def soft_delete_missing(self, seen_keys: set, source):
        if not self._mine:
            return ()
        if self._adapter is None:
            return self.delete_missing(set(seen_keys), source)
        retained = set(seen_keys)
        retained.update(self._failed_paths)
        retained.update(self._rejected_paths)
        drafted = []
        if not self._suppress_cleanup:
            try:
                drafted = list(self.delete_missing(retained, source))
                self._record_deleted(drafted)
            except Exception as error:
                self._fail_cleanup(error, sys.exc_info()[2])
        self._finish(completed=True)
        if self._errors:
            raise KnowledgeBaseParseError(
                f"{self.kind} collection finished with {len(self._errors)} error(s)"
            )
        return drafted

    def apply(self, document, source, commit_sha: str):
        write = page_write(document, self.kind, commit_sha)
        return sync.upsert_page(source, **write.storage_fields())

    def delete_missing(self, seen_source_paths: set, source):
        return sync.delete_missing(source, self.kind, seen_source_paths=seen_source_paths)

    def _default_upsert(self, item, source, media):
        view = self._require_view()
        resolved = view.resolve(media)
        if not resolved.ok:
            rendered = []
            for diagnostic in resolved.errors[:5]:
                rendered.append(diagnostic.render())
            raise KnowledgeBaseParseError(
                f"{self.kind} collection has unresolved references or assets: "
                + "; ".join(rendered)
            )
        obj, action = self.apply(view.document(media, item.key), source, view.commit_sha)
        return self._outcome(obj, action)

    def _adapted_upsert(self, item, source, media):
        self._prepare_resolution(media)
        if item.key in self._rejected_paths:
            return self._outcome(None, "unchanged")
        view = self._require_view()
        document = view.document(media, item.key)
        context = self._item_context(item.key)
        default = page_write(document, self.kind, view.commit_sha)
        projection = self._adapter.project(context, document, default)
        validate_projection(projection, default, context)
        obj, action = sync.upsert_page(source, **projection.write.storage_fields())
        self._record_action(item.key, action)
        for error in projection.errors:
            self._errors.append(self._safe_error(error))
        return self._outcome(obj, action)

    def _prepare_resolution(self, media) -> None:
        if self._resolution_ready:
            return
        view = self._require_view()
        resolved = view.resolve(media)
        diagnostics = family_diagnostics(view, self.kind, resolved.errors)
        source_paths = set()
        for document in view.read.by_kind(self.kind):
            source_paths.add(document.source_path)
        for diagnostic in diagnostics:
            if is_missing_image(diagnostic, source_paths):
                self._missing_assets.setdefault(diagnostic.path, []).append(diagnostic)
            else:
                self._record_diagnostic(diagnostic)
        self._resolution_ready = True

    def _record_read_diagnostics(self) -> None:
        view = self._require_view()
        diagnostics = family_diagnostics(view, self.kind, view.read.errors)
        for diagnostic in diagnostics:
            self._record_diagnostic(diagnostic)

    def _record_diagnostic(self, diagnostic: Diagnostic) -> None:
        self._errors.append(self._safe_error(diagnostic_error(diagnostic)))
        self._suppress_cleanup = True
        if diagnostic.path != MANIFEST_NAME:
            self._rejected_paths.add(diagnostic.path)

    def _describe_error(self, source_path, error, traceback) -> PageError:
        context = self._require_context()
        described = self._adapter.describe_error(context, source_path, error, traceback)
        if not isinstance(described, PageError):
            raise TypeError("Page site adapter describe_error() must return PageError")
        validate_described_error(described, source_path)
        return self._safe_error(described)

    def _safe_error(self, error: PageError) -> PageError:
        context = self._require_context()
        return redact_page_error(error, context.source)

    def _fail_boundary(self, error: PageError, cause: Exception) -> None:
        if not error.filesystem_boundary:
            raise ValueError("A fatal page boundary requires a typed boundary error")
        self._errors.append(error)
        self._suppress_cleanup = True
        self._finish(completed=False)
        raise PageBoundaryFailure(error) from cause

    def _fail_cleanup(self, error: Exception, traceback) -> None:
        self._suppress_cleanup = True
        self._errors.append(self._describe_error("<cleanup>", error, traceback))
        self._finish(completed=False)
        raise KnowledgeBaseParseError(f"{self.kind} collection cleanup failed") from error

    def _finish(self, *, completed: bool) -> None:
        if self._finished:
            return
        self._finished = True
        report = PageImportReport(
            section=self.kind,
            content_type=self.content_type,
            counts=PageCounts(**self._counts),
            details=tuple(self._details),
            errors=tuple(self._errors),
            cleanup_suppressed=self._suppress_cleanup,
            completed=completed,
        )
        self._adapter.finished(self._require_context(), report)

    def _record_action(self, source_path: str, action: str) -> None:
        self._counts[action] += 1
        if action != "unchanged":
            self._details.append(PageDetail(source_path, source_path, action, self.content_type))

    def _record_deleted(self, pages) -> None:
        for page in pages:
            self._counts["deleted"] += 1
            path = str(page.source_path or page.slug)
            self._details.append(PageDetail(path, path, "deleted", self.content_type))

    def _refuse_default_read_errors(self) -> None:
        errors = self._require_view().read_errors()
        if errors:
            raise KnowledgeBaseParseError(
                f"{self.kind} collection cannot be read: " + "; ".join(errors[:5])
            )

    def _make_context(self, checkout, source) -> PageImportContext:
        view = self._require_view()
        return PageImportContext(self.kind, self.content_type, checkout, source, view.commit_sha)

    def _item_context(self, source_path: str) -> PageImportContext:
        context = self._require_context()
        missing = tuple(self._missing_assets.get(source_path, ()))
        return PageImportContext(
            context.section,
            context.content_type,
            context.checkout,
            context.source,
            context.commit_sha,
            missing,
        )

    def _reset_state(self) -> None:
        self._errors: list[PageError] = []
        self._details: list[PageDetail] = []
        self._counts = {action: 0 for action in ACTIONS}
        self._failed_paths: set[str] = set()
        self._rejected_paths: set[str] = set()
        self._missing_assets: dict[str, list[Diagnostic]] = {}
        self._suppress_cleanup = False
        self._resolution_ready = False
        self._finished = False

    def _require_view(self) -> RepositoryView:
        if self._view is None:
            raise RuntimeError("discover() must run before page import")
        return self._view

    def _require_context(self) -> PageImportContext:
        if self._context is None:
            raise RuntimeError("discover() must run before page import")
        return self._context

    @staticmethod
    def _outcome(obj, action):
        from community_base.content_sync.orchestration import UpsertResult

        return UpsertResult(obj, action)


class WikiParser(PageParser):
    kind = SECTION_WIKI
    content_type = "knowledge_base_wiki"


class DocsParser(PageParser):
    kind = SECTION_DOCS
    content_type = "knowledge_base_docs"


__all__ = ["DocsParser", "KnowledgeBaseParseError", "PageParser", "WikiParser"]
