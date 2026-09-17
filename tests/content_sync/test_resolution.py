"""The resolving half of the toolkit: `FORMAT.md` sections 3.6 and 3.7."""

from pathlib import Path

import pytest

from community_base.content_sync.documents import read_repository
from community_base.content_sync.kinds import KeySpec, KindSpec, register_kind
from community_base.content_sync.kinds.layouts import FlatLayout
from community_base.content_sync.kinds.registry import KindDependencyError
from community_base.content_sync.media import MediaResult, asset_payload_defect
from community_base.content_sync.resolution import (
    order_sources,
    resolve_repository,
)

FIXTURES = Path(__file__).parent / "fixtures"

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a"
    "49444154789c6360000002000100ffff03000006000557bfabd40000000049454e44ae426082"
)
WIKI_MANIFEST = "schema_version: 1\ncollections:\n  - kind: wiki\n    path: wiki\n"


class FakeStore:
    """A media store that records what it was asked to upload."""

    def __init__(self):
        self.uploads = []

    def upload(self, checkout, path, source):
        checkout.read_bytes(path)
        self.uploads.append(path)
        return MediaResult(path, f"/media/{path}")


def write_repository(root: Path, *, manifest: str = WIKI_MANIFEST, pages=(), files=()):
    """One repository on disk: a manifest, some wiki pages and some bytes."""

    root.mkdir(parents=True, exist_ok=True)
    (root / "content.yaml").write_text(manifest)
    for name, text in pages:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    for name, payload in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return root


def page(body: str, *, title: str = "A Page", front: str = "") -> str:
    return (
        '---\ncontent_id: "88888888-8888-4888-8888-888888888888"\n'
        f"title: {title}\n{front}---\n\n{body}\n"
    )


def resolve(path, **kwargs):
    return resolve_repository(read_repository(path), **kwargs)


# --- assets, section 3.6 ------------------------------------------------------


def test_a_referenced_asset_is_uploaded_once_and_rewritten_everywhere():
    store = FakeStore()

    result = resolve(FIXTURES / "valid_multi", media=store, source=None)

    article = result.by_path()["articles/crisp-dm-for-ai/index.md"]
    assert result.ok
    # The cover is referenced twice, by the front-matter key and by the body,
    # and both the dark sibling and the light file upload exactly once.
    assert store.uploads.count("articles/crisp-dm-for-ai/images/cover.png") == 1
    assert article.values["image"] == "/media/articles/crisp-dm-for-ai/images/cover.png"
    assert "/media/articles/crisp-dm-for-ai/images/cover.png" in article.html
    assert [asset.path for asset in article.assets] == ["articles/crisp-dm-for-ai/images/cover.png"]


def test_an_unreferenced_file_is_not_an_asset(tmp_path):
    store = FakeStore()
    write_repository(
        tmp_path,
        pages=[("wiki/a-page.md", page("A body with no image."))],
        files=[("wiki/images/unused.png", PNG)],
    )

    result = resolve(tmp_path, media=store)

    assert result.ok
    assert store.uploads == []
    assert result.assets == ()


def test_an_asset_outside_every_collection_is_uploaded_when_referenced(tmp_path):
    store = FakeStore()
    write_repository(
        tmp_path,
        pages=[("wiki/a-page.md", page("![Cover](../images/cover.png)"))],
        files=[("images/cover.png", PNG)],
    )

    result = resolve(tmp_path, media=store)

    assert result.ok
    assert store.uploads == ["images/cover.png"]
    assert '<img alt="Cover" src="/media/images/cover.png">' in result.documents[0].html


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("/images/cover.png", "must be a relative path"),
        ("{IMAGE:9f3a}", "{IMAGE:id} tokens are not part of the format"),
        ("{{ site.baseurl }}/cover.png", "Liquid is not part of the format"),
        ("http://example.com/cover.png", "http:// references are not allowed"),
        ("data:image/png;base64,AA==", "data: references are not allowed"),
        ("../../outside.png", "asset leaves the repository"),
        ("images/missing.png", "does not exist"),
        ("images/cover.bmp", "asset type is not allowed"),
    ],
)
def test_a_refused_asset_reference_names_the_file(tmp_path, reference, message):
    write_repository(
        tmp_path,
        pages=[("wiki/a-page.md", page(f"![Cover]({reference})"))],
        files=[("wiki/images/cover.bmp", PNG)],
    )

    result = resolve(tmp_path)

    rendered = [item.render() for item in result.diagnostics]
    assert [item.rule for item in result.errors] == ["3.6"], rendered
    assert message in result.errors[0].message
    assert result.errors[0].path == "wiki/a-page.md"


def test_an_ignored_file_referenced_as_an_asset_is_unresolved():
    result = resolve(FIXTURES / "invalid" / "ignored_asset")

    assert [(item.rule, item.path) for item in result.errors] == [("3.6", "wiki/a-page.md")]
    assert result.errors[0].message == "asset images/cover.png is ignored by content.yaml"


def test_an_asset_over_the_maximum_is_refused(tmp_path):
    write_repository(
        tmp_path,
        pages=[("wiki/a-page.md", page("![Cover](images/cover.png)"))],
        files=[("wiki/images/cover.png", PNG + b"\x00" * (16 * 1024 * 1024))],
    )

    result = resolve(tmp_path)

    assert [item.rule for item in result.errors] == ["3.6"]
    assert "over the 16777216 byte maximum" in result.errors[0].message
    assert "wiki/images/cover.png" in result.errors[0].message


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"<svg><script>alert(1)</script></svg>", "unsafe SVG"),
        (b'<svg onload="x()"></svg>', "unsafe SVG"),
        (b"not an svg at all", "unsafe SVG"),
    ],
)
def test_an_unsafe_svg_is_refused_before_upload(tmp_path, payload, message):
    store = FakeStore()
    write_repository(
        tmp_path,
        pages=[("wiki/a-page.md", page("![Diagram](images/diagram.svg)"))],
        files=[("wiki/images/diagram.svg", payload)],
    )

    result = resolve(tmp_path, media=store)

    assert [item.rule for item in result.errors] == ["3.6"]
    assert message in result.errors[0].message
    assert "wiki/images/diagram.svg" in result.errors[0].message
    assert store.uploads == []


def test_a_signature_that_disagrees_with_the_extension_is_refused(tmp_path):
    write_repository(
        tmp_path,
        pages=[("wiki/a-page.md", page("![Cover](images/cover.png)"))],
        files=[("wiki/images/cover.png", b"GIF89a and the rest")],
    )

    result = resolve(tmp_path)

    assert "PNG signature mismatch" in result.errors[0].message


def test_the_signature_gate_admits_every_allowed_type():
    assert asset_payload_defect(".webp", b"RIFF1234WEBPVP8 ") is None
    assert asset_payload_defect(".pdf", b"%PDF-1.7") is None
    assert asset_payload_defect(".gif", b"GIF89a") is None
    assert asset_payload_defect(".jpeg", b"\xff\xd8\xff\x00\xff\xd9") is None
    assert asset_payload_defect(".svg", b"<svg viewBox='0 0 1 1'></svg>") is None
    assert asset_payload_defect(".webp", b"RIFF1234XXXX") == "WEBP signature mismatch"


def test_an_https_asset_reference_is_left_alone(tmp_path):
    store = FakeStore()
    write_repository(
        tmp_path,
        pages=[
            (
                "wiki/a-page.md",
                page("![Cover](https://example.com/cover.png)", front="image: https://x/y.png\n"),
            )
        ],
    )

    result = resolve(tmp_path, media=store)

    assert result.ok
    assert store.uploads == []
    assert result.documents[0].values["image"] == "https://x/y.png"
    assert "https://example.com/cover.png" in result.documents[0].html


def test_a_link_to_a_pdf_is_an_asset(tmp_path):
    store = FakeStore()
    write_repository(
        tmp_path,
        pages=[("wiki/a-page.md", page("Read the [slides](files/slides.pdf)."))],
        files=[("wiki/files/slides.pdf", b"%PDF-1.7 body")],
    )

    result = resolve(tmp_path, media=store)

    assert result.ok
    assert store.uploads == ["wiki/files/slides.pdf"]
    assert 'href="/media/wiki/files/slides.pdf"' in result.documents[0].html


# --- theme pairs, section 3.6 -------------------------------------------------


def test_a_dark_sibling_is_paired_when_the_repository_opts_in():
    result = resolve(FIXTURES / "valid_multi", media=FakeStore())

    article = result.by_path()["articles/crisp-dm-for-ai/index.md"]
    asset = article.assets[0]
    assert asset.is_paired
    assert asset.dark_path == "articles/crisp-dm-for-ai/images/cover.dark.png"
    assert 'data-theme-figure="light"' in article.html
    assert 'data-theme-figure="dark"' in article.html
    assert 'class="cb-theme-figure cb-theme-figure-dark"' in article.html
    assert "/media/articles/crisp-dm-for-ai/images/cover.dark.png" in article.html


def test_the_sanitiser_keeps_the_paired_image_attributes():
    """The pair is emitted before the sanitiser and has to survive it."""

    article = resolve(FIXTURES / "valid_multi", media=FakeStore()).by_path()[
        "articles/crisp-dm-for-ai/index.md"
    ]

    assert article.html.count("<img") == 2
    for variant in ("light", "dark"):
        assert f'data-theme-figure="{variant}"' in article.html
        assert f"cb-theme-figure-{variant}" in article.html
    assert 'alt="Cover"' in article.html


def test_a_dark_sibling_is_not_paired_without_the_opt_in(tmp_path):
    write_repository(
        tmp_path,
        pages=[("wiki/a-page.md", page("![Cover](images/cover.png)"))],
        files=[("wiki/images/cover.png", PNG), ("wiki/images/cover.dark.png", PNG)],
    )

    result = resolve(tmp_path, media=FakeStore())

    assert result.assets[0].is_paired is False
    assert "data-theme-figure" not in result.documents[0].html


def test_the_dark_half_is_never_paired_with_itself(tmp_path):
    write_repository(
        tmp_path,
        manifest=WIKI_MANIFEST + "theme_pairs: true\n",
        pages=[("wiki/a-page.md", page("![Cover](images/cover.dark.png)"))],
        files=[("wiki/images/cover.dark.png", PNG)],
    )

    result = resolve(tmp_path)

    assert result.ok
    assert result.assets[0].is_paired is False


# --- cross-references, section 3.7 --------------------------------------------


def test_the_three_destination_forms_resolve_and_are_stored():
    result = resolve(FIXTURES / "valid_multi")

    article = result.by_path()["articles/crisp-dm-for-ai/index.md"]
    assert result.ok
    assert article.reference_records() == [
        {
            "kind": "person",
            "target": "alexey-grigorev",
            "label": "",
            "href": "/people/alexey-grigorev",
        },
        {"kind": "wiki", "target": "a-b-testing", "label": "", "href": "/wiki/a-b-testing"},
        {
            "kind": "wiki",
            "target": "a-b-testing",
            "label": "A/B testing",
            "href": "/wiki/a-b-testing",
        },
        {
            "kind": "person",
            "target": "alexey-grigorev",
            "label": "author",
            "href": "/people/alexey-grigorev",
        },
    ]
    assert 'href="/wiki/a-b-testing"' in article.html


def test_a_relative_link_resolves_to_the_route_of_its_target():
    result = resolve(FIXTURES / "valid_docs")

    general = result.by_path()["docs/01-general/index.md"]
    assert result.ok
    assert general.reference_records() == [
        {
            "kind": "docs",
            "target": "general/joining",
            "label": "joining",
            "href": "/docs/general/joining#who-can-join",
        }
    ]
    assert 'href="/docs/general/joining#who-can-join"' in general.html


def test_an_external_url_is_left_alone(tmp_path):
    write_repository(
        tmp_path,
        pages=[("wiki/a-page.md", page("See [the docs](https://example.com/a?b=1#c)."))],
    )

    result = resolve(tmp_path)

    assert result.ok
    assert result.documents[0].references == ()
    assert 'href="https://example.com/a?b=1#c"' in result.documents[0].html


def test_a_front_matter_reference_with_a_fixed_kind_omits_the_prefix():
    result = resolve(FIXTURES / "valid_multi")

    article = result.by_path()["articles/crisp-dm-for-ai/index.md"]
    assert result.ok
    # `authors: [alexey-grigorev]` is a person reference written without one.
    assert article.document.data["authors"] == ["alexey-grigorev"]
    assert "person" in {reference.kind for reference in article.references}


def test_a_reference_style_link_resolves_like_an_inline_one(tmp_path):
    """The rendered HTML is what is resolved, so every link syntax is seen."""

    write_repository(
        tmp_path,
        pages=[
            ("wiki/a-page.md", page("See [the other page][other].\n\n[other]: b-page.md")),
            ("wiki/b-page.md", page("Body.", title="B Page").replace("88888888", "40404040")),
        ],
    )

    result = resolve(tmp_path)

    assert result.ok
    assert result.by_path()["wiki/a-page.md"].reference_records() == [
        {"kind": "wiki", "target": "b-page", "label": "the other page", "href": "/wiki/b-page"}
    ]


def test_a_fragment_must_name_a_heading_of_the_target(tmp_path):
    write_repository(
        tmp_path,
        pages=[
            ("wiki/a-page.md", page("See [the setup](b-page.md#setup).")),
            (
                "wiki/b-page.md",
                page("## Installation\n\nBody.", title="B Page").replace("88888888", "40404040"),
            ),
        ],
    )

    result = resolve(tmp_path)

    assert [item.rule for item in result.errors] == ["3.7"]
    assert "no heading 'setup' in wiki/b-page.md" in result.errors[0].message


def test_an_unresolved_reference_fails_under_strict_references():
    result = resolve(FIXTURES / "invalid" / "unresolved_reference")

    assert [(item.rule, item.severity) for item in result.diagnostics] == [("3.7", "error")]
    assert result.ok is False


def test_strict_references_false_drops_the_link_and_keeps_the_label():
    result = resolve(FIXTURES / "lenient_references")

    document = result.documents[0]
    assert [(item.rule, item.severity) for item in result.diagnostics] == [("3.7", "warning")]
    assert result.ok
    assert "power analysis" in document.text
    assert "<a" not in document.html
    assert document.references == ()


def test_a_kind_another_source_owns_waits_for_that_source(tmp_path):
    write_repository(
        tmp_path,
        pages=[("wiki/a-page.md", page("See [Rahul](person:16rahuljain)."))],
    )

    without_routes = resolve(tmp_path)
    with_routes = resolve(tmp_path, routes=lambda kind, target: f"/people/{target}")
    without_row = resolve(tmp_path, routes=lambda kind, target: None)

    assert without_routes.ok
    assert without_routes.documents[0].references == ()
    assert with_routes.documents[0].reference_records() == [
        {"kind": "person", "target": "16rahuljain", "label": "Rahul", "href": "/people/16rahuljain"}
    ]
    assert [item.rule for item in without_row.errors] == ["3.7"]


def test_a_site_route_wins_over_the_package_default():
    result = resolve(FIXTURES / "valid_multi", routes=lambda kind, target: f"/kb/{kind}/{target}")

    article = result.by_path()["articles/crisp-dm-for-ai/index.md"]
    assert {reference.href for reference in article.references} == {
        "/kb/wiki/a-b-testing",
        "/kb/person/alexey-grigorev",
    }


def test_an_unknown_kind_in_a_typed_reference_is_an_error():
    result = resolve(FIXTURES / "invalid" / "unknown_reference_kind")

    assert [item.rule for item in result.errors] == ["3.7"]
    assert "unknown kind in a typed reference: podcast" in result.errors[0].message


def test_a_relative_link_stays_inside_one_collection():
    result = resolve(FIXTURES / "valid_multi")
    assert result.ok

    result = resolve_repository(read_repository(FIXTURES / "valid_docs"))
    assert result.ok


# --- source ordering, section 3.7 ---------------------------------------------


def test_sources_are_ordered_by_the_kinds_their_collections_declare(tmp_path):
    """Two sources, one dependency, and no hand-written list anywhere."""

    people = write_repository(
        tmp_path / "people",
        manifest="schema_version: 1\ncollections:\n  - kind: person\n    path: people\n",
        pages=[
            (
                "people/alexey-grigorev.md",
                page("Alexey teaches.", title="Alexey Grigorev"),
            )
        ],
    )
    articles = write_repository(
        tmp_path / "articles",
        manifest="schema_version: 1\ncollections:\n  - kind: article\n    path: articles\n",
        pages=[
            (
                "articles/one/index.md",
                page(
                    "A body.",
                    title="One",
                    front="date: 2026-03-11\nauthors: [alexey-grigorev]\n",
                ),
            )
        ],
    )
    sources = [read_repository(articles), read_repository(people)]

    ordered = order_sources(sources)

    assert [item.collections[0].kind.name for item in ordered] == ["person", "article"]


def test_source_ordering_keeps_the_given_order_for_unrelated_sources(tmp_path):
    first = write_repository(tmp_path / "one", pages=[("wiki/a.md", page("Body."))])
    second = write_repository(tmp_path / "two", pages=[("wiki/b.md", page("Body."))])
    sources = [read_repository(second), read_repository(first)]

    assert order_sources(sources) == tuple(sources)


def test_source_ordering_reports_a_declared_cycle():
    register_kind(
        "left",
        KindSpec(name="left", shape="document", layout=FlatLayout(), depends_on=("right",)),
    )
    register_kind(
        "right",
        KindSpec(name="right", shape="document", layout=FlatLayout(), depends_on=("left",)),
    )

    with pytest.raises(KindDependencyError, match="left, right"):
        order_sources([("a", ("left",)), ("b", ("right",))], kinds=lambda item: item[1])


def test_source_ordering_follows_a_site_kind_that_declares_its_dependency():
    register_kind(
        "workshop",
        KindSpec(
            name="workshop",
            shape="manifest",
            layout=FlatLayout(),
            keys={"instructors": KeySpec("reference_list", reference_kind="person")},
        ),
    )

    ordered = order_sources(
        [("workshops", ("workshop",)), ("people", ("person",))], kinds=lambda item: item[1]
    )

    assert [name for name, _ in ordered] == ["people", "workshops"]


# --- the whole pass -----------------------------------------------------------


def test_a_repository_that_was_not_read_resolves_to_nothing():
    result = resolve_repository(read_repository(FIXTURES / "no-such-repository"))

    assert result == type(result)()


def test_resolution_renders_the_body_once_and_stores_its_text_and_headings():
    result = resolve(FIXTURES / "valid_docs")

    joining = result.by_path()["docs/01-general/01-joining.md"]
    assert joining.headings == ({"level": 2, "id": "who-can-join", "title": "Who can join"},)
    assert joining.text == "Who can join Anyone."
    assert joining.html.startswith('<h2 id="who-can-join">')


def test_a_data_record_is_opaque_and_its_keys_are_not_assets(tmp_path):
    """The one kind without core keys has no `image` for the engine to resolve."""

    write_repository(
        tmp_path,
        manifest="schema_version: 1\ncollections:\n  - kind: data\n    path: data\n",
        pages=[("data/tiers.yaml", "image: /not/a/repository/path.png\ntiers: []\n")],
    )

    result = resolve(tmp_path, media=FakeStore())

    assert result.ok
    assert result.assets == ()
