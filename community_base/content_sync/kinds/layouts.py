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

README = "README.md"
CODE_DIR = "code"
COHORTS_DIR = "cohorts"
HOMEWORK_DIR = "homework"
COURSE_MANIFEST = "course.yaml"
MODULE_MANIFEST = "module.yaml"
COHORT_MANIFEST = "cohort.yaml"
HOMEWORK_MANIFEST = "homework.yaml"

Found = tuple[list[RawItem], list[tuple[str, Problem]]]


def is_asset_dir(node: DirNode) -> bool:
    """A directory holding only assets at any depth carries no items (3.5)."""

    return all(is_asset_name(name) for name in node.files) and all(
        is_asset_dir(child) for child in node.dirs
    )


def _base_name(path: str) -> str:
    return path.rsplit("/", 1)[-1]


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


class CourseLayout(Layout):
    """The course tree of section 3.8: manifests, modules, units, cohorts.

    Files the layout does not recognise are ignored rather than rejected: a
    course repository carries notebooks, scripts and datasets beside its
    content, and `ignore` in `content.yaml` exists for the ones an author wants
    named.
    """

    def __init__(self, max_module_levels: int = 2) -> None:
        self.max_module_levels = max_module_levels

    def walk(self, root: DirNode) -> Found:
        items: list[RawItem] = []
        problems: list[tuple[str, Problem]] = []
        course_path = root.joined(COURSE_MANIFEST)
        if not root.has(COURSE_MANIFEST):
            problems.append(
                (
                    root.path or ".",
                    Problem("", "3.8", f"a course collection needs {COURSE_MANIFEST}"),
                )
            )
        else:
            items.append(
                RawItem(
                    part="course",
                    path=course_path,
                    container="",
                    name=_base_name(root.path),
                )
            )
        for child in root.dirs:
            name = _base_name(child.path)
            if name == COHORTS_DIR:
                self._walk_cohorts(child, items, problems)
                continue
            if name == CODE_DIR or is_asset_dir(child):
                continue
            self._walk_module(child, root.path, course_path, 1, items, problems)
        return items, problems

    def _walk_module(self, node, container, parent, level, items, problems) -> None:
        if not node.has(MODULE_MANIFEST):
            problems.append(
                (node.path, Problem("", "3.5", f"a module directory needs {MODULE_MANIFEST}"))
            )
            return
        if level > self.max_module_levels:
            problems.append(
                (
                    node.path,
                    Problem(
                        "", "3.5", f"a course has at most {self.max_module_levels} module levels"
                    ),
                )
            )
            return
        module_path = node.joined(MODULE_MANIFEST)
        items.append(
            RawItem(
                part="module",
                path=module_path,
                container=container,
                name=_base_name(node.path),
                parent=parent,
            )
        )
        units = [name for name in node.files if name.endswith(".md") and name != README]
        submodules = [
            child
            for child in node.dirs
            if _base_name(child.path) != CODE_DIR and not is_asset_dir(child)
        ]
        if units and submodules:
            problems.append(
                (
                    node.path,
                    Problem(
                        "",
                        "3.5",
                        "a module directory holds either submodule directories or unit files",
                    ),
                )
            )
        for name in units:
            items.append(
                RawItem(
                    part="unit",
                    path=node.joined(name),
                    container=node.path,
                    name=name,
                    parent=module_path,
                )
            )
        for child in submodules:
            self._walk_module(child, node.path, module_path, level + 1, items, problems)

    def _walk_cohorts(self, node, items, problems) -> None:
        for name in node.files:
            if name != README and not is_asset_name(name):
                problems.append(
                    (
                        node.joined(name),
                        Problem("", "3.8", "a cohort is a directory under cohorts/"),
                    )
                )
        for child in node.dirs:
            if not child.has(COHORT_MANIFEST):
                problems.append(
                    (child.path, Problem("", "3.8", f"a cohort directory needs {COHORT_MANIFEST}"))
                )
                continue
            cohort_path = child.joined(COHORT_MANIFEST)
            items.append(
                RawItem(
                    part="cohort",
                    path=cohort_path,
                    container=node.path,
                    name=_base_name(child.path),
                )
            )
            homework = child.child(HOMEWORK_DIR)
            if homework is None:
                continue
            for module_dir in homework.dirs:
                if not module_dir.has(HOMEWORK_MANIFEST):
                    problems.append(
                        (
                            module_dir.path,
                            Problem("", "3.8", f"a homework directory needs {HOMEWORK_MANIFEST}"),
                        )
                    )
                    continue
                items.append(
                    RawItem(
                        part="homework",
                        path=module_dir.joined(HOMEWORK_MANIFEST),
                        container=homework.path,
                        name=_base_name(module_dir.path),
                        parent=cohort_path,
                    )
                )
