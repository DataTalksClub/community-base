"""Migration 0006: the source primary key leaves ``source_content_id`` (C7.9c).

A7.1 is live on AI Shipping Labs with real knowledge base rows written the old
way, so this migration runs against real data. These tests run it for real --
backwards to 0005, rows written as the old code wrote them, then forwards --
and check the rows rather than asserting what the code intends.
"""

import uuid

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from community_base.content_sync.models import ContentSource

APP = "cb_knowledge_base"
BEFORE = "0005_page_record"
AFTER = "0006_page_source_foreign_key"
WITH_PERSON = "0007_person"

COMMIT = "b" * 40
CHECKSUM = "c" * 64

pytestmark = pytest.mark.django_db(transaction=True)


def migrate(target: str):
    """Migrate this app to one of its own states and return that state's apps."""

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate([(APP, target)])
    executor.loader.build_graph()
    return executor.loader.project_state([(APP, target)]).apps


def write_old_rows(apps):
    """Two synced pages and a Studio-authored one, as 0005 stored them."""

    # `ContentSource` is not part of this app's migration state, and these
    # migrations do not touch it, so the live model writes the source row.
    page_model = apps.get_model(APP, "KnowledgeBasePage")
    source = ContentSource.objects.create(
        id=uuid.uuid4(), slug="aisl-docs", repo_name="example/aisl-docs", webhook_secret="s"
    )
    for index, (section, slug) in enumerate(((("docs"), "setup"), ("wiki", "billing-faq"))):
        page_model.objects.create(
            section=section,
            slug=slug,
            title=slug.title(),
            # The old code stored the ContentSource primary key here.
            source_content_id=source.id,
            source_path=f"{section}/{slug}.md",
            source_commit_sha=COMMIT,
            source_checksum=chr(ord("a") + index) * 64,
        )
    page_model.objects.create(section="docs", slug="hand-written", title="Hand written")
    return source


def test_the_stored_source_primary_key_moves_into_the_source_foreign_key():
    old_apps = migrate(BEFORE)
    source = write_old_rows(old_apps)
    before = old_apps.get_model(APP, "KnowledgeBasePage").objects.count()

    new_apps = migrate(AFTER)

    page_model = new_apps.get_model(APP, "KnowledgeBasePage")
    after = page_model.objects.count()
    synced = page_model.objects.exclude(source=None)
    print(f"\nrows before 0006: {before}; rows after 0006: {after}")
    print(
        f"moved into source: {synced.count()}; source_content_id left set: "
        f"{page_model.objects.exclude(source_content_id=None).count()}"
    )
    assert after == before == 3
    assert sorted(page.slug for page in synced) == ["billing-faq", "setup"]
    assert {page.source_id for page in synced} == {source.id}
    assert page_model.objects.exclude(source_content_id=None).count() == 0
    hand_written = page_model.objects.get(slug="hand-written")
    assert hand_written.source_id is None
    assert hand_written.source_path is None
    migrate(WITH_PERSON)


def test_the_rest_of_an_a71_row_is_untouched():
    old_apps = migrate(BEFORE)
    write_old_rows(old_apps)

    new_apps = migrate(AFTER)

    page = new_apps.get_model(APP, "KnowledgeBasePage").objects.get(slug="setup")
    assert page.title == "Setup"
    assert page.source_path == "docs/setup.md"
    assert page.source_commit_sha == COMMIT
    assert page.source_checksum == "a" * 64
    assert page.status == "published"
    assert page.public_path is None
    assert page.record == {}
    migrate(WITH_PERSON)


def test_a_value_naming_no_content_source_is_dropped_deliberately():
    old_apps = migrate(BEFORE)
    write_old_rows(old_apps)
    dangling = uuid.uuid4()
    old_apps.get_model(APP, "KnowledgeBasePage").objects.create(
        section="wiki",
        slug="orphaned",
        title="Orphaned",
        source_content_id=dangling,
        source_path="wiki/orphaned.md",
        source_commit_sha=COMMIT,
        source_checksum=CHECKSUM,
    )

    new_apps = migrate(AFTER)

    page = new_apps.get_model(APP, "KnowledgeBasePage").objects.get(slug="orphaned")
    print(f"\ndangling values dropped: 1 (was {dangling})")
    assert page.source_id is None
    assert page.source_content_id is None
    # The row itself survives with its provenance intact.
    assert page.source_path == "wiki/orphaned.md"
    assert page.source_checksum == CHECKSUM
    migrate(WITH_PERSON)


def test_the_migration_reverses_and_re_applies_without_losing_a_row():
    old_apps = migrate(BEFORE)
    write_old_rows(old_apps)
    page_model = old_apps.get_model(APP, "KnowledgeBasePage")
    before = list(page_model.objects.order_by("slug").values_list("slug", "source_content_id"))

    migrate(AFTER)
    reversed_apps = migrate(BEFORE)
    restored = list(
        reversed_apps.get_model(APP, "KnowledgeBasePage")
        .objects.order_by("slug")
        .values_list("slug", "source_content_id")
    )
    reapplied_apps = migrate(AFTER)
    reapplied = reapplied_apps.get_model(APP, "KnowledgeBasePage").objects

    print(
        f"\nrows before: {len(before)}; after reverse: {len(restored)}; "
        f"after re-apply: {reapplied.count()}"
    )
    assert restored == before
    assert reapplied.count() == len(before)
    assert reapplied.exclude(source=None).count() == 2
    migrate(WITH_PERSON)


def test_the_person_table_arrives_empty_and_leaves_with_its_own_migration():
    migrate(BEFORE)
    new_apps = migrate(WITH_PERSON)

    assert new_apps.get_model(APP, "Person").objects.count() == 0

    old_apps = migrate(AFTER)
    with pytest.raises(LookupError):
        old_apps.get_model(APP, "Person")
    migrate(WITH_PERSON)
