"""The five layouts a kind can use to turn files into items (sections 3.2, 3.5).

A layout reads a `DirNode` tree and returns `RawItem` values plus layout
problems. It opens nothing, so every nesting rule of section 3.5 is decided
from names alone and a site kind can reuse a package layout.
"""

from __future__ import annotations

from community_base.content_sync.kinds.base import (
    DirNode,
    Layout,
    Problem,
    RawItem,
    is_asset_name,
)
from community_base.content_sync.kinds.course_layout import (
    CODE_DIR,
    COHORT_MANIFEST,
    COHORTS_DIR,
    COURSE_MANIFEST,
    HOMEWORK_DIR,
    HOMEWORK_MANIFEST,
    MODULE_MANIFEST,
    README,
    CourseLayout,
    _base_name,
    is_asset_dir,
)

Found = tuple[list[RawItem], list[tuple[str, Problem]]]

__all__ = [
    "CODE_DIR",
    "COHORT_MANIFEST",
    "COHORTS_DIR",
    "COURSE_MANIFEST",
    "HOMEWORK_DIR",
    "HOMEWORK_MANIFEST",
    "MODULE_MANIFEST",
    "README",
    "CourseLayout",
    "FlatLayout",
    "TreeLayout",
    "ItemDirectoryLayout",
    "DataLayout",
]


class FlatLayout(Layout):
    """One directory of `slug.md` documents; subdirectories are assets only."""

    def __init__(self, part: str = "page", suffix: str = ".md") -> None:
        self.part = part
        self.suffix = suffix

    def walk(self, root: DirNode) -> Found:
        items: list[RawItem] = []
        problems: list[tuple[str, Problem]] = []
        for name in root.files:
            path = root.joined(name)
            if name == README or is_asset_name(name):
                continue
            if not name.endswith(self.suffix):
                problems.append(
                    (
                        path,
                        Problem("", "3.2", f"a flat collection holds {self.suffix} files only"),
                    )
                )
                continue
            items.append(RawItem(part=self.part, path=path, container=root.path, name=name))
        for child in root.dirs:
            if is_asset_dir(child):
                continue
            problems.append(
                (
                    child.path,
                    Problem("", "3.5", "a flat collection has no subdirectories apart from assets"),
                )
            )
        return items, problems


class TreeLayout(Layout):
    """Directories are nodes with `index.md`; leaves are `NN-slug.md` files."""

    def __init__(self, part: str = "page", index: str = "index.md", max_depth: int = 4) -> None:
        self.part = part
        self.index = index
        self.max_depth = max_depth

    def walk(self, root: DirNode) -> Found:
        items: list[RawItem] = []
        problems: list[tuple[str, Problem]] = []
        self._walk(
            root, parent_container="", parent_path=None, depth=0, items=items, problems=problems
        )
        return items, problems

    def _walk(self, node, parent_container, parent_path, depth, items, problems) -> None:
        index_path = node.joined(self.index)
        documents = [
            name for name in node.files if name.endswith(".md") and name not in (self.index, README)
        ]
        children = [child for child in node.dirs if not is_asset_dir(child)]
        if node.has(self.index):
            items.append(
                RawItem(
                    part=self.part,
                    path=index_path,
                    container=parent_container,
                    name=_base_name(node.path) or self.index,
                    parent=parent_path,
                    # The collection root is the tree root: its path is empty,
                    # so `docs:courses/llm-zoomcamp` counts from below it.
                    contributes_slug=depth > 0,
                )
            )
            parent_path = index_path
        elif documents or children:
            problems.append(
                (
                    node.path or ".",
                    Problem("", "3.5", f"a tree node must contain {self.index}"),
                )
            )
        for name in documents:
            items.append(
                RawItem(
                    part=self.part,
                    path=node.joined(name),
                    container=node.path,
                    name=name,
                    parent=parent_path,
                )
            )
        for name in node.files:
            if not name.endswith(".md") and not is_asset_name(name) and name != README:
                problems.append(
                    (
                        node.joined(name),
                        Problem("", "3.2", "a docs collection holds .md files only"),
                    )
                )
        for child in children:
            if depth + 1 > self.max_depth:
                problems.append(
                    (
                        child.path,
                        Problem(
                            "",
                            "3.5",
                            f"nesting is deeper than {self.max_depth} levels below the collection",
                        ),
                    )
                )
                continue
            self._walk(child, node.path, parent_path, depth + 1, items, problems)


class ItemDirectoryLayout(Layout):
    """One directory per item, holding `index.md` (or a fixed manifest) and assets."""

    def __init__(self, part: str = "item", document: str = "index.md") -> None:
        self.part = part
        self.document = document

    def walk(self, root: DirNode) -> Found:
        items: list[RawItem] = []
        problems: list[tuple[str, Problem]] = []
        for name in root.files:
            if name == README or is_asset_name(name):
                continue
            problems.append(
                (
                    root.joined(name),
                    Problem("", "3.5", f"every item is a directory holding {self.document}"),
                )
            )
        for child in root.dirs:
            if is_asset_dir(child):
                continue
            if not child.has(self.document):
                problems.append(
                    (child.path, Problem("", "3.5", f"item directory has no {self.document}"))
                )
                continue
            items.append(
                RawItem(
                    part=self.part,
                    path=child.joined(self.document),
                    container=root.path,
                    name=_base_name(child.path),
                )
            )
        return items, problems


class DataLayout(Layout):
    """Opaque records: one per `.yaml` or `.json` file, keyed by its path stem."""

    def __init__(self, part: str = "data", suffixes: tuple[str, ...] = (".yaml", ".yml", ".json")):
        self.part = part
        self.suffixes = suffixes

    def walk(self, root: DirNode) -> Found:
        items: list[RawItem] = []
        self._walk(root, items)
        return items, []

    def _walk(self, node: DirNode, items: list[RawItem]) -> None:
        for name in node.files:
            if name.endswith(self.suffixes):
                items.append(
                    RawItem(
                        part=self.part,
                        path=node.joined(name),
                        container=node.path,
                        name=name,
                    )
                )
        for child in node.dirs:
            self._walk(child, items)
