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


def _dot_directory_tree(root):
    (root / "README.md").write_text("readme")
    (root / ".agents" / "skills").mkdir(parents=True)
    (root / ".agents" / "skills" / "skill.md").write_text("skill")
    (root / ".claude").mkdir()
    os.symlink("../.agents/skills", root / ".claude" / "skills")
    os.symlink("../README.md", root / ".claude" / "x.md")
    os.symlink("/etc/hostname", root / ".agents" / "link")
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text("on: push")
    os.symlink("workflows", root / ".github" / "y")


def test_checkout_skips_symlinks_inside_top_level_dot_directories(tmp_path):
    _dot_directory_tree(tmp_path)

    with ImmutableCheckout(tmp_path) as checkout:
        files = {path.as_posix() for path in checkout.files()}
        assert files == {
            "README.md",
            ".agents/skills/skill.md",
            ".github/workflows/ci.yml",
        }
        assert checkout.skipped_links == (
            ".agents/link",
            ".claude/skills",
            ".claude/x.md",
            ".github/y",
        )
        assert checkout.read_text(".github/workflows/ci.yml") == "on: push"
        for refused in (".claude/skills/skill.md", ".claude/x.md", ".claude/skills"):
            with pytest.raises(CheckoutError):
                checkout.read_bytes(refused)
        assert not (checkout.root / ".claude" / "skills").exists()
        assert not (checkout.root / ".claude" / "x.md").exists()


def test_skipped_links_do_not_count_toward_max_files(tmp_path):
    (tmp_path / "one.md").write_text("one")
    (tmp_path / ".claude").mkdir()
    for index in range(5):
        os.symlink("../one.md", tmp_path / ".claude" / f"link{index}.md")

    with ImmutableCheckout(tmp_path, max_files=1) as checkout:
        assert [path.as_posix() for path in checkout.files()] == ["one.md"]
        assert len(checkout.skipped_links) == 5


@pytest.mark.parametrize(
    ("link", "target"),
    [
        ("docs/a.md", "/etc/hostname"),
        ("images/x.png", "../x.png"),
        ("link", "."),
        ("faq/.hidden/link", "../../README.md"),
        (".claude", ".agents"),
    ],
)
def test_checkout_still_refuses_symlinks_outside_dot_directories(tmp_path, link, target):
    (tmp_path / "README.md").write_text("readme")
    (tmp_path / "x.png").write_bytes(b"png")
    (tmp_path / ".agents").mkdir()
    path = tmp_path / link
    path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, path)

    with pytest.raises(CheckoutError, match=f"Symlink is not allowed: {link}"):
        with ImmutableCheckout(tmp_path):
            pass
