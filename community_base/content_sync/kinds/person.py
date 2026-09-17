"""The `person` kind: the reference target of `authors`, `instructors`, `guests`."""

from __future__ import annotations

from community_base.content_sync.kinds.base import SHAPE_DOCUMENT, KeySpec, KindSpec
from community_base.content_sync.kinds.layouts import FlatLayout

LINK_LABELS = ("website", "linkedin", "github", "x", "youtube", "other")

SPEC = KindSpec(
    name="person",
    shape=SHAPE_DOCUMENT,
    layout=FlatLayout(part="person"),
    keys={
        "links": KeySpec(
            "object_list",
            item_keys={
                "label": KeySpec("choice", choices=LINK_LABELS, required=True),
                "url": KeySpec("url", required=True),
            },
        ),
    },
    route=lambda path: f"people/{path}",
)
