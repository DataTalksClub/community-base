"""Tests for the YAML criteria peer-review evaluation form."""

from django.http import QueryDict

from community_base.coursework.peer_review_form import (
    evaluation_form,
    missing_criteria_message,
    save_draft,
    save_review,
)
from community_base.coursework.project_criteria import parse_criteria

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


class _PackageReviewStub:
    def __init__(self):
        self.criteria_scores = {}
        self.note_to_peer = ""
        self.state = "TR"
        self.submitted_at = None
        self.saved_fields = []

    def save(self, update_fields=None):
        self.saved_fields.append(list(update_fields or []))


class _SiteReviewStub:
    def __init__(self):
        self.criteria_scores = {}
        self.feedback = ""
        self.is_complete = False
        self.completed_at = None
        self.saved_fields = []

    def save(self, update_fields=None):
        self.saved_fields.append(list(update_fields or []))


def test_save_draft_and_save_review_on_package_review_shape():
    review = _PackageReviewStub()

    assert save_draft(review, CRITERIA, QueryDict("criterion-extras=0&feedback=Nice")) is True
    assert review.criteria_scores == {"extras": [0]}
    assert review.note_to_peer == "Nice"
    assert review.state == "TR"

    form_missing, complete = save_review(review, CRITERIA, QueryDict("criterion-extras=0"))
    assert complete is False
    assert form_missing["missing_titles"] == ["Code quality"]
    assert "Code quality" in missing_criteria_message(form_missing["missing_titles"])

    form_ok, complete = save_review(
        review, CRITERIA, QueryDict("criterion-code=1&criterion-extras=0&feedback=Great+work")
    )
    assert complete is True
    assert form_ok["total"] == 3
    assert review.state == "SU"
    assert review.submitted_at is not None
    assert review.note_to_peer == "Great work"
    assert save_draft(review, CRITERIA, QueryDict("feedback=Ignored")) is False

    ro = evaluation_form(CRITERIA, review.criteria_scores, readonly=True)
    assert ro["readonly"] is True
    assert ro["rows"][0]["options"][1]["checked"] is True


def test_save_draft_and_save_review_on_site_review_shape():
    review = _SiteReviewStub()

    assert save_draft(review, CRITERIA, QueryDict("criterion-extras=0&feedback=Draft")) is True
    assert review.feedback == "Draft"
    assert review.is_complete is False

    form_ok, complete = save_review(review, CRITERIA, QueryDict("criterion-code=1&feedback=Done"))
    assert complete is True
    assert form_ok["total"] == 2
    assert review.is_complete is True
    assert review.completed_at is not None
    assert review.feedback == "Done"
    assert save_draft(review, CRITERIA, QueryDict("feedback=Ignored")) is False
