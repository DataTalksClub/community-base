import pytest

from community_base.comments import registry


@pytest.fixture(autouse=True)
def isolated_comment_targets():
    registry._clear()
    yield
    registry._clear()
