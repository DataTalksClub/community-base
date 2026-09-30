"""A dry-run flag does not change the shared report constructor contract."""

from community_base.content_sync.convert.report import ConversionReport


def test_positional_before_inventory_remains_the_second_argument():
    before = {"course.yaml": "digest"}

    report = ConversionReport("example", before)

    assert report.before == before
    assert report.applied is True
