"""Statistics computation for homework and project submissions."""

import statistics

from community_base.coursework.models import (
    Homework,
    HomeworkState,
    HomeworkStatistics,
    Project,
    ProjectState,
    ProjectStatistics,
    ProjectSubmission,
    Submission,
    SubmissionReviewState,
)

HOMEWORK_STAT_FIELDS = [
    "questions_score",
    "learning_in_public_score",
    "total_score",
    "time_spent_lectures",
    "time_spent_homework",
]

PROJECT_STAT_FIELDS = [
    "project_score",
    "project_learning_in_public_score",
    "peer_review_score",
    "peer_review_learning_in_public_score",
    "total_score",
    "time_spent",
]


def _field_values(submissions_data, field):
    values = []
    for submission in submissions_data:
        value = submission[field]
        if value is not None:
            values.append(value)
    return values


def _field_distribution(values):
    if len(values) < 3:
        return {
            "min": None,
            "max": None,
            "avg": None,
            "q1": None,
            "median": None,
            "q3": None,
        }

    quantiles = statistics.quantiles(values, n=4, method="inclusive")
    return {
        "min": min(values),
        "max": max(values),
        "avg": statistics.mean(values),
        "q1": quantiles[0],
        "median": quantiles[1],
        "q3": quantiles[2],
    }


def _calculate_field_distributions(submissions_data, fields):
    total_submissions = len(submissions_data)
    stats = {"total_submissions": total_submissions}

    for field in fields:
        field_values = _field_values(submissions_data, field)
        stats[field] = _field_distribution(field_values)

    return stats


def _persist_field_stats(stats, calculated_stats, fields):
    stats.total_submissions = calculated_stats["total_submissions"]

    for field in fields:
        field_stats = calculated_stats[field]

        setattr(stats, f"min_{field}", field_stats["min"])
        setattr(stats, f"max_{field}", field_stats["max"])
        setattr(stats, f"avg_{field}", field_stats["avg"])
        setattr(stats, f"median_{field}", field_stats["median"])
        setattr(stats, f"q1_{field}", field_stats["q1"])
        setattr(stats, f"q3_{field}", field_stats["q3"])


def calculate_raw_homework_statistics(homework: Homework):
    submission_rows = Submission.objects.filter(homework=homework).values(*HOMEWORK_STAT_FIELDS)
    submissions_data = list(submission_rows)
    return _calculate_field_distributions(submissions_data, HOMEWORK_STAT_FIELDS)


def calculate_homework_statistics(homework: Homework, force=False) -> HomeworkStatistics:
    if homework.state != HomeworkState.SCORED.value:
        raise ValueError(f"Cannot calculate statistics for unscored homework {homework}")

    stats, created = HomeworkStatistics.objects.get_or_create(homework=homework)

    if force or created:
        calculated_stats = calculate_raw_homework_statistics(homework)
        _persist_field_stats(stats, calculated_stats, HOMEWORK_STAT_FIELDS)
        stats.save()

    return stats


def calculate_raw_project_statistics(project: Project):
    # C5.2f: scope to review_state=SCORED, not every submission of the project. For deadline
    # mode this is a no-op change (calculate_project_statistics below still requires the whole
    # project COMPLETED before this runs, and every real submission mirrors SCORED at that same
    # moment -- see review.set_review_state_for_project). For a pooled project this is what
    # makes the statistic meaningful before every submission has been through a batch: it
    # reflects only the submissions actually scored so far, not zeroes from ones still waiting.
    submission_rows = ProjectSubmission.objects.filter(
        project=project, review_state=SubmissionReviewState.SCORED.value
    ).values(*PROJECT_STAT_FIELDS)
    submissions_data = list(submission_rows)
    return _calculate_field_distributions(submissions_data, PROJECT_STAT_FIELDS)


def calculate_project_statistics(project: Project, force=False) -> ProjectStatistics:
    """Compute (or recompute) one project's score distributions.

    Deadline mode: unchanged, requires the whole project ``COMPLETED`` (one operator action
    closes every submission's review at once, so "statistics ready" and "project done" are the
    same moment).

    Pooled mode: no such moment exists, so this is a live statistic instead -- callable any time,
    computed over whichever submissions have been scored by a batch so far
    (``calculate_raw_project_statistics`` above), and expected to be recalculated again as later
    batches complete. Never requires ``Project.state == COMPLETED``, which a pooled project never
    reaches (``Project.uses_pooled_review``).
    """
    if not project.uses_pooled_review and project.state != ProjectState.COMPLETED.value:
        raise ValueError(f"Cannot calculate statistics for uncompleted project {project}")

    stats, created = ProjectStatistics.objects.get_or_create(project=project)

    if force or created:
        calculated_stats = calculate_raw_project_statistics(project)
        _persist_field_stats(stats, calculated_stats, PROJECT_STAT_FIELDS)
        stats.save()

    return stats
