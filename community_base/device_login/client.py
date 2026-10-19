"""Shared CLI device-login loop (requests-based).

The CLI starts a grant, prints the verification URL and the user code
(the device code is never printed), then polls until the browser approves,
denies, or the code expires. Site CLIs wrap this loop and store the
returned credential with `storage.save_private_json`.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import requests


class DeviceLoginError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def device_login(
    base_url: str,
    *,
    label: str = "CLI",
    timeout: float = 600,
    printer: Callable[[str], None] | None = None,
    opener: Callable[[str], None] | None = None,
    session: requests.Session | None = None,
) -> dict:
    base = base_url.rstrip("/")
    http = session or requests.Session()
    say = printer or print
    try:
        response = http.post(f"{base}/api/auth/device", json={"label": label}, timeout=30)
    except requests.RequestException as error:
        raise DeviceLoginError("invalid_request", f"Cannot reach {base}: {error}") from error
    if response.status_code != 200:
        raise DeviceLoginError("invalid_response", f"Login start failed: {response.text[:200]}")
    try:
        offer = response.json()
    except ValueError as error:
        raise DeviceLoginError("invalid_response", "Login start returned invalid JSON.") from error
    for field in ("device_code", "user_code", "verification_uri"):
        if not offer.get(field):
            raise DeviceLoginError("invalid_response", "Login start returned an invalid offer.")
    device_code = offer["device_code"]
    user_code = offer["user_code"]
    url = offer.get("verification_uri_complete") or offer["verification_uri"]
    expires_in = offer.get("expires_in", 600) or 600
    interval = max(float(offer.get("interval", 5) or 5), 1.0)
    minutes = max(int(round(expires_in / 60)), 1)

    say("")
    say(f"  Confirm this code:  {user_code}")
    say(f"    Open in a browser:  {url}")
    say("    Open that link on a machine you trust and sign in as usual.")
    say(f"    Waiting for confirmation (the code is valid for {minutes} minute(s))...")
    say("")
    if opener is not None:
        try:
            opener(url)
        except Exception:
            pass

    deadline = time.monotonic() + max(timeout, expires_in + 15)
    wait = interval
    while True:
        if time.monotonic() >= deadline:
            raise DeviceLoginError("timeout", "Timed out waiting for browser approval.")
        time.sleep(wait)
        try:
            poll = http.post(
                f"{base}/api/auth/device/token",
                json={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                },
                timeout=30,
            )
        except requests.RequestException:
            continue
        if poll.status_code == 200:
            try:
                credential = poll.json()
            except ValueError as error:
                raise DeviceLoginError(
                    "invalid_response", "Login completed with an invalid response."
                ) from error
            if "error" in credential or "token" not in credential:
                raise DeviceLoginError(
                    "invalid_response", "Login completed with an invalid response."
                )
            return credential
        try:
            error_code = poll.json().get("error", "")
        except ValueError:
            continue
        if error_code == "authorization_pending":
            continue
        if error_code == "slow_down" or poll.status_code == 429:
            wait = min(wait + 5, 60)
            continue
        if error_code == "access_denied":
            raise DeviceLoginError("access_denied", "The login was denied in the browser.")
        if error_code == "expired_token":
            raise DeviceLoginError("expired_token", "The code expired. Run login again.")
        raise DeviceLoginError("invalid_response", f"Login failed: {poll.text[:200]}")
