"""The `wiki` kind: a flat graph of pages stored by the knowledge base."""

from __future__ import annotations

from community_base.content_sync.kinds.base import SHAPE_DOCUMENT, KeySpec, KindSpec
from community_base.content_sync.kinds.layouts import FlatLayout

SPEC = KindSpec(
    name="wiki",
    shape=SHAPE_DOCUMENT,
    layout=FlatLayout(part="wiki"),
    keys={
        "related": KeySpec("reference_list"),
        "page_type": KeySpec("slug"),
    },
    # Explicit, not derived: a wiki page's references live in its body as typed
    # links (`person:`, `podcast:`), which no key declaration can name.
    depends_on=("person",),
    route=lambda path: f"wiki/{path}",
)
