"""Both mail backends enforce the same template-key boundary."""

import pytest

from community_base.jobs.runner import PermanentJobError
from community_base.mail.backends.ses_local import TEMPLATE_KEY_PATTERN as SES_TEMPLATE_KEY_PATTERN
from community_base.mail.backends.ses_local import _load_template_source
from community_base.mail.relay import TEMPLATE_KEY_PATTERN as RELAY_TEMPLATE_KEY_PATTERN
from community_base.mail.relay import RelayMailClient
from community_base.mail.template_keys import TEMPLATE_KEY_PATTERN
from community_base.testing import FakeRelay, FakeResponse


def test_existing_pattern_imports_reexport_shared_contract():
    assert SES_TEMPLATE_KEY_PATTERN is TEMPLATE_KEY_PATTERN
    assert RELAY_TEMPLATE_KEY_PATTERN is TEMPLATE_KEY_PATTERN


@pytest.mark.parametrize(
    "key",
    ["../secret", "folder/name", "folder\\name", ".hidden", "a/../secret", "x" * 129, ""],
)
def test_unsafe_key_is_rejected_before_loader_or_relay_request(settings, key):
    loaded = []
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "MAIL_TEMPLATE_OVERRIDE_LOADER": lambda value: loaded.append(value),
    }
    with pytest.raises(PermanentJobError, match="invalid_mail_template_key"):
        _load_template_source(key)
    assert loaded == []

    transport = FakeRelay()
    client = RelayMailClient("https://relay.example.test", "test-key", transport=transport)
    with pytest.raises(ValueError, match="invalid template key"):
        client.template_versions(key)
    assert transport.calls == []


@pytest.mark.parametrize(
    "key", ["welcome_message", "welcome-message", "coursework.review_assigned"]
)
def test_valid_keys_keep_original_spelling_with_override_and_relay(settings, key):
    loaded = []

    def override(value):
        loaded.append(value)
        return "Subject", "Body"

    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "MAIL_TEMPLATE_OVERRIDE_LOADER": override,
    }
    assert _load_template_source(key) == ("Subject", "Body", "")
    assert loaded == [key]

    transport = FakeRelay()
    client = RelayMailClient("https://relay.example.test", "test-key", transport=transport)
    transport.next_response = FakeResponse(200, {"versions": []})
    client.template_versions(key)
    assert transport.calls[0][1].endswith(f"/templates/{key}/versions")
