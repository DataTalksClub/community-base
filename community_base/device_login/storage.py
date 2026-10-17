"""Atomic owner-only JSON credential writes (0600 file, 0700 directory)."""

from __future__ import annotations

import json
import os
from pathlib import Path


def save_private_json(path: str | Path, payload: dict) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    return target


def read_private_json(path: str | Path) -> dict:
    target = Path(path).expanduser()
    raw = target.read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Credential profile is invalid.")
    return payload
