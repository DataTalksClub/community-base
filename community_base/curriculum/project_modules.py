"""Explicit host project-module reader and shared source-tree resolution."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from community_base.content_sync.documents import Collection, ReadResult
from community_base.curriculum.source import CurriculumParseError, ModuleGraph


@dataclass(frozen=True, slots=True)
class ProjectModuleReference:
    """One host-owned project's authored module reference."""

    project_id: str
    source_path: str
    module_path: str
    pointer: str = "/"


@dataclass(frozen=True, slots=True)
class ProjectModuleBinding:
    project_id: str
    source_path: str
    module_path: str
    module_source_path: str
    module_content_id: str | None


ProjectModuleReader = Callable[[ReadResult, Collection], Iterable[ProjectModuleReference]]
_reader: ProjectModuleReader | None = None


def register_project_module_reader(reader: ProjectModuleReader) -> ProjectModuleReader:
    """Register the one pure host reader used by sync and ``--kinds`` checks."""

    global _reader
    if not callable(reader):
        raise TypeError("Project module reader must be callable")
    if _reader is not None and _reader is not reader:
        raise ValueError("Project module reader already registered")
    _reader = reader
    return reader


def resolve_project_modules(
    result: ReadResult, collection: Collection, modules: tuple[ModuleGraph, ...]
) -> tuple[ProjectModuleBinding, ...]:
    """Resolve every host reference to exactly one module before any writes."""

    if _reader is None:
        return ()
    sources = _module_sources(collection, modules)
    seen_projects: set[str] = set()
    bindings = []
    for reference in _reader(result, collection):
        _validate_reference(reference)
        if reference.project_id in seen_projects:
            raise _error(reference, f"duplicate project identity {reference.project_id!r}")
        seen_projects.add(reference.project_id)
        _validate_module_path(reference)
        bindings.append(_binding(reference, sources))
    return tuple(bindings)


def _binding(reference, sources):
    matches = sources.get(reference.module_path, ())
    if len(matches) != 1:
        raise _error(
            reference,
            f"module path {reference.module_path!r} resolves to {len(matches)} modules",
        )
    module = matches[0]
    return ProjectModuleBinding(
        reference.project_id,
        reference.source_path,
        reference.module_path,
        module.source_path,
        module.content_id,
    )


def _module_sources(collection, modules):
    sources: dict[str, list[ModuleGraph]] = {}
    prefix = ""
    if collection.path:
        prefix = f"{collection.path}/"

    def visit(nodes):
        for module in nodes:
            path = module.source_path
            if not path.startswith(prefix) or not path.endswith("/module.yaml"):
                raise CurriculumParseError(f"{path}: invalid course module source path")
            relative = path[len(prefix) : -len("/module.yaml")]
            sources.setdefault(relative, []).append(module)
            visit(module.children)

    visit(modules)
    return sources


def _validate_reference(reference):
    if not isinstance(reference, ProjectModuleReference):
        raise CurriculumParseError("project module reader must yield ProjectModuleReference values")
    if not isinstance(reference.project_id, str) or not reference.project_id:
        raise _error(reference, "project identity is required")
    if not isinstance(reference.source_path, str) or not reference.source_path:
        raise _error(reference, "project source location is required")
    if not isinstance(reference.pointer, str) or not reference.pointer.startswith("/"):
        raise _error(reference, "project source pointer must start with /")


def _validate_module_path(reference):
    path = reference.module_path
    if not isinstance(path, str) or not path:
        raise _error(reference, "module path is required")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise _error(reference, f"module path {path!r} is not source-relative")


def _error(reference, message):
    return CurriculumParseError(f"{reference.source_path}:{reference.pointer}: [3.8] {message}")


def _clear_project_module_reader():
    """Reset the registration only for isolated registry tests."""

    global _reader
    _reader = None
