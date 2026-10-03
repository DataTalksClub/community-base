"""The bounded source policy used only by the DTC article converter."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from community_base.content_sync.convert.contracts import DATE_NAME, Refused

ARTICLE_KEYS = ("subtitle", "authors", "faq")
NAMESPACE = "dtc_article_v1"
RAW_OPEN = "{% raw %}"
RAW_CLOSE = "{% endraw %}"
BLANK = re.compile(r"^[ \t]*(?:\r?\n)?$")
FENCE = re.compile(r"^(?P<indent> {0,3})(?P<mark>`{3,}|~{3,})(?P<info>[^\r\n]*)(?:\r?\n)?$")
RAW_LIKE = re.compile(r"\{%[- ]*\s*(?:end)?raw\b")


def prepare_metadata(
    page: Mapping[str, Any], data: dict[str, Any], details: list[str]
) -> dict[str, Any]:
    """Normalize metadata and install immutable source provenance."""

    extra = _authored_extra(data)
    if NAMESPACE in extra:
        _validate_replay(page, extra[NAMESPACE])
        data["extra"] = extra
        return data
    if "description" in data:
        summary = _description(data["description"])
        _set_summary(data, summary)
        details.append("description -> summary")
    field, display, chronology = _publication(page, data)
    data["date"] = chronology
    source = _source_provenance(page, data)
    extra[NAMESPACE] = {
        "source": source,
        "publication": {"field": field, "value": display},
    }
    data["extra"] = extra
    return data


def preserve_extra(data: dict[str, Any], known: set[str], details: list[str]) -> None:
    """Move DTC site keys without overwriting an authored extra value."""

    extra = _authored_extra(data)
    for name in list(data):
        if name in known:
            continue
        value = data.pop(name)
        if name in extra and extra[name] != value:
            raise Refused("3.3", f"top-level {name} conflicts with extra/{name}")
        if name in extra:
            details.append(f"{name} equals existing extra/{name}")
            continue
        extra[name] = value
        details.append(f"{name} -> extra")
    data["extra"] = extra


def unwrap_raw_fences(body: str) -> tuple[str, int]:
    lines = body.splitlines(keepends=True)
    output: list[str] = []
    fence: tuple[str, int] | None = None
    index = count = 0
    while index < len(lines):
        token = _line_token(lines[index])
        if fence is not None:
            output.append(lines[index])
            if _is_close(lines[index], fence):
                fence = None
            index += 1
            continue
        opening = _opening_fence(lines[index])
        if opening is not None:
            fence = opening
            output.append(lines[index])
            index += 1
            continue
        if token == RAW_CLOSE:
            raise Refused("4.1", "a standalone endraw has no matching raw wrapper")
        if token == RAW_OPEN:
            kept, index = _raw_pair(lines, index)
            output.extend(kept)
            count += 1
            continue
        _refuse_malformed_raw(lines[index])
        output.append(lines[index])
        index += 1
    return "".join(output), count


def _description(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping) and len(value) == 1:
        key, item = next(iter(value.items()))
        if isinstance(key, str) and isinstance(item, str):
            return f"{key}: {item}".strip()
    raise Refused("3.3", "description is a string or one string-to-string mapping")


def _set_summary(data: dict[str, Any], summary: str | None) -> None:
    original = data.pop("description")
    if "summary" in data and data["summary"] != summary:
        data["description"] = original
        raise Refused("3.3", "description and summary have incompatible values")
    data["summary"] = summary


def _publication(page: Mapping[str, Any], data: Mapping[str, Any]) -> tuple[str, str, str]:
    if data.get("date"):
        field = "date"
        value = data["date"]
    elif data.get("datepublished"):
        field = "datepublished"
        value = data["datepublished"]
    else:
        field = "filename"
        value = _filename_date(str(page["source"]))
    display = _display_date(value, field)
    return field, display, _calendar_date(display, field)


def _display_date(value: Any, field: str) -> str:
    if isinstance(value, bool):
        raise Refused("3.3", f"article {field} is an ISO date or datetime")
    if isinstance(value, (datetime, date)):
        found = value.isoformat()
    elif isinstance(value, str):
        found = value.strip()
    else:
        raise Refused("3.3", f"article {field} is an ISO date or datetime")
    if not found or len(found) > 50 or "\x00" in found:
        raise Refused("3.3", f"article {field} is an ISO date or datetime")
    return found


def _calendar_date(value: str, field: str) -> str:
    try:
        if "T" in value or " " in value:
            return datetime.fromisoformat(value).date().isoformat()
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise Refused("3.3", f"article {field} is not a complete ISO date or datetime") from exc


def _filename_date(source: str) -> str:
    match = DATE_NAME.match(Path(source).name)
    if match is None:
        raise Refused("3.3", "required article date is absent from metadata and filename")
    century = match.group("century") or "20"
    return f"{century}{match.group('year')}-{match.group('month')}-{match.group('day')}"


def _source_provenance(page: Mapping[str, Any], data: Mapping[str, Any]) -> dict[str, str]:
    raw = page["raw_bytes"]
    if not isinstance(raw, bytes):
        raise Refused("3.3", "article source bytes are unavailable")
    source = {
        "path": str(page["source"]),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "front_matter_yaml": _front_matter_yaml(str(page["raw_text"])),
    }
    image = data.get("image")
    if image is not None:
        if not isinstance(image, str):
            raise Refused("3.3", "article image is a string when present")
        source["image"] = image
    return source


def _front_matter_yaml(text: str) -> str:
    if text.startswith("---\r\n"):
        start = 5
    elif text.startswith("---\n"):
        start = 4
    else:
        raise Refused("3.2", "article front matter delimiters are malformed")
    closing = re.search(r"(?m)^---[ \t]*(?:\r?\n|$)", text[start:])
    if closing is None:
        raise Refused("3.2", "article front matter delimiters are malformed")
    value = text[start : start + closing.start()]
    return value.removesuffix("\r\n").removesuffix("\n")


def _extra_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise Refused("3.3", "extra is a mapping")
    return dict(value)


def _authored_extra(data: Mapping[str, Any]) -> dict[str, Any]:
    if "extra" not in data:
        return {}
    return _extra_mapping(data["extra"])


def _validate_replay(page: Mapping[str, Any], value: Any) -> None:
    if str(page["source"]) != str(page["target"]):
        raise Refused("3.3", f"reserved extra/{NAMESPACE} already exists on source input")
    if not isinstance(value, Mapping) or set(value) != {"source", "publication"}:
        raise Refused("3.3", f"reserved extra/{NAMESPACE} has an invalid shape")
    _validate_source(value["source"], str(page["source"]))
    _validate_publication(value["publication"])


def _validate_source(value: Any, current: str) -> None:
    if not isinstance(value, Mapping):
        raise Refused("3.3", f"reserved extra/{NAMESPACE}/source is a mapping")
    required = {"path", "sha256", "front_matter_yaml"}
    if set(value) not in (required, {*required, "image"}):
        raise Refused("3.3", f"reserved extra/{NAMESPACE}/source has an invalid shape")
    if not all(isinstance(value[key], str) for key in required):
        raise Refused("3.3", f"reserved extra/{NAMESPACE}/source fields are strings")
    if value["path"] == current or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"]):
        raise Refused("3.3", f"reserved extra/{NAMESPACE}/source is not replay provenance")
    if "image" in value and not isinstance(value["image"], str):
        raise Refused("3.3", f"reserved extra/{NAMESPACE}/source/image is a string")


def _validate_publication(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {"field", "value"}:
        raise Refused("3.3", f"reserved extra/{NAMESPACE}/publication has an invalid shape")
    if value["field"] not in {"date", "datepublished", "filename"}:
        raise Refused("3.3", f"reserved extra/{NAMESPACE}/publication field is invalid")
    if not isinstance(value["value"], str):
        raise Refused("3.3", f"reserved extra/{NAMESPACE}/publication value is a string")
    _calendar_date(value["value"], "publication value")


def _raw_pair(lines: list[str], start: int) -> tuple[list[str], int]:
    kept: list[str] = []
    index = start + 1
    while index < len(lines) and BLANK.fullmatch(lines[index]):
        kept.append(lines[index])
        index += 1
    if index >= len(lines):
        raise Refused("4.1", "a raw wrapper is opened and never closed")
    fence = _opening_fence(lines[index])
    if fence is None:
        raise Refused("4.1", "a raw wrapper contains prose instead of one fenced block")
    kept.append(lines[index])
    index = _copy_fence(lines, index + 1, fence, kept)
    while index < len(lines) and BLANK.fullmatch(lines[index]):
        kept.append(lines[index])
        index += 1
    if index >= len(lines) or _line_token(lines[index]) != RAW_CLOSE:
        raise Refused("4.1", "a raw wrapper contains prose, another fence, or no endraw")
    return kept, index + 1


def _copy_fence(lines: list[str], index: int, fence: tuple[str, int], kept: list[str]) -> int:
    while index < len(lines):
        kept.append(lines[index])
        if _is_close(lines[index], fence):
            return index + 1
        index += 1
    raise Refused("4.1", "the fenced block inside raw is opened and never closed")


def _opening_fence(line: str) -> tuple[str, int] | None:
    match = FENCE.fullmatch(line)
    if match is None:
        return None
    mark = match.group("mark")
    return mark[0], len(mark)


def _is_close(line: str, fence: tuple[str, int]) -> bool:
    mark, minimum = fence
    closing = re.compile(rf"^ {{0,3}}{re.escape(mark)}{{{minimum},}}[ \t]*(?:\r?\n)?$")
    return closing.fullmatch(line) is not None


def _line_token(line: str) -> str:
    return line.rstrip("\r\n").strip(" \t")


def _refuse_malformed_raw(line: str) -> None:
    if RAW_LIKE.search(line):
        raise Refused("4.1", "a raw wrapper token is malformed")
