import re
from dataclasses import dataclass

SOURCE_KEY = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_sources = {}


@dataclass(frozen=True, slots=True)
class NotificationDraft:
    recipient_id: int
    title: str
    body: str = ""
    url: str = ""
    notification_type: str = "announcement"
    source_id: str = ""
    dedupe_key: str = ""


class NotificationSourceError(ValueError):
    pass


def register_notification_source(key, builder=None):
    if not isinstance(key, str) or not SOURCE_KEY.fullmatch(key):
        raise NotificationSourceError("invalid notification source key")

    def register(callback):
        if not callable(callback):
            raise NotificationSourceError("notification source builder must be callable")
        existing = _sources.get(key)
        if existing is not None and existing is not callback:
            raise NotificationSourceError(f"notification source is already registered: {key}")
        _sources[key] = callback
        return callback

    return register(builder) if builder is not None else register


def notification_source(key):
    try:
        return _sources[key]
    except KeyError as error:
        raise NotificationSourceError("notification source is not registered") from error


def registered_notification_sources():
    return tuple(sorted(_sources))


def _clear():
    _sources.clear()
