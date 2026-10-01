"""Bounded site projection and reporting values for package-owned pages."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Protocol

from community_base.content_sync.documents import Diagnostic
from community_base.content_sync.resolution import ResolvedDocument


@dataclass(frozen=True, slots=True)
class PageImportContext:
    """The immutable package context for one page projection or final report."""

    section: str
    content_type: str
    checkout: object
    source: object
    commit_sha: str
    missing_assets: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class PageWrite:
    """Every existing public storage input for one package-owned page."""

    section: str
    page_path: str
    slug: str
    title: str
    body: str
    summary: str
    parent_slug: str | None
    parent_path: str | None
    nav_order: int
    public_path: str | None
    body_html: str | None
    record: Mapping[str, Any]
    status: str
    content_id: str | None
    commit_sha: str
    source_path: str
    checksum: str

    @property
    def identity(self) -> tuple[str, str, str | None, str, str, str]:
        return (
            self.section,
            self.page_path,
            self.content_id,
            self.slug,
            self.commit_sha,
            self.source_path,
        )

    def storage_fields(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "slug": self.slug,
            "title": self.title,
            "body": self.body,
            "summary": self.summary,
            "parent_slug": self.parent_slug,
            "parent_path": self.parent_path,
            "nav_order": self.nav_order,
            "public_path": self.public_path,
            "body_html": self.body_html,
            "record": dict(self.record),
            "status": self.status,
            "content_id": self.content_id,
            "commit_sha": self.commit_sha,
            "source_path": self.source_path,
            "checksum": self.checksum,
        }


@dataclass(frozen=True, slots=True)
class PageError:
    """The only structured error value accepted into a page report."""

    file: str
    error: str
    step: str
    kind: str
    filesystem_boundary: bool = False
    retryable: bool = False

    def __post_init__(self) -> None:
        for name in ("file", "error", "step", "kind"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"Page error {name} must be a nonempty string")
        if type(self.filesystem_boundary) is not bool or type(self.retryable) is not bool:
            raise ValueError("Page error boundary and retryable flags must be true or false")
        if self.filesystem_boundary and self.step != "filesystem_boundary":
            raise ValueError("Filesystem boundary errors require step=filesystem_boundary")
        if not self.filesystem_boundary and self.step == "filesystem_boundary":
            raise ValueError("The filesystem boundary step requires a boundary error")
        if self.filesystem_boundary and self.retryable:
            raise ValueError("Filesystem boundary errors cannot be retryable")

    @property
    def source_path(self) -> str:
        return self.file

    @property
    def message(self) -> str:
        return self.error

    @property
    def record(self) -> dict[str, object]:
        return {
            "file": self.file,
            "error": self.error,
            "step": self.step,
            "kind": self.kind,
            "filesystem_boundary": self.filesystem_boundary,
            "retryable": self.retryable,
        }


@dataclass(frozen=True, slots=True)
class PageProjection:
    """A site's projected storage values and validated missing-image errors."""

    write: PageWrite
    errors: tuple[PageError, ...] = ()


@dataclass(frozen=True, slots=True)
class PageCounts:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0


@dataclass(frozen=True, slots=True)
class PageDetail:
    key: str
    path: str
    action: str
    content_type: str


@dataclass(frozen=True, slots=True)
class PageImportReport:
    section: str
    content_type: str
    counts: PageCounts
    details: tuple[PageDetail, ...]
    errors: tuple[PageError, ...]
    cleanup_suppressed: bool
    completed: bool


class PageBoundaryFailure(RuntimeError):
    """A typed fatal filesystem boundary already safe for operator reporting."""

    def __init__(self, error: PageError) -> None:
        if not isinstance(error, PageError) or not error.filesystem_boundary:
            raise TypeError("PageBoundaryFailure requires a typed filesystem boundary error")
        super().__init__(error.message)
        self.error = error


class PageSiteAdapter(Protocol):
    """The three bounded operations a site may add to package page imports."""

    def project(
        self,
        context: PageImportContext,
        document: ResolvedDocument,
        default: PageWrite,
    ) -> PageProjection: ...

    def describe_error(
        self,
        context: PageImportContext,
        source_path: str,
        error: Exception,
        traceback: TracebackType | None,
    ) -> PageError: ...

    def finished(self, context: PageImportContext, report: PageImportReport) -> None: ...


_adapter: PageSiteAdapter | None = None


def register_page_site_adapter(adapter: PageSiteAdapter) -> PageSiteAdapter:
    """Register the one page compatibility adapter for this process."""

    global _adapter
    if _adapter is not None:
        raise ValueError("A knowledge base page site adapter is already registered")
    _validate_adapter(adapter)
    _adapter = adapter
    return adapter


def registered_page_site_adapter() -> PageSiteAdapter | None:
    """Return the adapter resolved when a page parser starts discovery."""

    return _adapter


@contextmanager
def page_site_adapter(adapter: PageSiteAdapter):
    """Install an adapter for one bounded operation or isolated test."""

    registered = register_page_site_adapter(adapter)
    try:
        yield registered
    finally:
        global _adapter
        if _adapter is registered:
            _adapter = None


def _validate_adapter(adapter: PageSiteAdapter) -> None:
    for method in ("project", "describe_error", "finished"):
        if not callable(getattr(adapter, method, None)):
            raise TypeError(f"Page site adapter must implement {method}()")


def validate_projection(
    projection: PageProjection, default: PageWrite, context: PageImportContext
) -> None:
    """Validate the only site-controlled values before a page write."""

    if not isinstance(projection, PageProjection):
        raise TypeError("Page site adapter project() must return PageProjection")
    if projection.write.identity != default.identity:
        raise ValueError("Page site adapter cannot change page identity or provenance")
    if len(projection.errors) != len(context.missing_assets):
        raise ValueError("Page projection must report every cleanup-safe missing image")
    for error in projection.errors:
        _validate_missing_image_error(error, default.source_path)


def validate_described_error(error: PageError, source_path: str) -> None:
    """Bind an adapter-described error to its active item or cleanup phase."""

    if error.source_path != source_path:
        raise ValueError("Page site adapter error must retain the active source path")
    if source_path == "<cleanup>" and error.step != "cleanup":
        raise ValueError("Page cleanup errors require step=cleanup")
    if source_path != "<cleanup>" and not error.filesystem_boundary:
        if error.step not in {"page_projection", "page_storage"}:
            raise ValueError("Page item errors require a projection or storage step")


def _validate_missing_image_error(error: PageError, source_path: str) -> None:
    if not isinstance(error, PageError):
        raise TypeError("Page projection errors must be typed PageError values")
    if error.source_path != source_path or error.step != "image_reference_missing":
        raise ValueError("Page projection reported an unrelated cleanup-safe error")
    if error.filesystem_boundary or error.retryable or error.kind != "missing_asset":
        raise ValueError("Page projection reported an invalid missing-image disposition")


__all__ = [
    "PageBoundaryFailure",
    "PageCounts",
    "PageDetail",
    "PageError",
    "PageImportContext",
    "PageImportReport",
    "PageProjection",
    "PageSiteAdapter",
    "PageWrite",
    "page_site_adapter",
    "register_page_site_adapter",
    "validate_described_error",
    "validate_projection",
]
