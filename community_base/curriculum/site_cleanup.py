"""Course cleanup shared by default and site-adapted sync."""

from community_base.curriculum.models import Course, CurriculumImportRun


def draft_missing_courses(source, parser_version, seen_content_ids):
    """Draft this source's courses only after its latest successful import."""

    runs = CurriculumImportRun.objects.filter(
        source_uuid=source.pk, parser_version=parser_version
    ).order_by("-created_at")
    latest = runs.first()
    if latest is None or latest.state != CurriculumImportRun.State.SUCCEEDED:
        return ()
    commits = _reference_commits(source, parser_version, latest)
    candidates = _managed_courses(source, parser_version, commits)
    drafted = _missing_courses(candidates, seen_content_ids)
    _draft_courses(drafted)
    return drafted


def _reference_commits(source, parser_version, latest):
    earlier = CurriculumImportRun.objects.filter(
        source_uuid=source.pk,
        parser_version=parser_version,
        state=CurriculumImportRun.State.SUCCEEDED,
        created_at__lt=latest.created_at,
    )
    commits = list(earlier.values_list("commit_sha", flat=True).distinct())
    commits.append(latest.commit_sha)
    return commits


def _managed_courses(source, parser_version, reference_commits):
    runs = CurriculumImportRun.objects.filter(
        source_uuid=source.pk,
        parser_version=parser_version,
        state=CurriculumImportRun.State.SUCCEEDED,
    )
    managed_slugs = list(runs.values_list("source_stable_id", flat=True).distinct())
    return Course.objects.filter(slug__in=managed_slugs, source_commit_sha__in=reference_commits)


def _missing_courses(candidates, seen_content_ids):
    seen = set()
    for value in seen_content_ids:
        if value is not None:
            seen.add(str(value))
    drafted = []
    for course in candidates:
        content_id = course.source_content_id
        if content_id is None or str(content_id) not in seen:
            drafted.append(course)
    return drafted


def _draft_courses(drafted):
    for course in drafted:
        course.status = "draft"
        course.save(update_fields=["status", "updated_at"])
