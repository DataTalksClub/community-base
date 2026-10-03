"""The sole document output plan, report accounting and filesystem writer."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from community_base.content_sync.convert.contracts import MANIFEST_NAME, Collection, Profile
from community_base.content_sync.convert.report import ConversionReport, dump_yaml


class DocumentOutput:
    def __init__(self, root: Path, profile: Profile, report: ConversionReport, apply: bool) -> None:
        self.root = root
        self.profile = profile
        self.report = report
        self.apply = apply
        self.writes: list[tuple[str, str]] = []
        self.copies: list[tuple[str, str]] = []
        self.removals: list[str] = []
        self.touched: set[str] = set()

    def refuse_page(self, source: str, rule: str, message: str) -> None:
        self.report.refuse(source, rule, message)
        self.report.record(source, "refused")
        self.touched.add(source)

    def move_single_file(self, collection: Collection) -> bool:
        path = self.root / collection.source
        target = f"{collection.target.rstrip('/')}/{path.name}"
        if path.is_file():
            self.copies.append((collection.source, target))
            self.report.record(
                collection.source, "renamed", target=target, details=["carried across unread"]
            )
            self.touched.add(collection.source)
            return True
        return (self.root / target).is_file()

    def move_verbatim(self, collection: Collection, directory: Path) -> None:
        """FORMAT3.8/D26: carry opaque bytes unchanged."""

        suffixes = None
        if collection.layout == "data":
            suffixes = (".yaml", ".yml", ".json")
        for path in sorted(directory.glob("**/*")):
            if not path.is_file():
                continue
            if suffixes is not None and path.suffix not in suffixes:
                continue
            source = path.relative_to(self.root).as_posix()
            rel = path.relative_to(directory).as_posix()
            if suffixes:
                rel = path.name
            target = f"{collection.target}/{rel}"
            self.copies.append((source, target))
            self.report.record(source, "renamed", target=target, details=["carried across unread"])
            self.touched.add(source)

    def move_assets(self, source: str, target: str) -> None:
        directory = self.root / source
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("**/*")):
            if not path.is_file():
                continue
            rel = path.relative_to(directory).as_posix()
            old = path.relative_to(self.root).as_posix()
            self.copies.append((old, f"{target}/{rel}"))
            self.report.record(old, "renamed", target=f"{target}/{rel}")
            self.touched.add(old)

    def put(self, source: str, target: str, text: str, details: Sequence[str]) -> None:
        existing = self.root / target
        if source == target:
            if existing.read_text(encoding="utf-8") == text:
                self.report.record(source, "unchanged")
            else:
                self.writes.append((target, text))
                self.report.record(source, "rewritten", details=details)
            self.touched.add(source)
            return
        self.writes.append((target, text))
        self.removals.append(source)
        self.report.record(source, "renamed", target=target, details=details)
        self.touched.add(source)

    def write_manifest(self) -> None:
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "collections": [
                {"kind": item.kind, "path": item.target} for item in self.profile.collections
            ],
        }
        if self.profile.ignore:
            manifest["ignore"] = list(self.profile.ignore)
        if self.profile.strict_references is not None:
            manifest["strict_references"] = self.profile.strict_references
        if self.profile.theme_pairs:
            manifest["theme_pairs"] = True
        text = dump_yaml(manifest)
        existing = self.root / MANIFEST_NAME
        if existing.is_file() and existing.read_text(encoding="utf-8") == text:
            self.report.record(MANIFEST_NAME, "unchanged")
        else:
            self.writes.append((MANIFEST_NAME, text))
            action = "rewritten"
            if not existing.is_file():
                action = "created"
            self.report.record(MANIFEST_NAME, action)
        self.touched.add(MANIFEST_NAME)

    def account(self) -> None:
        for path in sorted(self.report.before):
            if path not in self.touched:
                self.report.record(path, "unchanged")

    def flush(self) -> None:
        if not self.apply:
            return
        for source, target in self.copies:
            destination = self.root / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((self.root / source).read_bytes())
            (self.root / source).unlink()
        for path, text in self.writes:
            destination = self.root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
        for path in self.removals:
            target = self.root / path
            if target.is_file():
                target.unlink()
        _prune(self.root)


def _prune(root: Path) -> None:
    """Remove the directories a rename emptied, and nothing else."""

    for path in sorted(root.glob("**/*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
