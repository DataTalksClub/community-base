from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Protocol


@dataclass(frozen=True)
class SourceItem:
    key: str
    path: PurePosixPath | str
    data: Mapping[str, Any]
    media_paths: tuple[str, ...] = field(default_factory=tuple)


class Parser(Protocol):
    def discover(self, checkout, source) -> Iterable[SourceItem]: ...

    def upsert(self, item: SourceItem, source, media) -> object: ...

    def soft_delete_missing(self, seen_keys: set[str], source) -> Iterable[object] | int: ...


_parsers: dict[str, Parser] = {}


def register_parser(content_type: str, parser: Parser) -> Parser:
    if not content_type:
        raise ValueError("Content type cannot be empty")
    if content_type in _parsers:
        raise ValueError(f"Content sync parser already registered: {content_type}")
    for method in ("discover", "upsert", "soft_delete_missing"):
        if not callable(getattr(parser, method, None)):
            raise TypeError(f"Content sync parser must implement {method}()")
    _parsers[content_type] = parser
    return parser


def parsers() -> tuple[tuple[str, Parser], ...]:
    return tuple(_parsers.items())


def get_parser(content_type: str) -> Parser:
    try:
        return _parsers[content_type]
    except KeyError:
        raise LookupError(f"No content sync parser registered for {content_type}") from None


def _clear() -> None:
    _parsers.clear()
