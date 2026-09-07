import pytest

from community_base.coursework.models import ProjectState, ProjectStatistics, ProjectSubmission
from community_base.coursework.stat_display import project_stat_sections
from community_base.coursework.statistics import (
    calculate_project_statistics,
    calculate_raw_project_statistics,
)
from tests.coursework.test_models import (
    coursework_cohort,
    enrollment_for,
)
from tests.coursework.test_projects import make_project

pytestmark = pytest.mark.django_db

# Default score fields a project submission carries, matching the donor test defaults.
DEFAULT_SCORES = {
    "project_score": 10,
    "project_learning_in_public_score": 5,
    "peer_review_score": 3,
    "peer_review_learning_in_public_score": 2,
    "total_score": 20,
    "time_spent": 10.5,
}


def make_scored_submission(project, enrollment, **scores):
    values = {**DEFAULT_SCORES, **scores}
    return ProjectSubmission.objects.create(
        project=project,
        student=enrollment.user,
        enrollment=enrollment,
        github_link="https://github.com/example/repo",
        commit_id="a" * 40,
        **values,
    )


def assert_distribution(stats, field, minimum, maximum, average):
    assert stats[field]["min"] == minimum
    assert stats[field]["max"] == maximum
    assert stats[field]["avg"] == average


def test_calculate_raw_project_statistics_basic():
    cohort = coursework_cohort()
    project = make_project(cohort, state=ProjectState.COMPLETED.value)
    enrollments = [
        enrollment_for(cohort, email=f"rawstat{index}@example.com")[1] for index in range(3)
    ]
    scores = [
        {"project_score": 8, "total_score": 15, "time_spent": 8.0},
        {"project_score": 12, "total_score": 20, "time_spent": 12.0},
        {"project_score": 10, "total_score": 18, "time_spent": 10.0},
    ]
    for enrollment, values in zip(enrollments, scores, strict=True):
        make_scored_submission(project, enrollment, **values)

    stats = calculate_raw_project_statistics(project)

    assert stats["total_submissions"] == 3
    assert_distribution(stats, "project_score", 8, 12, 10.0)
    assert_distribution(stats, "total_score", 15, 20, 17.666666666666668)
    assert_distribution(stats, "time_spent", 8.0, 12.0, 10.0)


def test_calculate_raw_project_statistics_insufficient_data():
    cohort = coursework_cohort()
    project = make_project(cohort, state=ProjectState.COMPLETED.value)
    enrollments = [
        enrollment_for(cohort, email=f"fewstat{index}@example.com")[1] for index in range(2)
    ]
    for enrollment in enrollments:
        make_scored_submission(project, enrollment)

    stats = calculate_raw_project_statistics(project)

    assert stats["total_submissions"] == 2

    for field in ("project_score", "total_score", "time_spent"):
        for key in ("min", "max", "avg", "q1", "median", "q3"):
            assert stats[field][key] is None


def test_calculate_raw_project_statistics_with_nulls():
    cohort = coursework_cohort()
    project = make_project(cohort, state=ProjectState.COMPLETED.value)
    enrollments = [
        enrollment_for(cohort, email=f"nullstat{index}@example.com")[1] for index in range(4)
    ]
    scores = [
        {"project_score": 8, "total_score": 15, "time_spent": None},
        {"project_score": 12, "total_score": 20, "time_spent": 12.0},
        {"project_score": 10, "total_score": 18, "time_spent": 10.0},
        {"project_score": 9, "total_score": 16, "time_spent": 8.0},
    ]
    for enrollment, values in zip(enrollments, scores, strict=True):
        make_scored_submission(project, enrollment, **values)

    stats = calculate_raw_project_statistics(project)

    # Null time_spent rows are excluded from the time distribution...
    assert_distribution(stats, "time_spent", 8.0, 12.0, 10.0)
    # ...but their scores still count towards the score distributions.
    assert stats["project_score"]["min"] == 8
    assert stats["project_score"]["max"] == 12


def model_method_scores(index):
    return {
        "project_score": 10 + index,
        "total_score": 20 + index,
        "time_spent": 10.0 + index,
    }


def test_calculate_project_statistics_model_creation():
    cohort = coursework_cohort()
    project = make_project(cohort, state=ProjectState.COMPLETED.value)
    enrollments = [
        enrollment_for(cohort, email=f"statmodel{index}@example.com")[1] for index in range(3)
    ]
    for index, enrollment in enumerate(enrollments):
        make_scored_submission(project, enrollment, **model_method_scores(index))

    assert not ProjectStatistics.objects.filter(project=project).exists()

    stats = calculate_project_statistics(project)

    assert ProjectStatistics.objects.filter(project=project).exists()
    assert stats.project == project
    assert stats.total_submissions == 3
    assert stats.min_project_score == 10
    assert stats.max_project_score == 12
    assert stats.avg_project_score == 11.0


def test_calculate_project_statistics_force_update():
    cohort = coursework_cohort()
    project = make_project(cohort, state=ProjectState.COMPLETED.value)
    enrollments = [
        enrollment_for(cohort, email=f"statforce{index}@example.com")[1] for index in range(4)
    ]
    for enrollment in enrollments[:3]:
        make_scored_submission(project, enrollment)

    stats = calculate_project_statistics(project)
    initial_count = stats.total_submissions

    make_scored_submission(project, enrollments[3])

    stats = calculate_project_statistics(project, force=False)
    assert stats.total_submissions == initial_count

    stats = calculate_project_statistics(project, force=True)
    assert stats.total_submissions == initial_count + 1


def test_calculate_project_statistics_refuses_uncompleted_project():
    cohort = coursework_cohort()
    project = make_project(
        cohort,
        slug="incomplete-project",
        title="Incomplete Project",
        state=ProjectState.COLLECTING_SUBMISSIONS.value,
    )

    with pytest.raises(ValueError) as error:
        calculate_project_statistics(project)

    assert "Cannot calculate statistics for uncompleted project" in str(error.value)


def test_project_statistics_model_methods():
    cohort = coursework_cohort()
    project = make_project(cohort, state=ProjectState.COMPLETED.value)
    enrollments = [
        enrollment_for(cohort, email=f"statfields{index}@example.com")[1] for index in range(3)
    ]
    for index, enrollment in enumerate(enrollments):
        make_scored_submission(project, enrollment, **model_method_scores(index))

    stats = calculate_project_statistics(project)

    assert stats.get_value("project_score", "min") == 10
    assert stats.get_value("project_score", "max") == 12
    assert stats.get_value("total_score", "avg") == 21.0

    stat_fields = stats.get_stat_fields()
    assert [section[0] for section in stat_fields] == [
        section.label for section in project_stat_sections()
    ]
    field_name, field_stats, field_icon = stat_fields[0]
    assert isinstance(field_name, str)
    assert isinstance(field_stats, list)
    assert isinstance(field_icon, str)
    assert len(field_stats[0]) == 3

    assert project.slug in str(stats)
