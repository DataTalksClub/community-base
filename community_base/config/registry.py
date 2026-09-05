from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email

VALUE_TYPES = frozenset({"str", "int", "bool", "json", "list"})


@dataclass(frozen=True, slots=True)
class Definition:
    key: str
    group: str
    label: str
    description: str
    value_type: str
    default: Any
    secret: bool = False
    multiline: bool = False
    optional: bool = False
    is_email: bool = False
    django_settings_fallback: str | None = None
    env_var: str | None = None
    docs_url: str | None = None

    def coerce(self, value: Any) -> Any:
        if self.value_type == "str":
            normalized = value if isinstance(value, str) else str(value)
        elif self.value_type == "int":
            if isinstance(value, bool):
                raise ValidationError("Boolean values are not integers.")
            try:
                normalized = int(value)
            except (TypeError, ValueError) as error:
                raise ValidationError("Value must be an integer.") from error
        elif self.value_type == "bool":
            if isinstance(value, bool):
                normalized = value
            elif isinstance(value, str) and value.strip().casefold() in {"true", "1", "yes"}:
                normalized = True
            elif isinstance(value, str) and value.strip().casefold() in {"false", "0", "no"}:
                normalized = False
            else:
                raise ValidationError("Value must be a boolean.")
        elif self.value_type == "json":
            normalized = _json_value(value)
        elif self.value_type == "list":
            normalized = _list_value(value)
        else:
            raise ImproperlyConfigured(f"Unsupported config value type: {self.value_type}")
        if self.is_email and normalized:
            validate_email(normalized)
        return normalized


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise ValidationError("Value must be valid JSON.") from error
    try:
        json.dumps(value)
    except (TypeError, ValueError) as error:
        raise ValidationError("Value must be JSON serializable.") from error
    return value


def _list_value(value: Any) -> list:
    normalized = _json_value(value)
    if not isinstance(normalized, list):
        raise ValidationError("Value must be a list.")
    return normalized


_definitions: dict[str, Definition] = {}


def declare(
    *,
    key: str,
    group: str,
    label: str,
    description: str,
    value_type: str,
    default: Any,
    secret: bool = False,
    multiline: bool = False,
    optional: bool = False,
    is_email: bool = False,
    django_settings_fallback: bool | str = False,
    env_var: str | None = None,
    docs_url: str | None = None,
) -> Definition:
    if value_type not in VALUE_TYPES:
        raise ImproperlyConfigured(f"Unsupported config value type: {value_type}")
    fallback = key if django_settings_fallback is True else django_settings_fallback or None
    definition = Definition(
        key=key,
        group=group,
        label=label,
        description=description,
        value_type=value_type,
        default=default,
        secret=secret,
        multiline=multiline,
        optional=optional,
        is_email=is_email,
        django_settings_fallback=fallback,
        env_var=env_var or key,
        docs_url=docs_url,
    )
    definition.coerce(default)
    existing = _definitions.get(key)
    if existing is not None and existing != definition:
        raise ImproperlyConfigured(f"Conflicting config declaration: {key}")
    _definitions[key] = definition
    return definition


def definition(key: str) -> Definition:
    try:
        return _definitions[key]
    except KeyError as error:
        raise ImproperlyConfigured(f"Unknown configuration key: {key}") from error


def definitions() -> tuple[Definition, ...]:
    return tuple(sorted(_definitions.values(), key=lambda item: (item.group, item.key)))


def groups() -> dict[str, tuple[Definition, ...]]:
    result: dict[str, list[Definition]] = {}
    for item in definitions():
        result.setdefault(item.group, []).append(item)
    return {name: tuple(items) for name, items in result.items()}
