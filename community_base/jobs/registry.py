from __future__ import annotations

import json
import math
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JobPayload = dict[str, JsonValue]
type JobHandler = Callable[[JobContext, JobPayload], None]

HANDLER_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
SCHEDULE_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
PAYLOAD_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
MAX_PAYLOAD_BYTES = 32_768
MAX_PAYLOAD_DEPTH = 8
MAX_PAYLOAD_ITEMS = 256
MAX_STRING_LENGTH = 4_096
_SENSITIVE_FRAGMENTS = (
    "apikey",
    "authorization",
    "body",
    "cookie",
    "credential",
    "email",
    "password",
    "privatekey",
    "secret",
    "token",
)
_OPAQUE_SUFFIXES = frozenset({"id", "ids", "uuid", "uuids"})
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_AUTH_RE = re.compile(r"(?i)^\s*(bearer|basic)\s+\S+")
_JWT_RE = re.compile(r"^[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}$")
_CREDENTIAL_RE = re.compile(r"^(AKIA|ASIA|gh[pousr]_|github_pat_)[A-Za-z0-9_-]+$")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


class RegistryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class JobContext:
    job_id: uuid.UUID
    correlation_id: str | None
    attempt: int
    worker_id: str
    lease_token: uuid.UUID


@dataclass(frozen=True, slots=True)
class HandlerDefinition:
    name: str
    callback: JobHandler
    chunked: bool = False


@dataclass(frozen=True, slots=True)
class ScheduleDefinition:
    name: str
    handler: str
    cron: str
    payload: JobPayload


_handlers: dict[str, HandlerDefinition] = {}
_schedules: dict[str, ScheduleDefinition] = {}


def register_handler(name: str, *, chunked: bool = False):
    if not isinstance(name, str) or not HANDLER_PATTERN.fullmatch(name):
        raise RegistryError("invalid durable job handler name")

    def decorator(callback: JobHandler) -> JobHandler:
        declared = HandlerDefinition(name=name, callback=callback, chunked=chunked)
        existing = _handlers.get(name)
        if existing is not None and existing != declared:
            raise RegistryError(f"durable job handler is already registered: {name}")
        _handlers[name] = declared
        return callback

    return decorator


def handler_definition(name: str) -> HandlerDefinition:
    try:
        return _handlers[name]
    except KeyError as error:
        raise RegistryError("durable job handler is not registered") from error


def get_handler(name: str) -> JobHandler:
    return handler_definition(name).callback


def registered_handler_names() -> tuple[str, ...]:
    return tuple(sorted(_handlers))


def schedule(handler: str, cron: str, payload: Mapping[str, object], name: str | None = None):
    handler_definition(handler)
    schedule_name = name or handler
    if not SCHEDULE_PATTERN.fullmatch(schedule_name):
        raise RegistryError("invalid schedule name")
    if not isinstance(cron, str) or len(cron.split()) != 5:
        raise RegistryError("cron schedule must contain five fields")
    declared = ScheduleDefinition(
        name=schedule_name,
        handler=handler,
        cron=cron,
        payload=validate_payload(payload),
    )
    existing = _schedules.get(schedule_name)
    if existing is not None and existing != declared:
        raise RegistryError(f"schedule is already registered: {schedule_name}")
    _schedules[schedule_name] = declared
    return declared


def registered_schedules() -> tuple[ScheduleDefinition, ...]:
    return tuple(_schedules[name] for name in sorted(_schedules))


def validate_payload(payload: Mapping[str, object]) -> JobPayload:
    if not isinstance(payload, Mapping):
        raise RegistryError("durable job payload must be an object")
    normalized = _validate_mapping(payload, depth=0, counter=[0])
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode()) > MAX_PAYLOAD_BYTES:
        raise RegistryError("durable job payload is too large")
    return normalized


def _validate_mapping(value: Mapping[str, object], *, depth: int, counter: list[int]) -> JobPayload:
    if depth > MAX_PAYLOAD_DEPTH:
        raise RegistryError("durable job payload is too deeply nested")
    result: JobPayload = {}
    for key, item in value.items():
        counter[0] += 1
        if counter[0] > MAX_PAYLOAD_ITEMS:
            raise RegistryError("durable job payload has too many items")
        if not isinstance(key, str) or not PAYLOAD_KEY_PATTERN.fullmatch(key):
            raise RegistryError("durable job payload contains an invalid key")
        words = tuple(
            part for part in re.split(r"[^a-z0-9]+", _CAMEL_RE.sub("_", key).casefold()) if part
        )
        protected = any(fragment in "".join(words) for fragment in _SENSITIVE_FRAGMENTS)
        if protected and not _safe_opaque_identifier(words, item):
            raise RegistryError("durable job payload contains a protected field")
        result[key] = _validate_value(item, depth=depth + 1, counter=counter)
    return result


def _safe_opaque_identifier(words: tuple[str, ...], value: object) -> bool:
    if not words or words[-1] not in _OPAQUE_SUFFIXES:
        return False
    values = (
        value if words[-1] in {"ids", "uuids"} and isinstance(value, list | tuple) else (value,)
    )
    return bool(values) and all(_opaque_id(item) for item in values)


def _opaque_id(value: object) -> bool:
    if isinstance(value, int) and not isinstance(value, bool):
        return value >= 0
    if not isinstance(value, str):
        return False
    if value.isdigit() and len(value) <= 20:
        return True
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return value in {str(parsed), parsed.hex}


def _validate_value(value: Any, *, depth: int, counter: list[int]) -> JsonValue:
    if depth > MAX_PAYLOAD_DEPTH:
        raise RegistryError("durable job payload is too deeply nested")
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RegistryError("durable job payload contains a non-finite number")
        return value
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise RegistryError("durable job payload contains an oversized string")
        if (
            "://" in value
            or _EMAIL_RE.fullmatch(value)
            or _AUTH_RE.match(value)
            or _JWT_RE.fullmatch(value)
            or _CREDENTIAL_RE.fullmatch(value)
        ):
            raise RegistryError("durable job payload contains a protected value")
        return value
    if isinstance(value, Mapping):
        return _validate_mapping(value, depth=depth, counter=counter)
    if isinstance(value, list | tuple):
        result: list[JsonValue] = []
        for item in value:
            counter[0] += 1
            if counter[0] > MAX_PAYLOAD_ITEMS:
                raise RegistryError("durable job payload has too many items")
            result.append(_validate_value(item, depth=depth + 1, counter=counter))
        return result
    raise RegistryError("durable job payload must contain only JSON values")
