import os

import pytest

from community_base.content_sync.checkout import CheckoutError, ImmutableCheckout


def test_checkout_snapshots_regular_files(tmp_path):
    (tmp_path / "content").mkdir()
    source_file = tmp_path / "content" / "one.md"
    source_file.write_text("one")

    with ImmutableCheckout(tmp_path) as checkout:
        source_file.write_text("changed outside")
        assert checkout.files() == (type(checkout.files()[0])("content/one.md"),)
        assert checkout.read_text("content/one.md") == "one"


def test_checkout_rejects_symlinks(tmp_path):
    outside = tmp_path.parent / "outside-content.txt"
    outside.write_text("secret")
    os.symlink(outside, tmp_path / "linked.md")

    with pytest.raises(CheckoutError, match="Symlink"):
        with ImmutableCheckout(tmp_path):
            pass


def test_checkout_enforces_file_limit(tmp_path):
    (tmp_path / "one.md").write_text("one")
    (tmp_path / "two.md").write_text("two")

    with pytest.raises(CheckoutError, match="max_files=1"):
        with ImmutableCheckout(tmp_path, max_files=1):
            pass
