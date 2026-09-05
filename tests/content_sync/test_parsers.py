import pytest

from community_base.content_sync.parsers import SourceItem, get_parser, parsers, register_parser


class FixtureParser:
    def discover(self, checkout, source):
        return [SourceItem("one", "one.md", {"title": "One"})]

    def upsert(self, item, source, media):
        return item

    def soft_delete_missing(self, seen_keys, source):
        return 0


def test_parser_registration_is_ordered_and_resolvable():
    first = FixtureParser()
    second = FixtureParser()

    register_parser("articles", first)
    register_parser("events", second)

    assert parsers() == (("articles", first), ("events", second))
    assert get_parser("events") is second


def test_duplicate_parser_is_rejected():
    register_parser("articles", FixtureParser())

    with pytest.raises(ValueError, match="already registered"):
        register_parser("articles", FixtureParser())


def test_parser_protocol_is_validated_at_registration():
    with pytest.raises(TypeError, match="discover"):
        register_parser("broken", object())
