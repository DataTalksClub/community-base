import pytest

from community_base.content_sync.kinds import (
    CORE_KEYS,
    PACKAGE_KIND_NAMES,
    DirNode,
    KeySpec,
    KindDependencyError,
    KindSpec,
    PartSpec,
    check_item_keys,
    get_kind,
    is_registered,
    kind_order,
    kinds,
    register_kind,
    slug_from_name,
    split_order_prefix,
)
from community_base.content_sync.kinds.layouts import (
    CourseLayout,
    DataLayout,
    FlatLayout,
    ItemDirectoryLayout,
    TreeLayout,
)


def site_kind(name="workshop", **overrides):
    defaults = {
        "name": name,
        "shape": "manifest",
        "layout": ItemDirectoryLayout(part=name, document="workshop.yaml"),
        "keys": {"instructors": KeySpec("reference_list", reference_kind="person")},
        "requires_date": True,
        "route": lambda path: f"workshops/{path}",
    }
    defaults.update(overrides)
    return KindSpec(**defaults)


def test_package_registers_the_six_kinds():
    assert PACKAGE_KIND_NAMES == ("article", "course", "data", "docs", "person", "wiki")
    assert [name for name, _ in kinds()] == sorted(PACKAGE_KIND_NAMES)


def test_get_kind_names_the_missing_kind():
    with pytest.raises(LookupError, match="podcast"):
        get_kind("podcast")


def test_a_site_registers_its_own_kind():
    register_kind("workshop", site_kind())

    assert is_registered("workshop")
    assert get_kind("workshop").route("serving-open-models") == "workshops/serving-open-models"


def test_a_kind_is_registered_once():
    register_kind("workshop", site_kind())

    with pytest.raises(ValueError, match="already registered"):
        register_kind("workshop", site_kind())


def test_a_kind_may_not_retype_a_core_key():
    spec = site_kind(keys={"summary": KeySpec("integer")})

    with pytest.raises(ValueError, match="core key summary"):
        register_kind("workshop", spec)


def test_a_kind_declares_a_known_shape_and_layout():
    with pytest.raises(ValueError, match="unknown shape"):
        register_kind("workshop", site_kind(shape="booklet"))
    with pytest.raises(TypeError, match="Layout"):
        register_kind("workshop", site_kind(layout=object()))
    with pytest.raises(ValueError, match="unknown type"):
        register_kind("workshop", site_kind(keys={"level": KeySpec("colour")}))


def test_a_kind_name_is_a_registry_name():
    with pytest.raises(ValueError, match="must match"):
        register_kind("Workshop", site_kind("Workshop"))
    with pytest.raises(ValueError, match="declares the name"):
        register_kind("workshop", site_kind("seminar"))


def test_dependencies_come_from_the_reference_keys_when_undeclared():
    assert get_kind("article").dependencies == ("person",)
    assert get_kind("course").dependencies == ("person",)
    assert get_kind("data").dependencies == ()


def test_an_explicit_dependency_wins_over_the_derivation():
    # The wiki declares `person` although no key of it names a person: its
    # references live in the body as typed links.
    assert get_kind("wiki").keys["related"].reference_kind is None
    assert get_kind("wiki").dependencies == ("person",)


def test_kind_order_is_topological_and_stable():
    order = kind_order()

    assert order.index("person") < order.index("article")
    assert order.index("person") < order.index("wiki")
    assert kind_order() == order
    assert kind_order(["article"]) == ("person", "article")


def test_kind_order_reports_a_cycle():
    register_kind("first", site_kind("first", depends_on=("second",)))
    register_kind("second", site_kind("second", depends_on=("first",)))

    with pytest.raises(KindDependencyError, match="first, second"):
        kind_order()


def test_core_keys_apply_to_every_kind_but_data():
    article = get_kind("article")
    assert set(CORE_KEYS) <= set(article.part("article").keys | CORE_KEYS)
    assert get_kind("data").part("data").core_keys is False


def test_check_item_keys_reports_missing_unknown_and_mistyped():
    part = get_kind("wiki").part("wiki")

    problems = check_item_keys({"title": "A", "layout": "wiki", "tags": "llm"}, part)

    reported = {(problem.pointer, problem.rule) for problem in problems}
    assert ("/content_id", "3.3") in reported
    assert ("/layout", "3.3") in reported
    assert ("/tags", "3.3") in reported


def test_check_item_keys_accepts_a_valid_document():
    part = get_kind("wiki").part("wiki")

    assert (
        check_item_keys(
            {
                "content_id": "c4d5e6f7-a8b9-4c0d-8e1f-2a3b4c5d6e7f",
                "title": "A/B Testing",
                "summary": "One line.",
                "related": ["wiki:power-analysis"],
                "extra": {"seo_title": "A/B testing"},
            },
            part,
        )
        == []
    )


def test_date_is_required_by_the_kinds_that_declare_it_and_forbidden_elsewhere():
    article = check_item_keys(
        {"content_id": "6bc9da15-7603-46ee-901d-096fdebf5764", "title": "A"},
        get_kind("article").part("article"),
    )
    wiki = check_item_keys(
        {
            "content_id": "6bc9da15-7603-46ee-901d-096fdebf5764",
            "title": "A",
            "date": "2026-03-11",
        },
        get_kind("wiki").part("wiki"),
    )

    assert [problem.pointer for problem in article] == ["/date"]
    assert [problem.message for problem in wiki] == [
        "date is forbidden on this kind; chronology belongs to kinds that declare it"
    ]


def test_ordering_prefix_and_slug_from_name():
    assert split_order_prefix("01-intro.md") == (1, "intro.md")
    assert split_order_prefix("001-first-question.md") == (1, "first-question.md")
    assert split_order_prefix("intro.md") == (None, "intro.md")
    assert slug_from_name("01-agentic-rag") == "agentic-rag"
    assert slug_from_name("02-environment.md") == "environment"


def node(path, files=(), dirs=()):
    return DirNode(path=path, files=tuple(files), dirs=tuple(dirs))


def test_flat_layout_refuses_a_subdirectory_that_is_not_assets():
    tree = node(
        "wiki",
        files=["a-b-testing.md", "README.md"],
        dirs=[node("wiki/images", ["cover.png"]), node("wiki/section", ["b.md"])],
    )

    items, problems = FlatLayout(part="wiki").walk(tree)

    assert [item.path for item in items] == ["wiki/a-b-testing.md"]
    assert [(path, problem.rule) for path, problem in problems] == [("wiki/section", "3.5")]


def test_tree_layout_needs_an_index_and_stops_at_four_levels():
    deep = node("docs/a/b/c/d/e", ["index.md"])
    tree = node(
        "docs",
        ["index.md"],
        [
            node(
                "docs/a",
                ["index.md"],
                [
                    node(
                        "docs/a/b",
                        ["index.md"],
                        [
                            node(
                                "docs/a/b/c",
                                ["index.md"],
                                [node("docs/a/b/c/d", ["index.md"], [deep])],
                            )
                        ],
                    )
                ],
            ),
            node("docs/orphan", ["page.md"]),
        ],
    )

    items, problems = TreeLayout(part="docs").walk(tree)

    rules = {(path, problem.rule) for path, problem in problems}
    assert ("docs/orphan", "3.5") in rules
    assert ("docs/a/b/c/d/e", "3.5") in rules
    assert "docs/index.md" in {item.path for item in items}


def test_tree_layout_leaves_the_collection_root_out_of_the_path():
    tree = node("docs", ["index.md"], [node("docs/02-courses", ["index.md", "07-project.md"])])

    items, _ = TreeLayout(part="docs").walk(tree)

    root = next(item for item in items if item.path == "docs/index.md")
    child = next(item for item in items if item.path == "docs/02-courses/index.md")
    assert root.contributes_slug is False
    assert child.contributes_slug is True


def test_item_directory_layout_wants_a_directory_per_item():
    tree = node(
        "articles",
        ["stray.md"],
        [node("articles/crisp-dm", ["index.md"], [node("articles/crisp-dm/images", ["c.png"])])],
    )

    items, problems = ItemDirectoryLayout(part="article").walk(tree)

    assert [item.path for item in items] == ["articles/crisp-dm/index.md"]
    assert [(path, problem.rule) for path, problem in problems] == [("articles/stray.md", "3.5")]


def test_data_layout_takes_nested_files():
    tree = node("data", ["tiers.yaml"], [node("data/graph", ["graph.json"])])

    items, problems = DataLayout().walk(tree)

    assert sorted(item.path for item in items) == ["data/graph/graph.json", "data/tiers.yaml"]
    assert problems == []


def test_course_layout_finds_every_part():
    tree = node(
        "",
        ["course.yaml"],
        [
            node(
                "01-agentic-rag",
                ["module.yaml", "README.md", "01-intro.md"],
                [node("01-agentic-rag/images", ["a.png"])],
            ),
            node(
                "cohorts",
                [],
                [
                    node(
                        "cohorts/2026",
                        ["cohort.yaml"],
                        [
                            node(
                                "cohorts/2026/homework",
                                [],
                                [node("cohorts/2026/homework/01-agentic-rag", ["homework.yaml"])],
                            )
                        ],
                    )
                ],
            ),
        ],
    )

    items, problems = CourseLayout().walk(tree)

    assert problems == []
    assert {item.part for item in items} == {"course", "module", "unit", "cohort", "homework"}


def test_course_layout_refuses_three_module_levels():
    tree = node(
        "",
        ["course.yaml"],
        [
            node(
                "01-one",
                ["module.yaml"],
                [
                    node(
                        "01-one/02-two",
                        ["module.yaml"],
                        [node("01-one/02-two/03-three", ["module.yaml"])],
                    )
                ],
            )
        ],
    )

    _, problems = CourseLayout().walk(tree)

    assert [(path, problem.rule) for path, problem in problems] == [
        ("01-one/02-two/03-three", "3.5")
    ]


def test_a_part_of_a_composite_kind_is_named():
    course = get_kind("course")

    assert sorted(course.item_parts) == ["cohort", "course", "homework", "module", "unit"]
    with pytest.raises(LookupError, match="no part sprint"):
        course.part("sprint")


def test_a_simple_kind_has_one_part_named_after_it():
    spec = site_kind("project", parts={})

    assert list(spec.item_parts) == ["project"]
    assert spec.item_parts["project"] == PartSpec(
        name="project",
        shape="manifest",
        keys=spec.keys,
        requires_date=True,
        core_keys=True,
        allow_unknown=False,
    )


def homework_keys(**overrides):
    """The homework part of the course kind, with one manifest to check."""

    data = {
        "content_id": "8f0b3ad2-77f4-4f0c-9d2a-1f3c2e4d5a6b",
        "title": "Homework 1",
        "due_at": "2026-09-01T23:59:00+02:00",
        "form": {"homework_url": True},
        "questions": [
            {
                "content_id": "8f0b3ad2-77f4-4f0c-9d2a-1f3c2e4d5a6c",
                "id": "q1",
                "type": "multiple_choice",
                "prompt": "Which retriever?",
                "points": 1,
                "options": [{"id": "a", "label": "minsearch"}],
            }
        ],
        **overrides,
    }
    return check_item_keys(data, get_kind("course").part("homework"))


def test_a_valid_homework_manifest_passes_the_registry():
    assert homework_keys() == []


def test_a_mapping_that_declares_its_keys_reports_an_unknown_one():
    """`form` names its five keys; `extra`, which names none, stays opaque."""

    problems = homework_keys(form={"homework_url": True, "learning_in_publik_cap": 3})

    assert [(problem.pointer, problem.message) for problem in problems] == [
        ("/form/learning_in_publik_cap", "unknown key: learning_in_publik_cap")
    ]


def test_a_mapping_that_declares_its_keys_reports_a_mistyped_one():
    problems = homework_keys(form={"learning_in_public_cap": "three"})

    assert [problem.pointer for problem in problems] == ["/form/learning_in_public_cap"]


def test_extra_stays_opaque():
    assert homework_keys(extra={"anything": {"nested": [1, 2]}}) == []


def test_the_homework_manifest_states_its_question_shape():
    problems = homework_keys(
        due_at="2026-09-01T23:59:00",
        questions=[
            {
                "content_id": "8f0b3ad2-77f4-4f0c-9d2a-1f3c2e4d5a6c",
                "id": "q1",
                "type": "essay",
                "prompt": "Which retriever?",
                "points": 1,
                "options": ["minsearch"],
                "answer_type": "string",
                "correct": "minsearch",
            }
        ],
    )

    reported = {problem.pointer: problem.message for problem in problems}
    assert reported["/due_at"] == "must carry a UTC offset"
    assert reported["/questions/0/type"].startswith("must be one of multiple_choice")
    assert reported["/questions/0/options/0"] == "must be a mapping, found str"
    assert reported["/questions/0/answer_type"].startswith("must be one of any, float")
    assert reported["/questions/0/correct"] == "unknown key: correct"
