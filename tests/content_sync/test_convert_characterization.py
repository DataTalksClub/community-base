"""Observable contracts retained when the document converter is extracted.

Synthetic repositories exercise public orchestration, not private helpers.
DTC article corrections have separate tests; these expectations remain generic.
"""

from pathlib import Path

import pytest
import yaml

from community_base.content_sync.convert import documents
from community_base.content_sync.convert.documents import (
    PROFILES,
    Collection,
    Profile,
    convert_documents,
    main,
)

IDENTITY = "4538306c-3922-4c6e-8873-2f8da61a9d06"
PERSON = Profile(
    name="characterization-person",
    collections=(
        Collection(
            kind="person",
            source="_people",
            target="people",
            rename={"bio": "summary", "picture": "image"},
            drop=("layout",),
            link_keys={"github": "github"},
            assets={"images/authors": "people/images"},
        ),
    ),
)
PERSON_FILES = {
    "_people/ada.md": f"---\ncontent_id: {IDENTITY}\ntitle: Ada\nbio: Café 🧭\n"
    "picture: /images/authors/ada.png\ngithub: synthetic\nlayout: old\n"
    "extra:\n  retained: true\nunknown:\n  ordered: [b, a]\n---\nBody.\n",
    "images/authors/ada.png": b"synthetic image bytes",
    "notes.txt": "untouched bytes\n",
}


def write_files(root: Path, files: dict[str, str | bytes]) -> None:
    for name, value in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, bytes):
            path.write_bytes(value)
        else:
            path.write_text(value, encoding="utf-8")


def snapshot(root: Path) -> dict[str, bytes]:
    found = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


def decoded(root: Path, name: str) -> tuple[dict, str]:
    text = (root / name).read_text(encoding="utf-8")
    _, front, body = text.split("---", 2)
    return yaml.safe_load(front), body.lstrip("\n")


def test_generic_metadata_identity_assets_and_report_are_retained(tmp_path):
    write_files(tmp_path, PERSON_FILES)
    report = convert_documents(tmp_path, PERSON)
    front, body = decoded(tmp_path, "people/ada.md")
    assert report.ok and report.verify() == []
    assert (len(report.before), len(report.after)) == (3, 4)
    assert front == {
        "content_id": IDENTITY,
        "title": "Ada",
        "summary": "Café 🧭",
        "image": "images/ada.png",
        "links": [{"label": "github", "url": "https://github.com/synthetic"}],
        "extra": {"retained": True, "unknown": {"ordered": ["b", "a"]}},
    }
    assert body == "Body.\n"
    assert (tmp_path / "people/images/ada.png").read_bytes() == b"synthetic image bytes"
    assert (tmp_path / "notes.txt").read_bytes() == b"untouched bytes\n"
    changes = {row.path: row for row in report.changes}
    assert changes["_people/ada.md"].target == "people/ada.md"
    assert "dropped layout: 'old'" in changes["_people/ada.md"].details
    assert "unknown -> extra" in changes["_people/ada.md"].details
    before = snapshot(tmp_path)
    replay = convert_documents(tmp_path, PERSON)
    assert replay.ok and replay.converted == 0
    assert snapshot(tmp_path) == before


def test_page_rename_conflict_keeps_authored_target_and_accounts_old_key(tmp_path):
    write_files(
        tmp_path,
        {
            "_people/ada.md": f"---\ncontent_id: {IDENTITY}\ntitle: Ada\n"
            "bio: Original biography\nsummary: Authored summary\n"
            "extra:\n  retained: true\n---\nBody.\n",
        },
    )
    report = convert_documents(tmp_path, PERSON)
    front, body = decoded(tmp_path, "people/ada.md")
    assert report.ok and report.verify() == []
    assert front == {
        "content_id": IDENTITY,
        "title": "Ada",
        "summary": "Authored summary",
        "extra": {"retained": True, "bio": "Original biography"},
    }
    assert body == "Body.\n"


def test_body_rewrites_prose_but_preserves_fenced_and_inline_code(tmp_path):
    code = "```python\n{{ untouched }}\n[[Missing]] {: .code } ~~code~~\n```\n"
    source = (
        "---\ntitle: Alpha\nrelated: [beta]\n---\n# ALPHA\n\n"
        'Styled {: .wide }\n{: .block }\n<span style="color:red">~~gone~~</span>\n'
        "[[Beta]] and `{{ literal }}`.\n"
        + code
        + '{% include youtube.html video_id="synthetic" %}\n'
    )
    write_files(
        tmp_path, {"_wiki/alpha.md": source, "_wiki/beta.md": "---\ntitle: Beta\n---\nOther.\n"}
    )
    report = convert_documents(tmp_path, PROFILES["aisl-wiki"])
    front, body = decoded(tmp_path, "wiki/alpha.md")
    assert report.ok
    assert front["related"] == ["wiki:beta"]
    assert body == (
        "Styled\n<span><del>gone</del></span>\n"
        "[Beta](wiki:beta) and `{{ literal }}`.\n"
        + code
        + "```embed\ntype: youtube\nid: synthetic\n```"
    )
    assert snapshot(tmp_path)["wiki/alpha.md"].count(code.encode()) == 1


@pytest.mark.parametrize(
    "bad",
    ["{% include unknown.html %}", "```python\nunclosed", "[[Nobody]]"],
    ids=["unknown-liquid", "unclosed-fence", "missing-wikilink"],
)
def test_refused_file_is_byte_identical_while_valid_peer_is_accounted(tmp_path, bad):
    source = "---\ntitle: Refused\n---\n" + bad + "\n"
    write_files(
        tmp_path,
        {"_wiki/refused.md": source, "_wiki/accepted.md": "---\ntitle: Accepted\n---\nBody.\n"},
    )
    report = convert_documents(tmp_path, PROFILES["aisl-wiki"])
    assert not report.ok
    assert len(report.refusals) == 1
    assert report.refusals[0].path == "_wiki/refused.md"
    assert (tmp_path / "_wiki/refused.md").read_bytes() == source.encode()
    assert (tmp_path / "wiki/accepted.md").is_file()
    assert not (tmp_path / "wiki/refused.md").exists()
    assert report.verify() == []
    assert len(report.before) == 2 and len(report.after) == 3


def test_dry_run_proposes_actions_without_mutating_input_or_identity(tmp_path):
    source = f"---\ncontent_id: {IDENTITY}\ntitle: Dry\n---\nBody.\n"
    write_files(tmp_path, {"_wiki/dry.md": source})
    before = snapshot(tmp_path)
    report = convert_documents(tmp_path, PROFILES["aisl-wiki"], apply=False)
    assert len(before) == 1
    assert snapshot(tmp_path) == before
    assert report.before == report.after
    assert report.converted == 2
    assert [(row.path, row.action, row.target) for row in report.changes] == [
        ("_wiki/dry.md", "renamed", "wiki/dry.md"),
        ("content.yaml", "created", ""),
    ]
    convert_documents(tmp_path, PROFILES["aisl-wiki"])
    assert decoded(tmp_path, "wiki/dry.md")[0]["content_id"] == IDENTITY


def test_workshop_yaml_projection_keeps_opaque_page_and_manifest_order(tmp_path):
    name = "2026/session/workshop.yaml"
    write_files(
        tmp_path,
        {
            name: "title: Workshop\ninstructor_name: Synthetic\nbyline: Previously present\n"
            "cover_image_url: https://example.invalid/cover.png\nlanding_required_level: 0\n"
            "unknown: [second, first]\nextra:\n  retained: true\n",
            "2026/session/notes.md": "Opaque page without front matter\n",
        },
    )
    report = convert_documents(tmp_path, PROFILES["aisl-workshops"])
    front = yaml.safe_load((tmp_path / name).read_text())
    assert report.ok
    assert front == {
        "title": "Workshop",
        "image": "https://example.invalid/cover.png",
        "landing_required_level": 0,
        "byline": "Synthetic",
        "extra": {"retained": True, "unknown": ["second", "first"]},
    }
    assert list(front) == ["title", "image", "extra", "byline", "landing_required_level"]
    assert (
        tmp_path / "2026/session/notes.md"
    ).read_bytes() == b"Opaque page without front matter\n"
    before = snapshot(tmp_path)
    assert convert_documents(tmp_path, PROFILES["aisl-workshops"]).converted == 0
    assert snapshot(tmp_path) == before


def test_faq_remains_opaque_even_when_bytes_are_not_parseable_yaml(tmp_path):
    raw = b"---\n[malformed\n---\n{% unknown %}\n\xff"
    write_files(tmp_path, {"_questions/nested/question.md": raw})
    report = convert_documents(tmp_path, PROFILES["faq"])
    assert report.ok
    assert (tmp_path / "faq/nested/question.md").read_bytes() == raw
    assert not (tmp_path / "_questions/nested/question.md").exists()
    assert report.before["_questions/nested/question.md"] == report.after["faq/nested/question.md"]
    assert report.converted == 2


def test_public_cli_and_facade_preserve_report_and_replay_contract(tmp_path, capsys):
    write_files(tmp_path, {"_wiki/cli.md": "---\ntitle: CLI\n---\nBody.\n"})
    assert documents.Collection is Collection and documents.Profile is Profile
    assert documents.convert_documents is convert_documents and documents.main is main
    assert main([str(tmp_path), "--profile", "aisl-wiki"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("# conversion report: aisl-wiki\n")
    assert "files before: 1" in output and "files after:  2" in output
    assert "renamed" in output and "_wiki/cli.md -> wiki/cli.md" in output
    front, _ = decoded(tmp_path, "wiki/cli.md")
    assert front["content_id"] == "ad27efd8-819f-5a3c-bd8f-819d4273bf42"
    before = snapshot(tmp_path)
    assert main([str(tmp_path), "--profile", "aisl-wiki", "--dry-run"]) == 0
    assert snapshot(tmp_path) == before
    assert "| renamed | 0 |" in capsys.readouterr().out
