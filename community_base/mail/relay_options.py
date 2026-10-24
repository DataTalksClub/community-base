"""Translate validated durable recipient options to Relay's native contract."""

from __future__ import annotations


def recipient_options(options):
    from community_base.mail.relay import RelayMailError

    options = options or {}
    result = {}
    reply_to = options.get("reply_to") or []
    # Relay currently accepts one address, while the durable API allows a list
    # for SES. Refuse multiple addresses rather than silently lose recipients.
    if len(reply_to) > 1:
        raise RelayMailError("unsupported_relay_reply_to_count")
    if reply_to:
        result["reply_to"] = reply_to[0]
    for name in ("cc", "bcc"):
        values = options.get(name)
        if values:
            result[name] = list(values)
    return result
