from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from community_base.mail.context import register_context_resolver, resolve_delivery_context


def test_registered_resolver_enriches_worker_context_without_mutating_stored_data():
    callback = Mock(side_effect=lambda **kwargs: {**kwargs["context"], "link": "resolved"})
    register_context_resolver("maintenance_test.", callback)
    delivery = SimpleNamespace(purpose="maintenance_test.verify")
    stored = {"token_ref": "opaque"}

    result = resolve_delivery_context(delivery=delivery, context=stored)

    assert result == {"token_ref": "opaque", "link": "resolved"}
    assert stored == {"token_ref": "opaque"}
    callback.assert_called_once_with(delivery=delivery, context=stored)


def test_context_resolver_prefers_the_most_specific_prefix():
    register_context_resolver("maintenance_specific.", lambda **kwargs: {"selected": "broad"})
    register_context_resolver(
        "maintenance_specific.account.", lambda **kwargs: {"selected": "account"}
    )

    result = resolve_delivery_context(
        delivery=SimpleNamespace(purpose="maintenance_specific.account.reset"),
        context={},
    )

    assert result == {"selected": "account"}


def test_unknown_purpose_preserves_context_and_invalid_prefix_is_rejected():
    stored = {"value": "unchanged"}
    assert (
        resolve_delivery_context(
            delivery=SimpleNamespace(purpose="unregistered_maintenance_purpose"),
            context=stored,
        )
        == stored
    )
    with pytest.raises(ValueError, match="must end with a dot"):
        register_context_resolver("invalid", lambda **kwargs: {})
