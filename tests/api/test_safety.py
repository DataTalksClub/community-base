import pytest
from django.test import RequestFactory

from community_base.api.errors import APIError
from community_base.api.safety import parse_pagination, read_json_object, refuse_delete


def test_read_json_object_rejects_non_object_body():
    request = RequestFactory().post("/", data="[]", content_type="application/json")

    with pytest.raises(APIError) as raised:
        read_json_object(request)

    assert raised.value.code == "invalid_type"


def test_read_json_object_rejects_oversized_body():
    request = RequestFactory().post("/", data="{}", content_type="application/json")

    with pytest.raises(APIError) as raised:
        read_json_object(request, max_bytes=1)

    assert raised.value.status == 413


def test_parse_pagination_enforces_bounds():
    request = RequestFactory().get("/?limit=101&offset=0")

    with pytest.raises(APIError) as raised:
        parse_pagination(request)

    assert raised.value.code == "invalid_pagination"


def test_delete_policy_uses_resource_specific_code():
    with pytest.raises(APIError) as raised:
        refuse_delete(resource="canonical_event")

    assert raised.value.status == 405
    assert raised.value.code == "canonical_event_delete_not_available"
