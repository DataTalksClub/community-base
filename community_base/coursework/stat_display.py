"""Shared helpers for rendering HomeworkStatistics / ProjectStatistics.

Both statistics models expose the same per-field distribution
(min/max/avg/q1/median/q3) and render it as a list of
``(section_label, rows, section_icon)`` tuples for templates. This module
keeps that display structure in one place.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StatRow:
    stats_type: str
    label: str
    icon: str


@dataclass(frozen=True)
class StatSection:
    field_name: str
    label: str
    icon: str


STAT_ROWS = [
    StatRow("min", "Minimum", "fas fa-arrow-down"),
    StatRow("max", "Maximum", "fas fa-arrow-up"),
    StatRow("avg", "Average", "fas fa-equals"),
    StatRow("q1", "25th Percentile", "fas fa-percentage"),
    StatRow("median", "Median", "fas fa-percentage"),
    StatRow("q3", "75th Percentile", "fas fa-percentage"),
]


def homework_score_stat_sections():
    return [
        StatSection("questions_score", "Questions score", "fas fa-question-circle"),
        StatSection("total_score", "Total score", "fas fa-star"),
    ]


def homework_detail_stat_sections():
    return [
        StatSection("time_spent_lectures", "Time spent on lectures", "fas fa-book-reader"),
        StatSection("time_spent_homework", "Time spent on homework", "fas fa-clock"),
        StatSection("learning_in_public_score", "Learning in public score", "fas fa-globe"),
    ]


def homework_stat_sections():
    return homework_score_stat_sections() + homework_detail_stat_sections()


def project_score_stat_sections():
    return [
        StatSection("project_score", "Project score", "fas fa-project-diagram"),
        StatSection(
            "project_learning_in_public_score", "Project learning in public score", "fas fa-globe"
        ),
    ]


def project_peer_review_stat_sections():
    return [
        StatSection("peer_review_score", "Peer review score", "fas fa-users"),
        StatSection(
            "peer_review_learning_in_public_score",
            "Peer review learning in public score",
            "fas fa-share-alt",
        ),
    ]


def project_summary_stat_sections():
    return [
        StatSection("total_score", "Total score", "fas fa-star"),
        StatSection("time_spent", "Time spent on project", "fas fa-clock"),
    ]


def project_stat_sections():
    return (
        project_score_stat_sections()
        + project_peer_review_stat_sections()
        + project_summary_stat_sections()
    )


def build_stat_fields(stats, sections):
    """Build the display structure for a statistics model.

    ``sections`` is a list of ``StatSection`` objects. Returns a list of
    ``(section_label, rows, section_icon)`` where each row is
    ``(value, row_label, row_icon)``.
    """
    results = []
    for section in sections:
        rows = []
        for stat_row in STAT_ROWS:
            value = stats.get_value(section.field_name, stat_row.stats_type)
            rows.append((value, stat_row.label, stat_row.icon))
        results.append((section.label, rows, section.icon))
    return results
