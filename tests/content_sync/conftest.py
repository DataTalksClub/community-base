import pytest

from community_base.content_sync import parsers


@pytest.fixture(autouse=True)
def isolated_parser_registry():
    parsers._clear()
    yield
    parsers._clear()
