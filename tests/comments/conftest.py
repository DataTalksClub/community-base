import pytest

from community_base.comments import registry
from community_base.notifications import registry as notification_registry


@pytest.fixture(autouse=True)
def isolated_comment_targets():
    registry._clear()
    notification_registry._clear()
    yield
    registry._clear()
    notification_registry._clear()
