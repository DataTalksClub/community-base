from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from community_base.content_sync.convert.documents import PROFILES, convert_documents
from community_base.content_sync.convert.report import read_front_matter

PROFILE = PROFILES["dtc-articles"]


def write_article(root: Path, name: str, front: str, body: str = "Body.\n") -> tuple[Path, bytes]:
    path = root / "articles" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = f"---\n{front}---\n{body}".encode()
    path.write_bytes(raw)
    return path, raw


def converted(root: Path, slug: str) -> tuple[dict, str]:
    text = (root / "articles" / slug / "index.md").read_text()
    front, body = read_front_matter(text)
    assert front is not None
    return front, body


def assert_public_values(front: dict) -> None:
    assert front["summary"] == "Exact summary.  "
    assert front["date"] == "2024-03-10"
    assert front["subtitle"] == "Déjà vu"
    assert front["authors"] == ["zoe", "ada"]
    assert front["faq"] == [{"question": "Why?", "answer": "Because **Markdown**.\n"}]
    assert front["image"] == "../../images/posts/cafe/cover.png"
    assert front["extra"]["layout"] == "post"
    assert front["extra"]["datepublished"] == "2024-03-11"
    assert front["extra"]["math"] is True
    assert front["extra"]["retained"] == ["one", "two"]


def test_article_metadata_and_source_provenance_are_lossless(tmp_path):
    front_text = (
        "title: Café systems\nsubtitle: Déjà vu\ndescription: 'Exact summary.  '\n"
        "image: /images/posts/cafe/cover.png\nauthors: [zoe, ada]\n"
        "faq:\n  - question: Why?\n    answer: |\n      Because **Markdown**.\n"
        "date: 2024-03-10T23:30:00-07:00\ndatepublished: '2024-03-11'\n"
        "layout: post\nmath: true\nextra:\n  retained: [one, two]\n"
    )
    _, raw = write_article(tmp_path, "2024/24-03-10-cafe-systems.md", front_text)
    report = convert_documents(tmp_path, PROFILE)
    front, _ = converted(tmp_path, "cafe-systems")
    namespace = front["extra"]["dtc_article_v1"]
    assert report.ok and report.verify() == []
    assert_public_values(front)
    assert namespace == {
        "source": {
            "path": "articles/2024/24-03-10-cafe-systems.md",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "front_matter_yaml": front_text.rstrip("\n"),
            "image": "/images/posts/cafe/cover.png",
        },
        "publication": {"field": "date", "value": "2024-03-10T23:30:00-07:00"},
    }


@pytest.mark.parametrize(
    ("name", "front", "summary", "date", "field", "value"),
    [
        (
            "2021/21-01-01-mapped.md",
            "description:\n  Useful guide: with context\ndatepublished: '2021-02-03'\n",
            "Useful guide: with context",
            "2021-02-03",
            "datepublished",
            "2021-02-03",
        ),
        (
            "2022/22-07-09-from-name.md",
            "description: From the name\ndate: ''\ndatepublished: null\n",
            "From the name",
            "2022-07-09",
            "filename",
            "2022-07-09",
        ),
    ],
)
def test_description_normalization_and_publication_fallback(
    tmp_path, name, front, summary, date, field, value
):
    slug = Path(name).stem.split("-", 3)[-1]
    write_article(tmp_path, name, f"title: Article\n{front}")
    report = convert_documents(tmp_path, PROFILE)
    result, _ = converted(tmp_path, slug)
    assert report.ok
    assert result["summary"] == summary
    assert result["date"] == date
    assert result["extra"]["dtc_article_v1"]["publication"] == {
        "field": field,
        "value": value,
    }


@pytest.mark.parametrize(
    ("front", "message"),
    [
        ("description: [not, scalar]\n", "description"),
        ("description: null\n", "description"),
        ("description: {one: value, two: values}\n", "description"),
        ("description: {one: 2}\n", "description"),
        ("description: first\nsummary: second\n", "summary"),
        ("date: definitely-not-iso\n", "date"),
        ("date: '2024-02-30'\n", "date"),
        ("date: 3\n", "date"),
    ],
)
def test_malformed_description_or_publication_refuses_without_writing(tmp_path, front, message):
    path, raw = write_article(tmp_path, "2024/24-01-02-refused.md", f"title: Refused\n{front}")
    report = convert_documents(tmp_path, PROFILE)
    assert not report.ok and len(report.refusals) == 1
    assert message in report.refusals[0].message
    assert path.read_bytes() == raw
    assert not (tmp_path / "articles/refused/index.md").exists()


@pytest.mark.parametrize(
    "front",
    [
        "extra:\n  dtc_article_v1: {source: forged, publication: forged}\n",
        "extra:\n  dtc_article_v1: null\n",
        "layout: post\nextra:\n  layout: page\n",
        "math: true\nextra:\n  math: false\n",
        "extra: null\n",
    ],
)
def test_reserved_or_unequal_extra_collisions_refuse(tmp_path, front):
    path, raw = write_article(
        tmp_path,
        "2024/24-01-02-collision.md",
        f"title: Collision\ndescription: Safe\ndate: 2024-01-02\n{front}",
    )
    report = convert_documents(tmp_path, PROFILE)
    assert not report.ok and report.refusals[0].rule == "3.3"
    assert path.read_bytes() == raw
    assert not (tmp_path / "articles/collision/index.md").exists()


def test_equal_extra_collision_and_identity_survive_replay(tmp_path):
    identity = "41e5e796-1e9a-4444-b8d6-7b542fe35ca8"
    write_article(
        tmp_path,
        "2024/24-01-02-replay.md",
        f"content_id: {identity}\ntitle: Replay\ndescription: Safe\ndate: 2024-01-02\n"
        "layout: post\nextra:\n  layout: post\n",
    )
    first = convert_documents(tmp_path, PROFILE)
    before = (tmp_path / "articles/replay/index.md").read_bytes()
    front, _ = converted(tmp_path, "replay")
    source_sha = front["extra"]["dtc_article_v1"]["source"]["sha256"]
    second = convert_documents(tmp_path, PROFILE)
    assert first.ok and second.ok and second.converted == 0
    assert (tmp_path / "articles/replay/index.md").read_bytes() == before
    replayed, _ = converted(tmp_path, "replay")
    assert replayed["content_id"] == identity
    assert replayed["extra"]["dtc_article_v1"]["source"]["sha256"] == source_sha


def test_missing_identity_uses_the_existing_profile_target_namespace(tmp_path):
    write_article(
        tmp_path,
        "2024/24-01-02-identity.md",
        "title: Identity\ndescription: Safe\ndate: 2024-01-02\n",
    )
    report = convert_documents(tmp_path, PROFILE)
    front, _ = converted(tmp_path, "identity")
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, "datatalksclub:dtc-articles")
    assert report.ok
    assert front["content_id"] == str(uuid.uuid5(namespace, "articles/identity/index.md"))
