"""Synthetic site compatibility values for the package page parser tests."""

import hashlib
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from community_base.knowledge_base.page_adaptation import (
    PageBoundaryFailure,
    PageError,
    PageProjection,
)

WIKI_ID = "11111111-1111-4111-8111-111111111111"
SECOND_WIKI_ID = "22222222-2222-4222-8222-222222222222"
DOCS_ID = "33333333-3333-4333-8333-333333333333"
CHILD_ID = "44444444-4444-4444-8444-444444444444"
LEAF_ID = "55555555-5555-4555-8555-555555555555"


def document(content_id: str, title: str, body: str = "Body.") -> str:
    return (
        f'---\ncontent_id: "{content_id}"\ntitle: {title}\nsummary: About {title}.\n---\n\n{body}\n'
    )


def write_repository(root: Path, files: dict[str, str], *, manifest: str | None = None) -> Path:
    root.mkdir(parents=True)
    if manifest is None:
        lines = ["schema_version: 1", "collections:"]
        for section in ("wiki", "docs"):
            if any(name.startswith(f"{section}/") for name in files):
                lines.extend((f"  - kind: {section}", f"    path: {section}"))
        manifest = "\n".join(lines) + "\n"
    (root / "content.yaml").write_text(manifest)
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return root


def collections_manifest(*kinds: str, extra: str = "") -> str:
    lines = ["schema_version: 1", "collections:"]
    for kind in kinds:
        path = kind
        if kind == "person":
            path = "people"
        lines.extend((f"  - kind: {kind}", f"    path: {path}"))
    if extra:
        lines.append(extra)
    return "\n".join(lines) + "\n"


@contextmanager
def package_page_parsers():
    """Install package parsers without depending on prior test registry state."""

    from community_base.content_sync import parsers
    from community_base.knowledge_base.content_sync_parsers import register_parsers

    previous = parsers.parsers()
    parsers._clear()
    register_parsers()
    try:
        yield
    finally:
        parsers._clear()
        for content_type, parser in previous:
            parsers.register_parser(content_type, parser)


class RecordingPageAdapter:
    """A synthetic site projection with observable error and report boundaries."""

    def __init__(self) -> None:
        self.fail_path = ""
        self.boundary_path = ""
        self.mutate_identity = False
        self.raise_finished = False
        self.tracebacks = []
        self.reports = []

    def project(self, context, document, default):
        if document.source_path == self.boundary_path:
            try:
                raise OSError("private-canary outside checkout")
            except OSError as cause:
                self.tracebacks.append(sys.exc_info()[2])
                error = PageError(
                    file=document.source_path,
                    error=f"{document.source_path}: outside_checkout",
                    step="filesystem_boundary",
                    kind="outside_checkout",
                    filesystem_boundary=True,
                )
                raise PageBoundaryFailure(error) from cause
        if document.source_path == self.fail_path:
            raise ValueError("projection failed with private-canary")
        write = self._projected_write(context, document, default)
        if self.mutate_identity:
            write = replace(write, source_path="wiki/replaced.md")
        return PageProjection(write=write, errors=self._missing_errors(context))

    def _projected_write(self, context, document, default):
        record = dict(default.record)
        record["projected"] = context.section
        return replace(
            default,
            body_html=f"<p>site:{document.document.body.strip()}</p>",
            public_path=f"/projected/{context.section}/{default.slug}/",
            record=record,
            checksum=hashlib.sha256(f"site:{default.checksum}".encode()).hexdigest(),
        )

    def _missing_errors(self, context):
        warnings = []
        for diagnostic in context.missing_assets:
            warnings.append(
                PageError(
                    file=diagnostic.path,
                    error="Referenced image is missing",
                    step="image_reference_missing",
                    kind="missing_asset",
                )
            )
        return tuple(warnings)

    def describe_error(self, context, source_path, error, traceback):
        self.tracebacks.append(traceback)
        step = "page_projection"
        if source_path == "<cleanup>":
            step = "cleanup"
        return PageError(
            file=source_path,
            error=f"Could not publish {source_path}",
            step=step,
            kind="site_projection",
        )

    def finished(self, context, report):
        self.reports.append(report)
        if self.raise_finished:
            raise RuntimeError("final reporter failed")
