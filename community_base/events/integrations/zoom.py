from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from community_base.config import get as get_config
from community_base.kernel.redaction import mask_sensitive_spans


class ZoomError(RuntimeError):
    code = "zoom_error"
    retryable = False
    ambiguous = False


class ZoomDisabled(ZoomError):
    code = "zoom_disabled"


class ZoomConfigurationError(ZoomError):
    code = "zoom_not_configured"


class ZoomTemporaryError(ZoomError):
    code = "zoom_temporarily_unavailable"
    retryable = True


class ZoomAmbiguousError(ZoomError):
    code = "zoom_outcome_ambiguous"
    ambiguous = True


class ZoomRejected(ZoomError):
    code = "zoom_request_rejected"


@dataclass(frozen=True, slots=True)
class ZoomMeetingRequest:
    topic: str
    start_time: datetime
    duration_minutes: int
    timezone: str
    auto_recording: str = "cloud"
    join_before_host: bool = False
    waiting_room: bool = False


@dataclass(frozen=True, slots=True)
class ZoomMeetingResult:
    meeting_id: str
    join_url: str


def meeting_request_for_event(event):
    duration = max(
        1, int((event.effective_end_datetime - event.start_datetime).total_seconds() / 60)
    )
    zone_name = (event.timezone or "UTC").strip()
    try:
        local_start = event.start_datetime.astimezone(ZoneInfo(zone_name))
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ZoomConfigurationError("Event timezone is invalid.") from error
    auto_recording = get_config("ZOOM_AUTO_RECORDING")
    if auto_recording not in {"cloud", "local", "none"}:
        raise ZoomConfigurationError("Zoom auto recording mode is invalid.")
    return ZoomMeetingRequest(
        topic=event.title,
        start_time=local_start,
        duration_minutes=duration,
        timezone=zone_name,
        auto_recording=auto_recording,
        join_before_host=get_config("ZOOM_JOIN_BEFORE_HOST"),
        waiting_room=get_config("ZOOM_WAITING_ROOM"),
    )


class ZoomClient:
    def __init__(self, *, session=None):
        self.session = session or requests.Session()

    def create_meeting(self, request):
        token = self._access_token()
        payload = {
            "topic": request.topic,
            "type": 2,
            "start_time": request.start_time.strftime("%Y-%m-%dT%H:%M:%S"),
            "duration": request.duration_minutes,
            "timezone": request.timezone,
            "settings": {
                "auto_recording": request.auto_recording,
                "join_before_host": request.join_before_host,
                "mute_upon_entry": True,
                "waiting_room": request.waiting_room,
            },
        }
        response = self._provider_request(
            "post",
            urljoin(self._api_base_url(), "users/me/meetings"),
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            ambiguous_on_transport=True,
        )
        data = self._json_object(response)
        meeting_id = data.get("id")
        join_url = data.get("join_url")
        if not isinstance(meeting_id, int | str) or not isinstance(join_url, str):
            raise ZoomAmbiguousError("Zoom returned an incomplete meeting result.")
        return ZoomMeetingResult(str(meeting_id), join_url)

    def update_meeting(self, meeting_id, request):
        token = self._access_token()
        payload = {
            "topic": request.topic,
            "start_time": request.start_time.strftime("%Y-%m-%dT%H:%M:%S"),
            "duration": request.duration_minutes,
            "timezone": request.timezone,
        }
        self._provider_request(
            "patch",
            urljoin(self._api_base_url(), f"meetings/{meeting_id}"),
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            ambiguous_on_transport=True,
        )

    def delete_meeting(self, meeting_id):
        token = self._access_token()
        self._provider_request(
            "delete",
            urljoin(self._api_base_url(), f"meetings/{meeting_id}"),
            headers={"Authorization": f"Bearer {token}"},
            ambiguous_on_transport=True,
        )

    def _access_token(self):
        if not get_config("ZOOM_ENABLED"):
            raise ZoomDisabled("Zoom integration is disabled.")
        account_id = get_config("ZOOM_ACCOUNT_ID")
        client_id = get_config("ZOOM_CLIENT_ID")
        client_secret = get_config("ZOOM_CLIENT_SECRET")
        if not all((account_id, client_id, client_secret)):
            raise ZoomConfigurationError("Zoom credentials are incomplete.")
        response = self._provider_request(
            "post",
            self._oauth_url(),
            params={"grant_type": "account_credentials", "account_id": account_id},
            auth=(client_id, client_secret),
            ambiguous_on_transport=False,
        )
        token = self._json_object(response).get("access_token")
        if not isinstance(token, str) or not token:
            raise ZoomTemporaryError("Zoom OAuth returned no access token.")
        return token

    def _provider_request(self, method, url, *, ambiguous_on_transport, **kwargs):
        kwargs["timeout"] = self._timeout()
        try:
            response = getattr(self.session, method)(url, **kwargs)
        except (requests.Timeout, requests.ConnectionError) as error:
            exception = ZoomAmbiguousError if ambiguous_on_transport else ZoomTemporaryError
            raise exception("Zoom request did not return a definite outcome.") from error
        if 200 <= response.status_code < 300:
            return response
        if response.status_code == 429 and not ambiguous_on_transport:
            raise ZoomTemporaryError("Zoom temporarily rejected authentication.")
        message = self._safe_provider_message(response)
        if response.status_code >= 500:
            exception = ZoomAmbiguousError if ambiguous_on_transport else ZoomTemporaryError
            raise exception(message)
        raise ZoomRejected(message)

    @staticmethod
    def _json_object(response):
        try:
            data = response.json()
        except (TypeError, ValueError) as error:
            raise ZoomTemporaryError("Zoom returned an invalid response.") from error
        if not isinstance(data, dict):
            raise ZoomTemporaryError("Zoom returned an invalid response.")
        return data

    @staticmethod
    def _safe_provider_message(response):
        try:
            data = response.json()
        except (TypeError, ValueError):
            return "Zoom request failed."
        raw = data.get("message") if isinstance(data, dict) else None
        if not isinstance(raw, str):
            return "Zoom request failed."
        safe = mask_sensitive_spans(raw)[:300]
        return safe if safe and "[REDACTED]" not in safe else "Zoom request failed."

    @staticmethod
    def _timeout():
        value = get_config("ZOOM_HTTP_TIMEOUT")
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 60:
            raise ZoomConfigurationError("Zoom timeout must be between 1 and 60 seconds.")
        return value

    @staticmethod
    def _api_base_url():
        return _validated_https_url(get_config("ZOOM_API_BASE_URL"), trailing_slash=True)

    @staticmethod
    def _oauth_url():
        return _validated_https_url(get_config("ZOOM_OAUTH_URL"), trailing_slash=False)


def _validated_https_url(value, *, trailing_slash):
    parsed = urlparse(str(value))
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ZoomConfigurationError("Zoom endpoint must be an HTTPS URL without credentials.")
    normalized = str(value).rstrip("/")
    return f"{normalized}/" if trailing_slash else normalized
