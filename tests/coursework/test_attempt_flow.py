"""Pure attempt-flow helpers: sidebar items, phases, rows, criteria page, review heading."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from django.http import QueryDict

from community_base.coursework.attempt_flow import (
    FEEDBACK_PAGE,
    REVIEW_PAGE,
    SUBMIT_PAGE,
    attempt_nav_items,
    criteria_page_context,
    learner_attempt_phases,
    phase_row,
    review_heading,
)
from community_base.coursework.peer_pseudonym import peer_pseudonym
from community_base.coursework.peer_review_form import autosave, evaluation_form
from community_base.coursework.project_criteria import criteria_summary, normalize_stored_criteria

NOW = datetime(2027, 1, 20, tzinfo=UTC)
CRITERIA = [
    {
        "id": "system",
        "title": "System",
        "description": "",
        "type": "scale",
        "options": [{"points": 0, "text": "No"}, {"points": 2, "text": "Yes"}],
    }
]


def _project(pk=1, state="PR", criteria=CRITERIA):
    return SimpleNamespace(
        pk=pk,
        state=state,
        is_self_paced=False,
        submission_due_date=NOW - timedelta(days=5),
        peer_review_due_date=NOW + timedelta(days=2),
        criteria=criteria,
    )


def _submission(pk, student_id, description=""):
    return SimpleNamespace(pk=pk, student_id=student_id, description=description)


def _review(pk, submission, complete=False, scores=None):
    return SimpleNamespace(
        pk=pk,
        submission_under_evaluation=submission,
        state="SU" if complete else "TR",
        criteria_scores=scores if scores is not None else ({"system": 1} if complete else {}),
    )


def _phases(projects, **kwargs):
    return learner_attempt_phases(projects, criteria_for=lambda p: p.criteria, now=NOW, **kwargs)


def test_nav_items_list_submit_reviews_with_pseudonyms_and_mark_current():
    project = _project()
    mine = _submission(10, student_id=1)
    reviews = [_review(100, _submission(11, 2), complete=True), _review(101, _submission(12, 3))]
    phase = _phases([project], submissions={1: mine}, assigned={1: reviews}, received={})[1]

    items = attempt_nav_items(
        phase,
        has_submission=True,
        assigned_reviews=reviews,
        course_id=7,
        submit_url="/submit",
        review_url=lambda review: f"/eval/{review.pk}",
        feedback_url="/results",
        page=REVIEW_PAGE,
        current_review_id=101,
    )

    assert [item.title for item in items] == [
        "Submit",
        f"Review 1: {peer_pseudonym(2, 7)}",
        f"Review 2: {peer_pseudonym(3, 7)}",
    ]
    assert [item.done for item in items] == [True, True, False]
    assert [item.current for item in items] == [False, False, True]
    assert items[2].url == "/eval/101"


def test_nav_items_add_feedback_only_in_feedback_phase():
    project = _project(state="CO")
    mine = _submission(10, student_id=1)
    phase = _phases([project], submissions={1: mine}, assigned={}, received={})[1]
    items = attempt_nav_items(
        phase,
        has_submission=True,
        assigned_reviews=[],
        course_id=7,
        submit_url="/submit",
        review_url=str,
        feedback_url="/results",
        page=FEEDBACK_PAGE,
    )
    assert [(item.key, item.current, item.done) for item in items] == [
        ("submit", False, True),
        ("feedback", True, True),
    ]

    open_phase = _phases([_project(state="CS")], submissions={}, assigned={}, received={})[1]
    items = attempt_nav_items(
        open_phase,
        has_submission=False,
        assigned_reviews=[],
        course_id=7,
        submit_url="/submit",
        review_url=str,
        feedback_url="/results",
        page=SUBMIT_PAGE,
    )
    assert [(item.key, item.current, item.done) for item in items] == [("submit", True, False)]


def test_phases_score_received_reviews_and_ignore_incomplete_answers():
    project = _project(state="CO")
    mine = _submission(10, student_id=1)
    received = {
        10: [
            _review(200, mine, complete=True, scores={"system": 1}),
            _review(201, mine, complete=True, scores={}),  # missing a required answer
        ]
    }
    phases = _phases([project], submissions={1: mine}, assigned={}, received=received)
    assert phases[1].badge_label == "2 points"
    assert phases[1].results_final is True


def test_phase_row_links_reviews_page_during_review_and_nothing_when_missed():
    reviews = [_review(100, _submission(11, 2))]
    phase = _phases(
        [_project()], submissions={1: _submission(10, 1)}, assigned={1: reviews}, received={}
    )[1]
    row = phase_row(phase, submit_url="/submit", reviews_url="/eval")
    assert row["status"] == "Review 0/1"
    assert row["url"] == "/eval"
    assert row["action"] == "Start reviews"
    assert row["when"] == NOW + timedelta(days=2)

    missed = _phases([_project()], submissions={}, assigned={}, received={})[1]
    assert phase_row(missed, submit_url="/submit", reviews_url="/eval")["url"] == ""


def test_criteria_page_uses_first_attempt_with_criteria_and_points_to_open_attempt():
    first, second = _project(1, state="CS", criteria=[]), _project(2, state="CS")
    phases = _phases([first, second], submissions={}, assigned={}, received={})
    page = criteria_page_context([first, second], criteria_for=lambda p: p.criteria, phases=phases)
    assert page["criteria_project"] is second
    assert page["open_project"] is first
    assert page["project_criteria"]["totals_label"] == "up to 2 points"
    assert criteria_page_context([first], criteria_for=lambda p: p.criteria) is None


def test_review_heading_names_the_peer_and_carries_the_description():
    review = _review(100, _submission(11, 2, description="  A media agent.  "))
    heading = review_heading(review, 7)
    assert heading["heading"] == f"Evaluate {peer_pseudonym(2, 7)}'s submission"
    assert heading["description"] == "A media agent."


def test_raw_criteria_without_optional_keys_render():
    raw = [{"id": "a", "title": "A", "options": [{"points": 1, "text": "ok"}]}, "junk"]
    normalized = normalize_stored_criteria(raw)
    assert normalized == [
        {
            "id": "a",
            "title": "A",
            "description": "",
            "type": "scale",
            "options": [{"points": 1, "text": "ok"}],
        }
    ]
    assert evaluation_form(raw)["rows"][0]["description"] == ""
    assert criteria_summary(raw)["core_max"] == 1
    assert normalize_stored_criteria(CRITERIA) == CRITERIA


class _Review(SimpleNamespace):
    def save(self, update_fields):
        self.saved_fields = update_fields


def test_autosave_reports_saved_then_submitted():
    review = _Review(state="TR", criteria_scores={}, note_to_peer="")
    data = QueryDict("criterion-system=1&note_to_peer=Nice")
    assert autosave(review, CRITERIA, data) == {"saved": True}
    assert review.criteria_scores == {"system": 1}
    assert review.note_to_peer == "Nice"

    review.state = "SU"
    assert autosave(review, CRITERIA, data) == {"saved": False, "submitted": True}


def test_review_assigned_email_accepts_site_review_objects(monkeypatch):
    """A site project names its cohort FK ``course`` and its reviews have no batch."""
    from community_base.coursework import notifications

    sent = []
    monkeypatch.setattr(notifications, "send", lambda *args, **kwargs: sent.append((args, kwargs)))
    monkeypatch.setattr(
        notifications.hooks, "review_url_builder", lambda project, review: "/eval", raising=False
    )
    cohort = SimpleNamespace(slug="mediagen-2026", course=SimpleNamespace(slug="mediagen"))
    project = SimpleNamespace(
        slug="attempt-1", title="Attempt 1", course=cohort, peer_review_due_date=NOW
    )
    reviewer = SimpleNamespace(student=SimpleNamespace(email="peer@example.test"))
    submission = SimpleNamespace(project=project)
    reviews = [
        SimpleNamespace(
            id=pk, reviewer_id=9, reviewer=reviewer, submission_under_evaluation=submission
        )
        for pk in (5, 6)
    ]

    class _Atomic:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(notifications.transaction, "atomic", _Atomic)
    assert notifications.send_review_assigned_notifications(reviews) == 1
    args, _kwargs = sent[0]
    assert args[0] == notifications.REVIEW_ASSIGNED_PURPOSE
    assert args[2]["cohort_slug"] == "mediagen-2026"
    assert args[2]["review_count"] == 2
