"""Code generation, normalization and hashing for the device flow.

User codes are 8 symbols from a vowel-free alphabet, shown as XXXX-XXXX.
Rejection sampling avoids modulo bias. Both codes are stored as SHA-256
hex digests only; the plaintext user code is returned once at creation
and the device code is returned once to the polling CLI.
"""

from __future__ import annotations

import hashlib
import re
import secrets

ALPHABET = "BCDFGHJKMNPQRSTWXZ23456789"  # no vowels, no L/V, no 0/1 (canonical dakit spec)
CODE_LENGTH = 8
DEVICE_CODE_PREFIX = "cbdl_"
LABEL_MAX_LENGTH = 80

# Separators ignored when parsing user codes (spaces, hyphens/dashes, dots, underscores).
SEPARATORS_RE = re.compile(r"[\s\-‐-―−._]")


def generate_user_code() -> str:
    symbols = []
    while len(symbols) < CODE_LENGTH:
        candidate = secrets.choice(ALPHABET)
        symbols.append(candidate)
    return f"{''.join(symbols[:4])}-{''.join(symbols[4:])}"


def normalize_user_code(value: str | None) -> str | None:
    """Compact to the 8-symbol form, or None when invalid. Never truncates."""
    if not value:
        return None
    cleaned = SEPARATORS_RE.sub("", value).upper()
    if len(cleaned) != CODE_LENGTH:
        return None
    if any(ch not in ALPHABET for ch in cleaned):
        return None
    return cleaned


def format_user_code(compact: str) -> str:
    return f"{compact[:4]}-{compact[4:]}"


def is_valid_user_code(value: str | None) -> bool:
    return normalize_user_code(value) is not None


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_device_code() -> str:
    return f"{DEVICE_CODE_PREFIX}{secrets.token_urlsafe(32)}"


def sanitize_label(value: str | None, *, default: str = "CLI") -> str:
    """Strip control characters, collapse whitespace, cap at 80 chars."""
    cleaned = "".join(ch if ch.isprintable() else " " for ch in (value or ""))
    collapsed = " ".join(cleaned.split())
    return (collapsed or default)[:LABEL_MAX_LENGTH]
