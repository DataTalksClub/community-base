import pytest

from community_base.voting.registry import _clear


@pytest.fixture(autouse=True)
def clear_voting_targets():
    _clear()
    yield
    _clear()
