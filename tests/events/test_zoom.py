from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import requests

from community_base.events.integrations import zoom
from community_base.events.integrations.zoom import (
    ZoomAmbiguousError,
    ZoomClient,
    ZoomConfigurationError,
    ZoomDisabled,
    ZoomTemporaryError,
    meeting_request_for_event,
)
from community_base.events.models import Event


class Response:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self.data = data

    def json(self):
        return self.data


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def _call(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url, **kwargs):
        return self._call("post", url, **kwargs)

    def patch(self, url, **kwargs):
        return self._call("patch", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._call("delete", url, **kwargs)


@pytest.fixture
def configured(monkeypatch):
    values = {
        "ZOOM_ENABLED": True,
        "ZOOM_ACCOUNT_ID": "account-id",
        "ZOOM_CLIENT_ID": "client-id",
        "ZOOM_CLIENT_SECRET": "super-secret",
        "ZOOM_API_BASE_URL": "https://api.zoom.test/v2",
        "ZOOM_OAUTH_URL": "https://zoom.test/oauth/token",
        "ZOOM_HTTP_TIMEOUT": 7,
        "ZOOM_AUTO_RECORDING": "cloud",
        "ZOOM_JOIN_BEFORE_HOST": False,
        "ZOOM_WAITING_ROOM": False,
    }
    monkeypatch.setattr(zoom, "get_config", values.get)
    return values


def request():
    return zoom.ZoomMeetingRequest(
        topic="Office hours",
        start_time=datetime(2026, 4, 1, 18, tzinfo=ZoneInfo("Europe/Berlin")),
        duration_minutes=60,
        timezone="Europe/Berlin",
    )


def test_zoom_create_uses_bounded_oauth_and_returns_safe_result(configured):
    session = Session(
        Response(200, {"access_token": "provider-token"}),
        Response(
            201,
            {
                "id": 123456,
                "join_url": "https://zoom.test/j/123456",
                "start_url": "https://zoom.test/host-secret",
            },
        ),
    )

    result = ZoomClient(session=session).create_meeting(request())

    assert result.meeting_id == "123456"
    assert result.join_url == "https://zoom.test/j/123456"
    assert not hasattr(result, "start_url")
    oauth = session.calls[0]
    create = session.calls[1]
    assert oauth[2]["auth"] == ("client-id", "super-secret")
    assert oauth[2]["timeout"] == 7
    assert create[2]["headers"] == {"Authorization": "Bearer provider-token"}
    assert create[2]["timeout"] == 7
    assert create[2]["json"]["timezone"] == "Europe/Berlin"


def test_zoom_disabled_fails_without_an_http_call(monkeypatch):
    monkeypatch.setattr(zoom, "get_config", lambda key: False if key == "ZOOM_ENABLED" else "")
    session = Session()

    with pytest.raises(ZoomDisabled):
        ZoomClient(session=session).create_meeting(request())
    assert session.calls == []


def test_oauth_timeout_is_retryable_but_create_timeout_is_ambiguous(configured):
    with pytest.raises(ZoomTemporaryError) as oauth_error:
        ZoomClient(session=Session(requests.Timeout())).create_meeting(request())
    assert oauth_error.value.retryable is True

    session = Session(Response(200, {"access_token": "token"}), requests.Timeout())
    with pytest.raises(ZoomAmbiguousError) as create_error:
        ZoomClient(session=session).create_meeting(request())
    assert create_error.value.retryable is False
    assert create_error.value.ambiguous is True


def test_provider_error_does_not_retain_secrets_or_urls(configured):
    session = Session(
        Response(200, {"access_token": "token"}),
        Response(
            500,
            {"message": "access_token=secret at https://zoom.test/private"},
        ),
    )

    with pytest.raises(ZoomAmbiguousError) as captured:
        ZoomClient(session=session).create_meeting(request())

    message = str(captured.value)
    assert "secret" not in message
    assert "zoom.test" not in message
    assert not hasattr(captured.value, "response")


def test_zoom_rejects_unsafe_endpoints_and_unbounded_timeouts(configured):
    configured["ZOOM_API_BASE_URL"] = "http://api.zoom.test/v2"
    with pytest.raises(ZoomConfigurationError, match="HTTPS"):
        ZoomClient(session=Session(Response(200, {"access_token": "token"}))).create_meeting(
            request()
        )

    configured["ZOOM_API_BASE_URL"] = "https://api.zoom.test/v2"
    configured["ZOOM_HTTP_TIMEOUT"] = 0
    with pytest.raises(ZoomConfigurationError, match="between 1 and 60"):
        ZoomClient(session=Session()).create_meeting(request())


def test_event_request_preserves_local_timezone_and_duration(monkeypatch):
    item = Event(
        title="Office hours",
        slug="office-hours",
        start_datetime=datetime(2026, 4, 1, 16, tzinfo=ZoneInfo("UTC")),
        end_datetime=datetime(2026, 4, 1, 17, 30, tzinfo=ZoneInfo("UTC")),
        timezone="Europe/Berlin",
    )

    values = {
        "ZOOM_AUTO_RECORDING": "local",
        "ZOOM_JOIN_BEFORE_HOST": True,
        "ZOOM_WAITING_ROOM": True,
    }
    monkeypatch.setattr(zoom, "get_config", values.get)
    result = meeting_request_for_event(item)

    assert result.start_time.hour == 18
    assert result.duration_minutes == 90
    assert result.timezone == "Europe/Berlin"
    assert result.auto_recording == "local"
    assert result.join_before_host is True
    assert result.waiting_room is True
