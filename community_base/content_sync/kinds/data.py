"""The `data` kind: opaque records the package stores and a site interprets.

This is the one kind without core keys (section 3.3). It carries generated
artefacts and site configuration that ride in a content repository, such as a
podwiki graph or a tier list (decision D27).
"""

from __future__ import annotations

from community_base.content_sync.kinds.base import SHAPE_DATA, KindSpec
from community_base.content_sync.kinds.layouts import DataLayout

SPEC = KindSpec(
    name="data",
    shape=SHAPE_DATA,
    layout=DataLayout(part="data"),
    core_keys=False,
    allow_unknown=True,
)
