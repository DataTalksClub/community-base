"""Map document and manifest units onto the same curriculum UnitGraph."""

from __future__ import annotations

from dataclasses import replace

from community_base.content_sync.documents import ParsedDocument
from community_base.content_sync.kinds.base import resolve_level
from community_base.curriculum.code_annotations import CodeAnnotationError, validate_annotated_body
from community_base.curriculum.source import CurriculumParseError, UnitGraph


def _unit_graph(document: ParsedDocument, inherited: int | None) -> UnitGraph:
    values = document.values
    body = document.body
    _check_annotations(document.raw.path, body)
    return UnitGraph(
        content_id=document.content_id,
        slug=document.slug,
        title=document.title,
        source_path=document.raw.path,
        body=body,
        video_url=values.get("video_url") or "",
        timestamps=tuple(values.get("timestamps") or ()),
        required_level=_declared_level(document, inherited),
        sort_order=document.sort_order,
        kind=values.get("kind") or "lesson",
        session_position=values.get("session_position"),
        is_bonus=bool(values.get("is_bonus")),
    )


def _source_unit_graph(result, document, inherited):
    if document.part.name == "unit":
        return _unit_graph(document, inherited)
    repository = result.repository
    directory = document.raw.path.rsplit("/", 1)[0]
    companion = f"{directory}/homework.md"
    body = repository.read_text(companion)
    _check_annotations(companion, body)
    return replace(_unit_graph(document, inherited), body=body, kind="homework")


def _declared_level(document: ParsedDocument, inherited: int | None) -> int | None:
    """The unit's own level, else the one its module ancestors declared.

    Section 3.3 inherits `required_level` from the parent item. The course sits
    at the top of that chain, and a unit that takes the course's level must
    stay `None` here so that `Course.default_unit_required_level` still answers
    for it (`Unit.effective_required_level`).
    """

    declared = resolve_level(document.data.get("required_level"))
    if declared is None:
        return inherited
    return declared


def _check_annotations(path: str, body: str) -> None:
    """Reject a malformed structured code annotation before anything is written."""

    try:
        validate_annotated_body(body, path)
    except CodeAnnotationError as error:
        raise CurriculumParseError(str(error)) from None
