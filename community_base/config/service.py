from __future__ import annotations

import logging
import os
import sys
import uuid
from typing import Any

from django.apps.registry import AppRegistryNotReady
from django.conf import settings
from django.core.cache import cache
from django.core.cache.backends.base import InvalidCacheBackendError
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, transaction

from community_base.config.crypto import decrypt, encrypt
from community_base.config.models import Setting, SettingChange
from community_base.config.registry import Definition, definition, definitions
from community_base.kernel.redaction import REDACTED, mask_sensitive_spans

STAMP_KEY = "community_base.config.stamp"
_DEFAULT_SENTINEL = object()
logger = logging.getLogger(__name__)
_RUNTIME_READ_ERRORS = (AppRegistryNotReady, DatabaseError)
_STAMP_ERRORS = (InvalidCacheBackendError, ImproperlyConfigured, DatabaseError)


def running_in_worker_process() -> bool:
    return os.environ.get("DJANGO_QCLUSTER_PROCESS") == "true" or "qcluster" in sys.argv


class RuntimeConfig:
    def __init__(self, *, stamp_store=cache):
        self.stamp_store = stamp_store
        self._values: dict[str, Any] = {}
        self._stamp = None
        self._populated = False

    def reset(self) -> None:
        self._values = {}
        self._stamp = None
        self._populated = False

    def publish(self) -> None:
        self.reset()
        try:
            self.stamp_store.set(STAMP_KEY, uuid.uuid4().hex, timeout=None)
        except _STAMP_ERRORS:
            logger.warning("Unable to publish the runtime configuration stamp", exc_info=True)

    def value(self, key: str, default=_DEFAULT_SENTINEL):
        item = definition(key)
        if running_in_worker_process():
            try:
                row = Setting.objects.filter(key=key).first()
            except _RUNTIME_READ_ERRORS:
                return _fallback(item, default)
            return _stored_value(item, row) if row is not None else _fallback(item, default)
        try:
            current_stamp = self.stamp_store.get(STAMP_KEY)
        except _STAMP_ERRORS:
            current_stamp = None
        if not self._populated or current_stamp != self._stamp:
            try:
                self._values = {
                    row.key: _stored_value(definition(row.key), row)
                    for row in Setting.objects.filter(key__in=[item.key for item in definitions()])
                }
            except _RUNTIME_READ_ERRORS:
                self._values = {}
            self._stamp = current_stamp
            self._populated = True
        return self._values[key] if key in self._values else _fallback(item, default)


runtime = RuntimeConfig()


def _stored_value(item: Definition, row: Setting):
    raw = decrypt(row.value) if item.secret else row.value
    return item.coerce(raw)


def _fallback(item: Definition, default=_DEFAULT_SENTINEL):
    if item.env_var and item.env_var in os.environ:
        return item.coerce(os.environ[item.env_var])
    if item.django_settings_fallback:
        value = getattr(settings, item.django_settings_fallback, _DEFAULT_SENTINEL)
        if value is not _DEFAULT_SENTINEL:
            return item.coerce(value)
    return item.coerce(item.default if default is _DEFAULT_SENTINEL else default)


def get(key: str, default=None):
    return runtime.value(key, _DEFAULT_SENTINEL if default is None else default)


def is_enabled(key: str) -> bool:
    value = get(key)
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "1", "yes"}


def resolved_source(key: str) -> str:
    item = definition(key)
    try:
        if Setting.objects.filter(key=key).exists():
            return "db"
    except _RUNTIME_READ_ERRORS:
        pass
    if item.env_var and item.env_var in os.environ:
        return "environment"
    if item.django_settings_fallback and hasattr(settings, item.django_settings_fallback):
        return "django_settings"
    return "default"


def describe(key: str) -> dict[str, Any]:
    item = definition(key)
    source = resolved_source(key)
    return {
        "key": item.key,
        "group": item.group,
        "label": item.label,
        "description": item.description,
        "value_type": item.value_type,
        "value": REDACTED if item.secret else runtime.value(key),
        "configured": source != "default",
        "source": source,
        "secret": item.secret,
        "multiline": item.multiline,
        "optional": item.optional,
        "is_email": item.is_email,
        "docs_url": item.docs_url,
    }


def set(key: str, value, actor_ref: str, reason: str = "", *, source: str = "studio") -> Setting:
    item = definition(key)
    normalized = item.coerce(value)
    stored = encrypt(normalized) if item.secret else normalized
    with transaction.atomic():
        previous = Setting.objects.filter(key=key).first()
        row, _ = Setting.objects.update_or_create(
            key=key,
            defaults={"value": stored, "value_type": item.value_type, "source": source},
        )
        redacted = item.secret
        SettingChange.objects.create(
            setting_key=key,
            old_value=REDACTED if redacted and previous else previous.value if previous else None,
            old_value_redacted=redacted and previous is not None,
            new_value=REDACTED if redacted else normalized,
            new_value_redacted=redacted,
            actor_ref=mask_sensitive_spans(str(actor_ref)),
            reason=mask_sensitive_spans(
                str(reason),
                canaries=(str(normalized),) if item.secret else (),
            ),
        )
        runtime.reset()
        transaction.on_commit(runtime.publish)
    return row


def export() -> dict[str, Any]:
    return {
        item.key: REDACTED if item.secret else runtime.value(item.key) for item in definitions()
    }


def import_(payload: dict[str, Any], actor_ref: str, *, reason: str = "Imported") -> list[Setting]:
    if not isinstance(payload, dict):
        raise ValueError("Configuration import must be an object.")
    with transaction.atomic():
        return [
            set(key, value, actor_ref, reason, source="import")
            for key, value in payload.items()
            if value != REDACTED
        ]
