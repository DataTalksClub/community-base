import pytest

from community_base.kernel.context import ContextIdError, context_scope, current_context


def test_context_scope_nests_and_resets():
    with context_scope(request_id="outer", correlation_id="correlation-1"):
        with context_scope(request_id="inner", job_id="job-1"):
            assert current_context().request_id == "inner"
            assert current_context().job_id == "job-1"
        assert current_context().request_id == "outer"
        assert current_context().correlation_id == "correlation-1"

    assert current_context().request_id is None


def test_context_validation_does_not_echo_rejected_value():
    rejected = "secret value with spaces"

    with pytest.raises(ContextIdError) as error:
        with context_scope(request_id=rejected):
            pass

    assert rejected not in str(error.value)
