from __future__ import annotations

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

PREFIX = "fernet:v1:"


def _fernet() -> Fernet:
    digest = hashlib.sha256(f"community-base-config:{settings.SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value) -> str:
    serialized = json.dumps(value, separators=(",", ":"))
    return f"{PREFIX}{_fernet().encrypt(serialized.encode()).decode()}"


def decrypt(ciphertext: str):
    if not isinstance(ciphertext, str) or not ciphertext.startswith(PREFIX):
        raise ImproperlyConfigured("Stored configuration secret is not encrypted.")
    try:
        serialized = _fernet().decrypt(ciphertext[len(PREFIX) :].encode()).decode()
    except InvalidToken as error:
        raise ImproperlyConfigured("Stored configuration secret cannot be decrypted.") from error
    return json.loads(serialized)
