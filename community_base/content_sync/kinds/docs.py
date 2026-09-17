"""The `docs` kind: a tree of pages whose parent is the directory, nothing else."""

from __future__ import annotations

from community_base.content_sync.kinds.base import SHAPE_TREE, KeySpec, KindSpec
from community_base.content_sync.kinds.layouts import TreeLayout

MAX_DEPTH = 4

SPEC = KindSpec(
    name="docs",
    shape=SHAPE_TREE,
    layout=TreeLayout(part="docs", max_depth=MAX_DEPTH),
    keys={"toc": KeySpec("boolean", default=True)},
    route=lambda path: f"docs/{path}",
)
