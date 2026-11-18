"""The `review_criteria` kind: standalone reusable peer-review criteria sets."""

from __future__ import annotations

from community_base.content_sync.kinds.base import (
    SEVERITY_ERROR,
    SHAPE_MANIFEST,
    KeySpec,
    KindSpec,
)
from community_base.content_sync.kinds.layouts import FlatLayout

CRITERION_TYPES = ("scale", "checklist")

CRITERION_OPTION_KEYS = {
    "points": KeySpec("integer", required=True),
    "text": KeySpec("string", required=True),
}

CRITERION_KEYS = {
    "id": KeySpec("slug", required=True),
    "title": KeySpec("string", required=True),
    "description": KeySpec("text"),
    "type": KeySpec("choice", choices=CRITERION_TYPES, default="scale"),
    "options": KeySpec("object_list", required=True, item_keys=CRITERION_OPTION_KEYS),
}

SPEC = KindSpec(
    name="review_criteria",
    shape=SHAPE_MANIFEST,
    layout=FlatLayout(part="review_criteria", suffix=".yaml"),
    keys={
        "description": KeySpec("text"),
        "criteria": KeySpec("object_list", required=True, item_keys=CRITERION_KEYS),
    },
)


def review_criteria_diagnostics(result) -> list:
    """Validate semantic rules for standalone `review_criteria` documents."""
    from community_base.content_sync.documents import Diagnostic
    from community_base.coursework.project_criteria import CriteriaError, parse_criteria_set

    diagnostics: list[Diagnostic] = []
    for document in result.by_kind(SPEC.name):
        raw = {
            **document.values,
            "slug": document.slug,
            "content_id": document.content_id,
        }
        try:
            parse_criteria_set(raw, document.source_path, default_slug=document.slug)
        except CriteriaError as error:
            diagnostics.append(
                Diagnostic(
                    path=document.source_path,
                    pointer="/criteria",
                    rule="3.8",
                    message=str(error),
                    severity=SEVERITY_ERROR,
                )
            )
    return diagnostics
