"""The course tree layout and its shared name helpers."""

from __future__ import annotations

from community_base.content_sync.kinds.base import DirNode, Layout, Problem, RawItem, is_asset_name

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
        if not self._module_allowed(node, level, problems):
            return
        module_path = node.joined(MODULE_MANIFEST)
        items.append(self._module_item(node, container, parent))
        units, submodules, homework_units = self._module_contents(node)
        self._append_units(node, module_path, units, items)
        for child in submodules:
            self._walk_module(child, node.path, module_path, level + 1, items, problems)
        for child in homework_units:
            self._walk_homework_unit(child, module_path, items, problems)

    def _module_allowed(self, node, level, problems) -> bool:
        if not node.has(MODULE_MANIFEST):
            problems.append(
                (node.path, Problem("", "3.5", f"a module directory needs {MODULE_MANIFEST}"))
            )
            return False
        if level > self.max_module_levels:
            problems.append(
                (
                    node.path,
                    Problem(
                        "", "3.5", f"a course has at most {self.max_module_levels} module levels"
                    ),
                )
            )
            return False
        return True

    def _module_item(self, node, container, parent):
        return RawItem(
            part="module",
            path=node.joined(MODULE_MANIFEST),
            container=container,
            name=_base_name(node.path),
            parent=parent,
        )

    def _module_contents(self, node):
        units = []
        submodules = []
        homework_units = []
        for name in node.files:
            if name.endswith(".md") and name != README:
                units.append(name)
        for child in node.dirs:
            if _base_name(child.path) == CODE_DIR or is_asset_dir(child):
                continue
            if child.has(HOMEWORK_MANIFEST):
                homework_units.append(child)
            else:
                submodules.append(child)
        return units, submodules, homework_units

    def _append_units(self, node, module_path, units, items) -> None:
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

    def _walk_homework_unit(self, node, parent, items, problems) -> None:
        if node.has(MODULE_MANIFEST):
            problems.append(
                (node.path, Problem("", "3.8", "module.yaml and homework.yaml conflict"))
            )
            return
        companions = []
        for name in node.files:
            if name.endswith(".md"):
                companions.append(name)
        if companions != ["homework.md"]:
            problems.append(
                (
                    node.path,
                    Problem("", "3.8", "homework.yaml needs exactly one homework.md companion"),
                )
            )
            return
        items.append(
            RawItem(
                part="homework_unit",
                path=node.joined(HOMEWORK_MANIFEST),
                container=parent.rsplit("/", 1)[0],
                name=_base_name(node.path),
                parent=parent,
            )
        )

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
            self._walk_cohort_homework(child, cohort_path, items, problems)

    def _walk_cohort_homework(self, cohort, cohort_path, items, problems) -> None:
        homework = cohort.child(HOMEWORK_DIR)
        if homework is None:
            return
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
