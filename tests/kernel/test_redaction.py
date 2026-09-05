import json

from community_base.kernel.redaction import CYCLE, REDACTED, TRUNCATED, RedactionPolicy, redact


def test_redaction_normalizes_sensitive_keys_and_protects_canaries():
    canary = "provider-secret-canary"
    original_safe = {"note": f"prefix {canary} suffix", "count": 2}
    original = {
        "Authorization-Header": "Bearer token",
        "aws_secret.ACCESS-key": "secret",
        "safe": original_safe,
    }

    redacted = redact(original, canaries=(canary,))

    assert redacted["Authorization-Header"] == REDACTED
    assert redacted["aws_secret.ACCESS-key"] == REDACTED
    assert redacted["safe"]["note"] == REDACTED
    assert original_safe["note"] == f"prefix {canary} suffix"
    assert canary not in json.dumps(redacted)


def test_redaction_is_bounded_and_cycle_safe():
    cyclic = []
    cyclic.append(cyclic)
    value = {"cycle": cyclic, "items": [1, 2, 3], "long": "x" * 10}

    redacted = redact(
        value,
        policy=RedactionPolicy(
            max_depth=2,
            max_container_items=2,
            max_total_nodes=20,
            max_string_length=4,
        ),
    )

    assert CYCLE in repr(redacted)
    assert TRUNCATED in repr(redacted)
