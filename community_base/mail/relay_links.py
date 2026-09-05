from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from enum import Enum
from urllib.parse import quote, urlsplit

import requests
from requests.adapters import HTTPAdapter

from community_base.kernel.conf import get

TOKEN_PATTERN = re.compile(r"\A[A-Za-z0-9_-]{16,128}\Z")
TRANSPARENT_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)
UNSUBSCRIBE_SCOPES = ("client", "audience", "global")
_session_lock = threading.Lock()
_session: requests.Session | None = None
_session_key = ""


class BridgeOutcome(Enum):
    RECORDED = "recorded"
    REJECTED = "rejected"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True, slots=True)
class BridgeResult:
    outcome: BridgeOutcome
    status_code: int | None = None

    @property
    def answered(self) -> bool:
        return self.outcome in {
            BridgeOutcome.RECORDED,
            BridgeOutcome.REJECTED,
            BridgeOutcome.INVALID,
        }


def token_fingerprint(token: str) -> str:
    if not isinstance(token, str) or not token:
        return "absent"
    return hashlib.sha256(token.encode("utf-8", "replace")).hexdigest()[:12]


def is_well_formed_token(token: object) -> bool:
    return isinstance(token, str) and TOKEN_PATTERN.fullmatch(token) is not None


def is_safe_click_destination(destination: object) -> bool:
    if not isinstance(destination, str) or not destination or len(destination) > 2048:
        return False
    if any(character in destination for character in ("\r", "\n", "\t")):
        return False
    try:
        parsed = urlsplit(destination)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def bridge_base_url() -> str:
    configured = get("RELAY_BASE_URL").strip()
    if not configured:
        return ""
    parsed = urlsplit(configured)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        return ""
    return configured.rstrip("/")


def is_configured() -> bool:
    return bool(bridge_base_url())


def _pool() -> requests.Session:
    global _session, _session_key
    key = bridge_base_url()
    with _session_lock:
        if _session is None or _session_key != key:
            session = requests.Session()
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            session.trust_env = False
            _session = session
            _session_key = key
        return _session


def reset_pool() -> None:
    global _session, _session_key
    with _session_lock:
        if _session is not None:
            _session.close()
        _session = None
        _session_key = ""


def _call(
    method: str,
    path: str,
    *,
    timeout: float,
    params: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
) -> requests.Response | None:
    base = bridge_base_url()
    if not base:
        return None
    try:
        return _pool().request(
            method,
            f"{base}{path}",
            params=params,
            data=data,
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException:
        # Request exceptions can include the token-bearing URL. Never propagate them.
        return None


def _classify(response: requests.Response | None) -> BridgeResult:
    if response is None:
        return BridgeResult(BridgeOutcome.UNAVAILABLE)
    status = response.status_code
    if 200 <= status < 400:
        return BridgeResult(BridgeOutcome.RECORDED, status)
    if status == 404:
        return BridgeResult(BridgeOutcome.REJECTED, status)
    if status in {400, 405, 409, 410, 422}:
        return BridgeResult(BridgeOutcome.INVALID, status)
    return BridgeResult(BridgeOutcome.UNAVAILABLE, status)


def record_open(token: str) -> BridgeResult:
    if not is_configured():
        return BridgeResult(BridgeOutcome.NOT_CONFIGURED)
    if not is_well_formed_token(token):
        return BridgeResult(BridgeOutcome.REJECTED)
    return _classify(_call("GET", f"/t/o/{quote(token, safe='')}.gif", timeout=2.0))


def record_click(token: str, destination: str) -> BridgeResult:
    if not is_configured():
        return BridgeResult(BridgeOutcome.NOT_CONFIGURED)
    if not is_well_formed_token(token) or not is_safe_click_destination(destination):
        return BridgeResult(BridgeOutcome.INVALID)
    return _classify(
        _call(
            "GET",
            f"/t/c/{quote(token, safe='')}",
            params={"u": destination},
            timeout=3.0,
        )
    )


def load_unsubscribe(token: str) -> BridgeResult:
    if not is_configured():
        return BridgeResult(BridgeOutcome.NOT_CONFIGURED)
    if not is_well_formed_token(token):
        return BridgeResult(BridgeOutcome.REJECTED)
    return _classify(_call("GET", f"/unsubscribe/{quote(token, safe='')}", timeout=10.0))


def submit_unsubscribe(token: str, scope: str) -> BridgeResult:
    if not is_configured():
        return BridgeResult(BridgeOutcome.NOT_CONFIGURED)
    if not is_well_formed_token(token):
        return BridgeResult(BridgeOutcome.REJECTED)
    if scope not in UNSUBSCRIBE_SCOPES:
        return BridgeResult(BridgeOutcome.INVALID)
    return _classify(
        _call(
            "POST",
            f"/unsubscribe/{quote(token, safe='')}",
            data={"scope": scope},
            timeout=10.0,
        )
    )
