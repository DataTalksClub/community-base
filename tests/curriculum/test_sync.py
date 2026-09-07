import shutil
from pathlib import Path

import pytest
from django.core.management import call_command

from community_base.content_sync.models import ContentSource, SyncStatus
from community_base.content_sync.orchestration import sync_content_source
from community_base.content_sync.parsers import get_parser
from community_base.curriculum.content_sync_parsers import (
    AislCourseParser,
    DtcCourseRepositoryParser,
)
from community_base.curriculum.models import (
    Cohort,
    Course,
    CurriculumImportRun,
    Unit,
)
from tests.curriculum.utils import AISL_CONTENT, DTC_REPO

pytestmark = pytest.mark.django_db


def make_source(slug, repo):
    source = ContentSource(slug=slug, repo_name=repo, webhook_secret="fixture-secret")
    source.full_clean()
    source.save()
    return source


def test_both_parsers_are_registered():
    assert isinstance(get_parser("curriculum_aisl_course"), AislCourseParser)
    assert isinstance(get_parser("curriculum_dtc_course_repository"), DtcCourseRepositoryParser)


def test_sync_imports_aisl_fixture():
    source = make_source("aisl-content", "AI-Shipping-Labs/content")

    log = sync_content_source(source, repo_dir=str(AISL_CONTENT))

    assert log.status == SyncStatus.SUCCESS
    assert log.items_created == 1
    course = Course.objects.get(slug="ai-hero")
    assert course.cohorts.count() == 1
    assert course.total_units() == 3


def test_sync_reimport_is_unchanged():
    source = make_source("aisl-content", "AI-Shipping-Labs/content")
    sync_content_source(source, repo_dir=str(AISL_CONTENT))

    # From-disk syncs always re-run; the second pass must be a clean no-op.
    second = sync_content_source(source, repo_dir=str(AISL_CONTENT))
    assert second.status == SyncStatus.SUCCESS
    assert second.items_created == 0
    assert second.items_updated == 0
    assert second.items_deleted == 0
    assert second.items_unchanged == 1
    assert Course.objects.filter(slug="ai-hero").count() == 1
    assert Unit.objects.filter(module__cohort__course__slug="ai-hero").count() == 3


def test_sync_imports_dtc_fixture():
    source = make_source("dtc-repo", "DataTalksClub/ml-zoomcamp")

    log = sync_content_source(source, repo_dir=str(DTC_REPO))

    assert log.status == SyncStatus.SUCCESS
    course = Course.objects.get(slug="ml-zoomcamp")
    cohort = course.cohorts.get(slug="2026")
    assert cohort.curriculum_format == "modules"
    assert Unit.objects.filter(module__cohort=cohort).count() == 2


def test_sync_records_import_run():
    source = make_source("dtc-repo", "DataTalksClub/ml-zoomcamp")
    sync_content_source(source, repo_dir=str(DTC_REPO))

    run = CurriculumImportRun.objects.get(
        source_stable_id="ml-zoomcamp", state=CurriculumImportRun.State.SUCCEEDED
    )
    assert run.repository_owner == "DataTalksClub"
    assert run.repository_name == "ml-zoomcamp"
    assert run.parser_version == "dtc-course-repository-1"
    assert run.counts["created"] >= 1


def test_sync_records_parse_failure(tmp_path: Path):
    broken = tmp_path / "broken-repo"
    shutil_tree(DTC_REPO, broken)
    (broken / "course.yaml").write_text("schema_version: 1\ncontent_id: nope\n")
    source = make_source("broken", "example/broken")

    log = sync_content_source(source, repo_dir=str(broken))

    assert log.status == SyncStatus.PARTIAL
    assert any(
        "curriculum_dtc_course_repository" in item.get("content_type", "") for item in log.errors
    )
    # Parse failures happen before the import run is created, so no run row exists.
    assert not CurriculumImportRun.objects.filter(source_stable_id="ml-zoomcamp").exists()


def test_sync_command_reports_counts():
    make_source("aisl-content", "AI-Shipping-Labs/content")

    call_command(
        "sync_content",
        "--from-disk",
        str(AISL_CONTENT),
        "--source",
        "aisl-content",
        stdout=open("/dev/null", "w"),
    )

    assert Course.objects.filter(slug="ai-hero").exists()
    assert Cohort.objects.filter(course__slug="ai-hero", mode="self_paced").exists()


def shutil_tree(src: Path, dest: Path) -> None:
    shutil.copytree(src, dest)
