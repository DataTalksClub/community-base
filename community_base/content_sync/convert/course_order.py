"""Transfer authored legacy unit-list order into canonical unit files."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from community_base.content_sync.convert.report import read_front_matter
from community_base.content_sync.kinds.base import slug_from_name, split_order_prefix


class OrderRefusal(ValueError):
    """An old list and the authored positions cannot be reconciled."""


def preserve_list_order(
    root: Path,
    rel: str,
    found: dict[str, dict[str, Any]],
    entries: list[Any],
    ignored: Callable[[str], bool],
) -> None:
    """Write list positions only where no stronger authored order exists."""

    mixed = _has_other_siblings(root / rel, rel, ignored)
    eligible, positions = _declared_positions(root, rel, found, entries, ignored, mixed=mixed)
    if mixed and positions != sorted(set(positions)):
        raise OrderRefusal(f"{rel}/units has contradictory authored list and sort_order")
    if not mixed and not _flat_order_agrees(root / rel, eligible, positions):
        raise OrderRefusal(f"{rel}/units has contradictory authored list and sort_order")


def _declared_positions(root, rel, found, entries, ignored, *, mixed):
    eligible = []
    positions = []
    for index, entry in enumerate(entries, start=1):
        name = str(entry["path"])
        if ignored(f"{rel}/{name}"):
            continue
        position = _position(root / rel / name, found[name], mixed=mixed)
        if position is None:
            if mixed:
                raise OrderRefusal(f"{rel}/units needs positions beside mixed siblings")
            position = index
            found[name]["sort_order"] = position
        if not isinstance(position, int) or isinstance(position, bool):
            raise OrderRefusal(f"{rel}/units/{index - 1} has a non-integer sort_order")
        eligible.append(entry)
        positions.append(position)
    return eligible, positions


def _flat_order_agrees(directory: Path, entries: list[Any], positions: list[int]) -> bool:
    previous = None
    for entry, position in zip(entries, positions, strict=True):
        path = directory / str(entry["path"])
        front, _ = read_front_matter(path.read_text(encoding="utf-8"))
        slug = None
        if front:
            slug = front.get("slug")
        if not slug:
            slug = slug_from_name(path.name)
        current = (position, str(slug))
        if previous is not None and current < previous:
            return False
        previous = current
    return True


def _has_other_siblings(directory: Path, rel: str, ignored: Callable[[str], bool]) -> bool:
    for item in directory.iterdir():
        path = f"{rel}/{item.name}"
        if not item.is_dir() or ignored(path):
            continue
        for manifest in ("module.yaml", "homework.yaml"):
            if (item / manifest).is_file() and not ignored(f"{path}/{manifest}"):
                return True
    return False


def _position(path: Path, supplied: dict[str, Any], *, mixed: bool) -> Any:
    front, _ = read_front_matter(path.read_text(encoding="utf-8"))
    explicit = supplied.get("sort_order")
    if front is not None and front.get("sort_order") is not None:
        if explicit is not None and str(explicit) != str(front["sort_order"]):
            raise OrderRefusal(f"{path}: module list and unit sort_order disagree")
        return front["sort_order"]
    if explicit is not None:
        return explicit
    if mixed:
        prefix, _ = split_order_prefix(path.name)
        return prefix
    return None
