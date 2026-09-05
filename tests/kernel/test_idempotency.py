import pytest

from community_base.kernel.idempotency import (
    UnsafeJsonValue,
    canonical_json_bytes,
    hash_idempotency_key,
    hash_idempotency_request,
)


def test_hashes_are_canonical_and_fenced_by_scope():
    assert canonical_json_bytes({"a": 1, "b": 2}) == canonical_json_bytes({"b": 2, "a": 1})
    assert hash_idempotency_key("tests.one", "same-key") != hash_idempotency_key(
        "tests.two", "same-key"
    )
    assert hash_idempotency_request("tests.one", {"a": 1}) == hash_idempotency_request(
        "tests.one", {"a": 1}
    )


def test_canonical_json_is_bounded():
    with pytest.raises(UnsafeJsonValue):
        canonical_json_bytes({"value": float("nan")})
