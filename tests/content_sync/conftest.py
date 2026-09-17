import pytest

from community_base.content_sync import parsers
from community_base.content_sync.kinds import registry


@pytest.fixture(autouse=True)
def isolated_parser_registry():
    parsers._clear()
    yield
    parsers._clear()


@pytest.fixture(autouse=True)
def isolated_kind_registry():
    """The package kinds, and only those, around every test in this app."""

    registry._reset()
    yield
    registry._reset()
