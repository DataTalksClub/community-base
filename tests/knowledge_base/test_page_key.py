"""The page key: a slug scoped to its parent, and path-shaped slugs (C7.4)."""

import shutil

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client

from community_base.knowledge_base import hierarchy, sync
from community_base.knowledge_base.models import (
    SECTION_DOCS,
    SECTION_WIKI,
    STATUS_DRAFT,
    KnowledgeBasePage,
)
from tests.knowledge_base.fixture_parser import KbDocsTreeFixtureParser
from tests.knowledge_base.utils import DOCS_TREE_REPO, ParserHarness, make_source

pytestmark = pytest.mark.django_db


def make_page(*, section=SECTION_DOCS, slug="page", title="Page", parent=None, **fields):
    page = KnowledgeBasePage(section=section, slug=slug, title=title, parent=parent, **fields)
    page.full_clean()
    page.save()
    return page


def test_slug_accepts_a_path_but_not_a_malformed_one():
    page = make_page(slug="course-a/module-1/project", title="Project")
    assert page.slug == "course-a/module-1/project"
    for bad in ("/leading", "trailing/", "double//slash", "no spaces"):
        with pytest.raises(ValidationError):
            make_page(slug=bad, title="Bad")


def test_two_root_pages_may_share_a_slug_across_sections():
    docs = make_page(section=SECTION_DOCS, slug="faq", title="Docs FAQ")
    wiki = make_page(section=SECTION_WIKI, slug="faq", title="Wiki FAQ")
    assert {docs.section, wiki.section} == {SECTION_DOCS, SECTION_WIKI}


def test_two_root_pages_in_one_section_may_not_share_a_slug():
    make_page(slug="faq", title="First")
    duplicate = KnowledgeBasePage(section=SECTION_DOCS, slug="faq", title="Second")
    with pytest.raises(IntegrityError), transaction.atomic():
        duplicate.save()


def test_two_children_of_one_parent_may_not_share_a_slug():
    parent = make_page(slug="course-a", title="Course A")
    make_page(slug="project", title="First", parent=parent)
    duplicate = KnowledgeBasePage(
        section=SECTION_DOCS, slug="project", title="Second", parent=parent
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        duplicate.save()


def test_the_same_leaf_slug_lives_under_different_parents():
    course_a = make_page(slug="course-a", title="Course A")
    course_b = make_page(slug="course-b", title="Course B")
    first = make_page(slug="project", title="A project", parent=course_a)
    second = make_page(slug="project", title="B project", parent=course_b)
    assert first.get_absolute_url() == "/docs/course-a/project/"
    assert second.get_absolute_url() == "/docs/course-b/project/"


def test_a_root_page_and_a_child_may_share_a_slug():
    parent = make_page(slug="project", title="Project root")
    child = make_page(slug="project", title="Nested project", parent=parent)
    assert child.parent_id == parent.pk


def test_sequential_navigation_follows_the_page_not_its_namesake():
    course_a = make_page(slug="course-a", title="Course A", nav_order=1)
    course_b = make_page(slug="course-b", title="Course B", nav_order=2)
    first = make_page(slug="project", title="A project", parent=course_a)
    second = make_page(slug="project", title="B project", parent=course_b)

    previous, following = hierarchy.sequential_navigation(first)
    assert (previous.pk, following.pk) == (course_a.pk, course_b.pk)
    previous, following = hierarchy.sequential_navigation(second)
    assert (previous.pk, following) == (course_b.pk, None)


def test_tree_parser_stores_a_three_level_tree_with_repeated_leaf_slugs():
    _source, items, results, deleted = ParserHarness().run_parser(
        KbDocsTreeFixtureParser(), DOCS_TREE_REPO
    )

    assert deleted == []
    assert [result.action for result in results] == ["created"] * 7
    assert {item.key for item in items} == {
        "docs/index.md",
        "docs/course-a/index.md",
        "docs/course-a/project.md",
        "docs/course-a/module-1/index.md",
        "docs/course-a/module-1/project.md",
        "docs/course-b/index.md",
        "docs/course-b/project.md",
    }
    projects = KnowledgeBasePage.objects.filter(slug="project").order_by("title")
    assert [page.title for page in projects] == [
        "Course A project",
        "Course B project",
        "Module 1 project",
    ]
    assert {page.get_absolute_url() for page in projects} == {
        "/docs/course-a/project/",
        "/docs/course-b/project/",
        "/docs/course-a/module-1/project/",
    }


def test_each_page_of_the_tree_reads_back_at_its_own_path():
    ParserHarness().run_parser(KbDocsTreeFixtureParser(), DOCS_TREE_REPO)
    client = Client()

    for path, title in (
        ("/docs/course-a/project/", "Course A project"),
        ("/docs/course-a/module-1/project/", "Module 1 project"),
        ("/docs/course-b/project/", "Course B project"),
        ("/docs/course-a/module-1/", "Module 1"),
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.context["page"].title == title


def test_tree_reimport_is_unchanged():
    harness = ParserHarness()
    harness.run_parser(KbDocsTreeFixtureParser(), DOCS_TREE_REPO)

    _source, _items, results, deleted = harness.run_parser(
        KbDocsTreeFixtureParser(), DOCS_TREE_REPO
    )

    assert [result.action for result in results] == ["unchanged"] * 7
    assert deleted == []
    assert KnowledgeBasePage.objects.count() == 7


def test_a_removed_page_is_drafted_although_its_slug_survives_elsewhere(tmp_path):
    repo = shutil.copytree(DOCS_TREE_REPO, tmp_path / "repo")
    harness = ParserHarness()
    harness.run_parser(KbDocsTreeFixtureParser(), repo)
    (repo / "docs" / "course-b" / "project.md").unlink()

    _source, _items, _results, deleted = harness.run_parser(KbDocsTreeFixtureParser(), repo)

    assert [page.source_path for page in deleted] == ["docs/course-b/project.md"]
    assert (
        KnowledgeBasePage.objects.get(source_path="docs/course-b/project.md").status == STATUS_DRAFT
    )
    assert (
        KnowledgeBasePage.objects.get(source_path="docs/course-a/project.md").status != STATUS_DRAFT
    )


def test_a_page_that_changes_parent_is_updated_not_duplicated():
    source = make_source()
    common = {
        "commit_sha": "c" * 40,
        "source_path": "docs/guide.md",
        "checksum": "d" * 64,
    }
    make_page(slug="course-a", title="Course A")
    make_page(slug="course-b", title="Course B")
    sync.upsert_page(
        source, section=SECTION_DOCS, slug="guide", title="Guide", parent_slug="course-a", **common
    )

    page, action = sync.upsert_page(
        source,
        section=SECTION_DOCS,
        slug="guide",
        title="Guide",
        parent_slug="course-b",
        commit_sha="c" * 40,
        source_path="docs/guide.md",
        checksum="e" * 64,
    )

    assert action == "updated"
    assert page.parent.slug == "course-b"
    assert KnowledgeBasePage.objects.filter(slug="guide").count() == 1


def test_an_ambiguous_parent_slug_is_refused():
    source = make_source()
    course_a = make_page(slug="course-a", title="Course A")
    course_b = make_page(slug="course-b", title="Course B")
    make_page(slug="project", title="A project", parent=course_a)
    make_page(slug="project", title="B project", parent=course_b)

    with pytest.raises(sync.KnowledgeBaseSyncError) as error:
        sync.upsert_page(
            source,
            section=SECTION_DOCS,
            slug="task",
            title="Task",
            parent_slug="project",
            commit_sha="c" * 40,
            source_path="docs/task.md",
            checksum="d" * 64,
        )
    assert "parent_path" in str(error.value)


def test_a_parent_path_segment_that_does_not_exist_is_refused():
    source = make_source()
    make_page(slug="course-a", title="Course A")

    with pytest.raises(sync.KnowledgeBaseSyncError) as error:
        sync.upsert_page(
            source,
            section=SECTION_DOCS,
            slug="task",
            title="Task",
            parent_path="course-a/module-9",
            commit_sha="c" * 40,
            source_path="docs/task.md",
            checksum="d" * 64,
        )
    assert "module-9" in str(error.value)


def test_naming_the_parent_twice_is_refused():
    source = make_source()
    make_page(slug="course-a", title="Course A")

    with pytest.raises(sync.KnowledgeBaseSyncError):
        sync.upsert_page(
            source,
            section=SECTION_DOCS,
            slug="task",
            title="Task",
            parent_slug="course-a",
            parent_path="course-a",
            commit_sha="c" * 40,
            source_path="docs/task.md",
            checksum="d" * 64,
        )


def test_delete_missing_needs_exactly_one_seen_set():
    source = make_source()
    with pytest.raises(sync.KnowledgeBaseSyncError):
        sync.delete_missing(source, SECTION_DOCS)
    with pytest.raises(sync.KnowledgeBaseSyncError):
        sync.delete_missing(source, SECTION_DOCS, set(), seen_source_paths=set())
