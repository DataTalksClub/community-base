"""The kind registry: `register_kind`, `get_kind` and the dependency order.

The registry mirrors `community_base.content_sync.parsers`: a mapping filled at
import time by the package and from `AppConfig.ready()` by a site, with
registration refused rather than overwritten. A kind may add keys; it may never
remove, rename or retype a core key, which is checked here and not left to
review.
"""

from __future__ import annotations

from community_base.content_sync.kinds.base import (
    CORE_KEYS,
    KEY_TYPES,
    KIND_NAME_PATTERN,
    SHAPES,
    KindSpec,
    Layout,
    PartSpec,
)


class KindDependencyError(Exception):
    """The declared kind dependencies do not form an order."""


_kinds: dict[str, KindSpec] = {}


def register_kind(name: str, spec: KindSpec) -> KindSpec:
    if not name:
        raise ValueError("Kind name cannot be empty")
    if not KIND_NAME_PATTERN.match(name):
        raise ValueError(f"Kind name must match {KIND_NAME_PATTERN.pattern}: {name}")
    if name in _kinds:
        raise ValueError(f"Content kind already registered: {name}")
    if not isinstance(spec, KindSpec):
        raise TypeError("register_kind needs a KindSpec")
    if spec.name != name:
        raise ValueError(f"Kind registered as {name} declares the name {spec.name}")
    if spec.shape not in SHAPES:
        raise ValueError(f"Kind {name} has an unknown shape: {spec.shape}")
    if not isinstance(spec.layout, Layout):
        raise TypeError(f"Kind {name} needs a Layout")
    for part in spec.item_parts.values():
        _check_part(name, part)
    _kinds[name] = spec
    return spec


def _check_part(kind: str, part: PartSpec) -> None:
    if part.shape not in SHAPES:
        raise ValueError(f"Kind {kind} part {part.name} has an unknown shape: {part.shape}")
    for key, key_spec in part.keys.items():
        if part.core_keys and key in CORE_KEYS:
            raise ValueError(
                f"Kind {kind} redefines the core key {key}; a kind adds keys and uses extra"
            )
        if key_spec.type not in KEY_TYPES:
            raise ValueError(f"Kind {kind} key {key} has an unknown type: {key_spec.type}")


def get_kind(name: str) -> KindSpec:
    try:
        return _kinds[name]
    except KeyError:
        raise LookupError(f"No content kind registered for {name}") from None


def is_registered(name: str) -> bool:
    return name in _kinds


def kinds() -> tuple[tuple[str, KindSpec], ...]:
    return tuple(sorted(_kinds.items()))


def kind_order(names: list[str] | tuple[str, ...] | None = None) -> tuple[str, ...]:
    """Registered kinds in dependency order, ties broken by name.

    Section 3.7 orders sources by the declared kinds' dependencies. Ordering
    kinds is the whole of it: a source is synced once every kind its
    collections depend on has been synced. A dependency on a kind nobody
    registered still appears in the order, as a leaf, so that a caller sees the
    name instead of having it silently dropped.
    """

    wanted = tuple(names) if names is not None else tuple(sorted(_kinds))
    pending = {name: set(_dependencies(name)) for name in _expand(wanted)}
    ordered: list[str] = []
    while pending:
        ready = sorted(name for name, needs in pending.items() if not (needs - set(ordered)))
        if not ready:
            cycle = ", ".join(sorted(pending))
            raise KindDependencyError(f"Kind dependencies form a cycle: {cycle}")
        for name in ready:
            ordered.append(name)
            del pending[name]
    return tuple(ordered)


def _expand(names: tuple[str, ...]) -> set[str]:
    seen: set[str] = set()
    queue = list(names)
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        queue.extend(_dependencies(name))
    return seen


def _dependencies(name: str) -> tuple[str, ...]:
    spec = _kinds.get(name)
    return spec.dependencies if spec is not None else ()


def _clear() -> None:
    _kinds.clear()


def _reset() -> None:
    """Back to the package kinds alone; for tests that register their own."""

    from community_base.content_sync.kinds import register_package_kinds

    _clear()
    register_package_kinds()
