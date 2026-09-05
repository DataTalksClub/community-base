import pytest

from community_base.kernel.context import context_scope
from community_base.kernel.services import ServiceContext


def test_service_context_captures_current_ids_and_hides_idempotency_key():
    with context_scope(request_id="request-1", correlation_id="correlation-1", job_id="job-1"):
        context = ServiceContext.from_current(actor_ref="user:42", idempotency_key="command-1")

    assert context.request_id == "request-1"
    assert context.correlation_id == "correlation-1"
    assert context.job_id == "job-1"
    assert "command-1" not in repr(context)


def test_service_context_rejects_pii_actor_reference():
    with pytest.raises(ValueError, match="Invalid actor_ref"):
        ServiceContext(correlation_id="correlation-1", actor_ref="user:person@example.com")
