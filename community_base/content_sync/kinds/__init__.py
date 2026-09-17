"""The content kind registry (specification section 3.8).

`FORMAT.md` in this app is the normative text. A kind declares its file shape,
its layout, its keys, the kinds it depends on and a route resolver; the package
registers `course`, `article`, `person`, `wiki`, `docs` and `data`, and a site
registers its own from `AppConfig.ready()`:

    from community_base.content_sync.kinds import KeySpec, KindSpec, register_kind
    from community_base.content_sync.kinds.layouts import ItemDirectoryLayout

    register_kind("workshop", KindSpec(name="workshop", ...))

Importing this package registers the package kinds once. Registration is
idempotent here and refused elsewhere, so a site cannot silently replace a
package kind.
"""

from __future__ import annotations

from community_base.content_sync.kinds import article, course, data, docs, person, wiki
from community_base.content_sync.kinds.base import (
    ASSET_SUFFIXES,
    CORE_KEYS,
    KEY_TYPES,
    MAX_ASSET_BYTES,
    MAX_SLUG_LENGTH,
    SHAPE_DATA,
    SHAPE_DOCUMENT,
    SHAPE_MANIFEST,
    SHAPE_TREE,
    SHAPES,
    SLUG_PATTERN,
    DirNode,
    KeySpec,
    KindSpec,
    Layout,
    PartSpec,
    Problem,
    RawItem,
    check_item_keys,
    check_value,
    effective_keys,
    slug_from_name,
    split_order_prefix,
)
from community_base.content_sync.kinds.registry import (
    KindDependencyError,
    get_kind,
    is_registered,
    kind_order,
    kinds,
    register_kind,
)

PACKAGE_KINDS = (
    article.SPEC,
    course.SPEC,
    data.SPEC,
    docs.SPEC,
    person.SPEC,
    wiki.SPEC,
)

PACKAGE_KIND_NAMES = tuple(spec.name for spec in PACKAGE_KINDS)


def register_package_kinds() -> None:
    """Register the kinds the package owns; already-registered ones stay."""

    for spec in PACKAGE_KINDS:
        if not is_registered(spec.name):
            register_kind(spec.name, spec)


register_package_kinds()

__all__ = [
    "ASSET_SUFFIXES",
    "CORE_KEYS",
    "KEY_TYPES",
    "MAX_ASSET_BYTES",
    "MAX_SLUG_LENGTH",
    "PACKAGE_KINDS",
    "PACKAGE_KIND_NAMES",
    "SHAPES",
    "SHAPE_DATA",
    "SHAPE_DOCUMENT",
    "SHAPE_MANIFEST",
    "SHAPE_TREE",
    "SLUG_PATTERN",
    "DirNode",
    "KeySpec",
    "KindDependencyError",
    "KindSpec",
    "Layout",
    "PartSpec",
    "Problem",
    "RawItem",
    "check_item_keys",
    "check_value",
    "effective_keys",
    "get_kind",
    "is_registered",
    "kind_order",
    "kinds",
    "register_kind",
    "register_package_kinds",
    "slug_from_name",
    "split_order_prefix",
]
