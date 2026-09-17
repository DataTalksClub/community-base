"""The `article` kind: one directory per article, storage site-owned (D21)."""

from __future__ import annotations

from community_base.content_sync.kinds.base import SHAPE_DOCUMENT, KeySpec, KindSpec
from community_base.content_sync.kinds.layouts import ItemDirectoryLayout

SPEC = KindSpec(
    name="article",
    shape=SHAPE_DOCUMENT,
    layout=ItemDirectoryLayout(part="article", document="index.md"),
    requires_date=True,
    keys={
        "authors": KeySpec("reference_list", reference_kind="person"),
        "byline": KeySpec("text", max_length=300),
        "subtitle": KeySpec("text", max_length=300),
        "related": KeySpec("reference_list"),
        "faq": KeySpec(
            "object_list",
            item_keys={
                "question": KeySpec("string", required=True),
                "answer": KeySpec("markdown", required=True),
            },
        ),
    },
    route=lambda path: f"articles/{path}",
)
