"""Tests for the YAML criteria peer-review evaluation form."""

import pytest
from django.http import QueryDict

from community_base.accounts.models import User
from community_base.coursework.models import PeerReview, PeerReviewState, Project, ProjectSubmission
from community_base.coursework.peer_review_form import (
    evaluation_form,
    missing_criteria_message,
    save_draft,
    save_review,
)
from community_base.coursework.project_criteria import parse_criteria
from community_base.curriculum.models import Cohort, Course, Enrollment

CRITERIA = parse_criteria(
    [
        {
            "id": "code",
            "title": "Code quality",
            "type": "scale",
            "options": [{"points": 0, "text": "Poor"}, {"points": 2, "text": "Good"}],
        },
        {
            "id": "extras",
            "title": "Extras",
            "type": "checklist",
            "options": [{"points": 1, "text": "Linting"}],
        },
    ],
    "course.yaml",
)


@pytest.mark.django_db
def test_save_draft_and_save_review_on_package_peer_review():
    course = Course.objects.create(slug="c1", title="Course 1")
    cohort = Cohort.objects.create(course=course, slug="2026", title="2026", mode="self_paced")
    project = Project.objects.create(
        cohort=cohort, slug="p1", title="P1", evaluation_criteria=CRITERIA
    )
    u1 = User.objects.create_user(email="u1@example.com")
    u2 = User.objects.create_user(email="u2@example.com")
    e1 = Enrollment.objects.create(user=u1, cohort=cohort)
    e2 = Enrollment.objects.create(user=u2, cohort=cohort)
    s1 = ProjectSubmission.objects.create(
        project=project, student=u1, enrollment=e1, github_link="https://github.com/a/b"
    )
    s2 = ProjectSubmission.objects.create(
        project=project, student=u2, enrollment=e2, github_link="https://github.com/c/d"
    )
    review = PeerReview.objects.create(submission_under_evaluation=s1, reviewer=s2, note_to_peer="")

    assert save_draft(review, CRITERIA, QueryDict("criterion-extras=0&feedback=Nice")) is True
    review.refresh_from_db()
    assert review.criteria_scores == {"extras": [0]}
    assert review.note_to_peer == "Nice"
    assert review.state == PeerReviewState.TO_REVIEW.value

    form_missing, complete = save_review(review, CRITERIA, QueryDict("criterion-extras=0"))
    assert complete is False
    assert form_missing["missing_titles"] == ["Code quality"]
    assert "Code quality" in missing_criteria_message(form_missing["missing_titles"])

    form_ok, complete = save_review(
        review, CRITERIA, QueryDict("criterion-code=1&criterion-extras=0&feedback=Great+work")
    )
    assert complete is True
    assert form_ok["total"] == 3
    review.refresh_from_db()
    assert review.state == PeerReviewState.SUBMITTED.value
    assert review.submitted_at is not None
    assert review.note_to_peer == "Great work"
    assert save_draft(review, CRITERIA, QueryDict("feedback=Ignored")) is False

    ro = evaluation_form(CRITERIA, review.criteria_scores, readonly=True)
    assert ro["readonly"] is True
    assert ro["rows"][0]["options"][1]["checked"] is True
