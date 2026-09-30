"""Build the course's module tree with one authored order for mixed siblings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from community_base.content_sync.documents import ParsedDocument, ReadResult
from community_base.content_sync.kinds.base import resolve_level, split_order_prefix
from community_base.curriculum.source import CurriculumParseError, ModuleGraph
from community_base.curriculum.source_unit_parser import _source_unit_graph

README = "README.md"


def module_graphs(
    result: ReadResult,
    by_parent: Mapping[str | None, list[ParsedDocument]],
    *,
    parent: str,
    inherited: int | None,
) -> tuple[ModuleGraph, ...]:
    documents = []
    for document in by_parent.get(parent, ()):
        if document.part.name == "module":
            documents.append(document)
    documents.sort(key=lambda document: document.sort_key)
    return tuple(_module_graph(result, by_parent, document, inherited) for document in documents)


def _module_graph(result, by_parent, document, inherited) -> ModuleGraph:
    values = document.values
    level = resolve_level(document.data.get("required_level"))
    if level is None:
        level = inherited
    direct = _direct_unit_documents(by_parent, document.raw.path)
    units = tuple(_source_unit_graph(result, item, level) for item in direct)
    children = module_graphs(result, by_parent, parent=document.raw.path, inherited=level)
    if children and units:
        children, units = _position_mixed(children, units, by_parent[document.raw.path])
    return ModuleGraph(
        content_id=document.content_id,
        slug=document.slug,
        title=document.title,
        source_path=document.raw.path,
        overview=_overview(result, document),
        syllabus_section=values.get("syllabus_section") or "",
        sort_order=document.sort_order,
        is_bonus=bool(values.get("is_bonus")),
        available_after_days=values.get("available_after_days"),
        units=units,
        children=children,
    )


def _direct_unit_documents(by_parent, path):
    units = []
    for document in by_parent.get(path, ()):
        if document.part.name in ("unit", "homework_unit"):
            units.append(document)
    units.sort(key=lambda document: document.sort_key)
    return units


def _position_mixed(children, units, documents):
    positions = _mixed_positions(documents)
    positioned_children = tuple(
        replace(child, source_sibling_position=positions[child.source_path]) for child in children
    )
    positioned_units = tuple(
        replace(unit, source_sibling_position=positions[unit.source_path]) for unit in units
    )
    return positioned_children, positioned_units


def _mixed_positions(documents):
    seen: dict[int, str] = {}
    ordered = []
    for document in documents:
        if document.part.name not in ("module", "unit", "homework_unit"):
            continue
        prefix, _ = split_order_prefix(document.raw.name)
        if "sort_order" not in document.data and prefix is None:
            raise CurriculumParseError(
                f"{document.raw.path}:/sort_order: [3.8] mixed sibling needs authored order"
            )
        first = seen.get(document.sort_order)
        if first is not None:
            raise CurriculumParseError(
                f"{document.raw.path}:/sort_order: [3.8] mixed sibling order "
                f"{document.sort_order} is already used by {first}"
            )
        seen[document.sort_order] = document.raw.path
        ordered.append(document)
    ordered.sort(key=lambda document: document.sort_order)
    return {document.raw.path: index for index, document in enumerate(ordered)}


def _overview(result: ReadResult, document: ParsedDocument) -> str:
    """A module's README, without moving its source prose into the manifest."""

    directory = document.raw.path.rsplit("/", 1)[0]
    path = README
    if directory:
        path = f"{directory}/{README}"
    repository = result.repository
    if repository is None or path not in repository.files:
        return ""
    return repository.read_text(path)
