import pytest

from community_base.notifications import registry


@pytest.fixture(autouse=True)
def isolated_notification_sources():
    registry._clear()
    yield
    registry._clear()
