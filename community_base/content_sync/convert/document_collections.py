"""Single discovery owner: filtering, naming, placement and collection URL indexes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from community_base.content_sync.convert.contracts import (
    DATE_NAME,
    ORDER_PREFIX,
    Collection,
    Profile,
)
from community_base.content_sync.convert.document_output import DocumentOutput
from community_base.content_sync.convert.report import read_front_matter


class DocumentCollections:
    def __init__(self, root: Path, profile: Profile, output: DocumentOutput) -> None:
        self.root = root
        self.profile = profile
        self.output = output
        self.report = output.report

    def directory(self, collection: Collection) -> Path | None:
        directory = self.root / collection.source
        if directory.is_dir():
            return directory
        already = self.root / collection.target
        if already.exists() and collection.source != collection.target:
            return None
        self.report.refuse(
            collection.source, "3.1", "the profile names a directory that is not there"
        )
        return None

    def yaml_paths(self, collection: Collection) -> list[Path]:
        name = collection.manifest
        if not name:
            self.report.refuse(
                collection.source, "3.2", "a yaml collection names the manifest file"
            )
            return []
        directory = self.root / collection.source
        if not directory.is_dir():
            self.report.refuse(
                collection.source, "3.1", "the profile names a directory that is not there"
            )
            return []
        found = []
        for path in sorted(directory.glob(f"**/{name}")):
            if any(part.startswith(".") for part in path.relative_to(directory).parts):
                continue
            if not self.is_ignored(path.relative_to(self.root).as_posix()):
                found.append(path)
        if not found:
            self.report.refuse(
                collection.source, "3.1", f"no {name} files under the collection root"
            )
        return found

    def pages(self, collection: Collection, directory: Path) -> list[dict[str, Any]]:
        found = []
        for path in sorted(self.candidates(collection, directory)):
            source = path.relative_to(self.root).as_posix()
            if self.is_ignored(source) or path.name.startswith("."):
                continue
            front, body = read_front_matter(path.read_text(encoding="utf-8"))
            if front is None:
                self.output.refuse_page(source, "3.2", "a document carries front matter")
                continue
            name = path.name
            if collection.layout == "tree" and name == "index.md":
                name = path.parent.name or collection.target
            if collection.layout == "item" and name == "index.md":
                name = path.parent.name
            found.append(
                {
                    "source": source,
                    "path": path,
                    "front": front,
                    "body": body,
                    "slug": _slug_of(name, collection),
                }
            )
        return found

    def candidates(self, collection: Collection, directory: Path) -> list[Path]:
        roots = [directory]
        if collection.roots:
            roots = [directory / name for name in collection.roots]
        found = []
        for root in roots:
            if root.is_file():
                found.append(root)
                continue
            if not root.is_dir():
                self.report.refuse(
                    root.relative_to(self.root).as_posix(),
                    "3.1",
                    "the profile names it and it is not there",
                )
                continue
            for path in root.glob("**/*.md"):
                # Hidden and underscore trees are excluded below the collection root.
                if any(part.startswith((".", "_")) for part in path.relative_to(root).parts):
                    continue
                found.append(path)
        return found

    def is_ignored(self, source: str) -> bool:
        return any(Path(source).match(pattern) for pattern in self.profile.ignore)

    def place(self, collection: Collection, pages: list[dict[str, Any]]) -> None:
        for page in pages:
            page["directory"] = _directory_of(collection, str(page["source"]))
            page["index"] = Path(str(page["source"])).name == "index.md"
            page["node"] = False
        if not collection.parent_titles:
            return
        self._section_nodes(pages)
        by_title = {}
        for page in pages:
            key = (str(page["directory"]), str(page["front"].get("title") or "").strip().lower())
            by_title[key] = page
        for _ in range(4):
            if not self._place_children(pages, by_title):
                break

    def _section_nodes(self, pages: list[dict[str, Any]]) -> None:
        directories = {str(page["directory"]) for page in pages}
        for page in pages:
            if page["index"]:
                continue
            owned = f"{page['directory']}/{page['slug']}".strip("/")
            if owned in directories:
                # D28: a section beside its directory is that directory's index.
                page["index"] = True
                page["directory"] = owned

    def _place_children(self, pages, by_title) -> bool:
        moved = False
        for page in pages:
            parent = str(page["front"].get("parent") or "").strip().lower()
            if not parent or page["index"]:
                continue
            owner = by_title.get((str(page["directory"]), parent))
            if owner is None or owner is page or owner["index"]:
                continue
            owner["node"] = True
            page["directory"] = f"{owner['directory']}/{owner['slug']}".strip("/")
            moved = True
        return moved

    def target(self, collection: Collection, page: Mapping[str, Any], slug: str) -> str:
        if collection.layout == "item":
            return f"{collection.target}/{slug}/index.md"
        if collection.layout == "tree":
            directory = str(page.get("directory") or "")
            if page.get("index"):
                name = "index.md"
            elif page.get("node"):
                name = f"{slug}/index.md"
            else:
                name = f"{slug}.md"
            return _joined(collection.target, directory, name)
        return f"{collection.target}/{slug}.md"


def _joined(*parts: str) -> str:
    found = []
    for part in parts:
        if part:
            found.append(part)
    return "/".join(found)


def _slug_of(name: str, collection: Collection) -> str:
    stem = name
    if name.endswith(".md"):
        stem = name[:-3]
    if stem == "index":
        return "index"
    if collection.date_from_name:
        stem = DATE_NAME.sub("", stem)
    return ORDER_PREFIX.sub("", stem)


def _directory_of(collection: Collection, source: str) -> str:
    parent = Path(source).parent.as_posix()
    if parent in (".", collection.source):
        return ""
    if collection.source not in (".", "") and parent.startswith(f"{collection.source}/"):
        return parent[len(collection.source) + 1 :]
    return parent


def _jekyll_urls(collection: Collection, pages: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    found = {}
    for page in pages:
        stem = str(page["source"])[:-3]
        if collection.source not in (".", "") and stem.startswith(f"{collection.source}/"):
            stem = stem[len(collection.source) + 1 :]
        if stem.endswith("/index"):
            stem = stem[: -len("/index")]
        directory = str(page.get("directory") or "")
        name = str(page["slug"])
        target = _joined(collection.target, directory, f"{name}.md")
        if page.get("index"):
            target = _joined(collection.target, directory, "index.md")
        elif page.get("node"):
            target = _joined(collection.target, directory, name, "index.md")
        found[f"{collection.url_prefix}/{stem}/".replace("//", "/")] = target
    return found
