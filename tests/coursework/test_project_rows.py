"""C5.2k: CMP's per-project learner row, for every state by submitted combination."""

import datetime

import pytest
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.utils import timezone

from community_base.coursework.models import (
    PeerReview,
    PeerReviewBatch,
    PeerReviewState,
    ProjectState,
    ProjectSubmission,
    SubmissionReviewState,
)
from community_base.coursework.project_rows import project_row, project_rows_for_cohort
from tests.coursework.test_models import coursework_cohort, enrollment_for
from tests.coursework.test_projects import make_project

pytestmark = pytest.mark.django_db

CL = ProjectState.CLOSED.value
CS = ProjectState.COLLECTING_SUBMISSIONS.value
PR = ProjectState.PEER_REVIEWING.value
CO = ProjectState.COMPLETED.value


def make_submission(project, email, **values):
    user, enrollment = enrollment_for(project.cohort, email=email)
    values.setdefault("github_link", "https://github.com/example/repo")
    values.setdefault("commit_id", "a" * 40)
    submission = ProjectSubmission.objects.create(
        project=project, student=user, enrollment=enrollment, **values
    )
    return user, submission


def row_summary(row):
    return (
        row.label,
        row.css_class,
        row.surface,
        row.link_target,
        row.deadline_kind,
        row.completed,
        row.score,
    )


# (state, submitted, passed, expected row summary). CMP's labels and badge classes, the pill
# surfaces from DataTalksClub/website's coursework_badges, and CMP's link and deadline columns.
DEADLINE_MODE_CASES = [
    (CL, False, False, ("Closed", "bg-secondary", "past", None, "submission", False, None)),
    (CL, True, False, ("Closed", "bg-secondary", "past", None, "submission", False, None)),
    (CS, False, False, ("Open", "bg-warning", "your_move", "submit", "submission", False, None)),
    (CS, True, False, ("Submitted", "bg-info", "done", "submit", "submission", False, None)),
    (
        PR,
        False,
        False,
        ("Not submitted", "bg-secondary", "past", "eval", "submission", False, None),
    ),
    (PR, True, False, ("Review", "bg-danger", "your_move", "eval", "peer_review", False, None)),
    (
        CO,
        False,
        False,
        ("Not submitted", "bg-secondary", "past", "results", "peer_review", True, None),
    ),
    (CO, True, True, ("Passed (12)", "bg-success", "result", "results", "peer_review", True, 12)),
    (CO, True, False, ("Failed (12)", "bg-secondary", "past", "results", "peer_review", True, 12)),
]


@pytest.mark.parametrize(("state", "submitted", "passed", "expected"), DEADLINE_MODE_CASES)
def test_deadline_mode_row_for_every_state_and_submission(state, submitted, passed, expected):
    project = make_project(coursework_cohort(), state=state)
    submission = None
    if submitted:
        _user, submission = make_submission(
            project, "me@example.com", total_score=12, passed=passed
        )

    row = project_row(project, submission, completed_reviews=0)

    assert row_summary(row) == expected
    assert row.stage == state
    assert row.submitted is submitted


@pytest.mark.parametrize(
    ("state", "submitted", "expected_due"),
    [
        (CS, True, "submission_due_date"),
        (PR, False, "submission_due_date"),
        (PR, True, "peer_review_due_date"),
        (CO, False, "peer_review_due_date"),
    ],
)
def test_deadline_shows_the_date_cmp_shows(state, submitted, expected_due):
    project = make_project(coursework_cohort(), state=state)
    submission = None
    if submitted:
        _user, submission = make_submission(project, "me@example.com")

    row = project_row(project, submission, completed_reviews=0)

    assert row.deadline == getattr(project, expected_due)


@pytest.mark.parametrize(
    ("completed_reviews", "label", "surface"),
    [
        (2, "Review", "your_move"),
        (3, "Review completed", "done"),
        (4, "Review completed", "done"),
    ],
)
def test_review_completes_at_number_of_peers_to_evaluate(completed_reviews, label, surface):
    project = make_project(coursework_cohort(), state=PR, number_of_peers_to_evaluate=3)
    _user, submission = make_submission(project, "me@example.com")

    row = project_row(project, submission, completed_reviews=completed_reviews)

    assert (row.label, row.surface) == (label, surface)
    assert row.link_target == "eval"


def review_by(reviewer, project, index, **values):
    _peer, peer_submission = make_submission(project, f"peer{index}@example.com")
    return PeerReview.objects.create(
        submission_under_evaluation=peer_submission, reviewer=reviewer, **values
    )


def test_builder_counts_only_submitted_required_reviews_toward_the_threshold():
    cohort = coursework_cohort()
    project = make_project(cohort, state=PR, number_of_peers_to_evaluate=3)
    user, mine = make_submission(project, "me@example.com")
    submitted = PeerReviewState.SUBMITTED.value
    review_by(mine, project, 1, state=submitted)
    review_by(mine, project, 2, state=submitted)
    review_by(mine, project, 3, state=submitted, optional=True)
    review_by(mine, project, 4, state=PeerReviewState.TO_REVIEW.value)
    review_by(mine, project, 5, state=PeerReviewState.EXPIRED.value)

    [row] = project_rows_for_cohort(cohort, user)
    assert row.label == "Review"

    review_by(mine, project, 6, state=submitted)
    [row] = project_rows_for_cohort(cohort, user)
    assert row.label == "Review completed"


def test_builder_uses_only_the_learners_own_submission():
    cohort = coursework_cohort()
    project = make_project(cohort, state=CS)
    make_submission(project, "someone-else@example.com")
    me, _enrollment = enrollment_for(cohort, email="me@example.com")

    [row] = project_rows_for_cohort(cohort, me)
    [anonymous_row] = project_rows_for_cohort(cohort, AnonymousUser())

    assert (row.label, row.submitted) == ("Open", False)
    assert (anonymous_row.label, anonymous_row.submitted) == ("Open", False)


def test_builder_resolves_a_link_only_where_the_stage_has_one():
    cohort = coursework_cohort()
    closed = make_project(cohort, slug="closed", state=CL)
    reviewing = make_project(cohort, slug="reviewing", state=PR)
    user, _submission = make_submission(reviewing, "me@example.com")
    calls = []

    def url_for(project, link_target):
        calls.append((project.slug, link_target))
        return f"/{project.slug}/{link_target}/"

    rows = project_rows_for_cohort(cohort, user, url_for=url_for)

    assert [(row.project.slug, row.href) for row in rows] == [
        ("closed", None),
        ("reviewing", "/reviewing/eval/"),
    ]
    assert calls == [("reviewing", "eval")]
    assert closed.id < reviewing.id


def test_builder_query_count_does_not_grow_with_projects(django_assert_num_queries):
    cohort = coursework_cohort()
    user, _submission = make_submission(make_project(cohort, slug="p0", state=PR), "me@example.com")
    with django_assert_num_queries(2):
        project_rows_for_cohort(cohort, user)

    for index in range(1, 5):
        project = make_project(cohort, slug=f"p{index}", state=PR)
        ProjectSubmission.objects.create(
            project=project,
            student=user,
            enrollment=_submission.enrollment,
            github_link="https://github.com/example/repo",
            commit_id="b" * 40,
        )
    with django_assert_num_queries(2):
        rows = project_rows_for_cohort(cohort, user)
    assert len(rows) == 5


def pooled_project(**values):
    cohort = coursework_cohort(slug="pool", mode="self_paced")
    return make_project(cohort, number_of_peers_to_evaluate=2, **values)


# A pooled project's own state is only CS or CL; the learner's review_state carries the rest.
# Self-paced has no submission deadline (#323): no deadline kind until the learner is in a batch
# whose due date is known, and none on a closed project.
POOLED_CASES = [
    (CS, None, ("Open", "your_move", "submit", None)),
    (
        CS,
        SubmissionReviewState.AWAITING_ASSIGNMENT.value,
        ("Submitted", "done", "submit", None),
    ),
    (CS, SubmissionReviewState.IN_REVIEW.value, ("Review", "your_move", "eval", None)),
    (CS, SubmissionReviewState.SCORED.value, ("Passed (9)", "result", "results", "peer_review")),
    (CL, None, ("Closed", "past", None, None)),
    (CL, SubmissionReviewState.SCORED.value, ("Closed", "past", None, None)),
]


@pytest.mark.parametrize(("state", "review_state", "expected"), POOLED_CASES)
def test_pooled_row_follows_the_learners_review_state(state, review_state, expected):
    project = pooled_project(state=state)
    submission = None
    if review_state is not None:
        _user, submission = make_submission(
            project, "me@example.com", review_state=review_state, total_score=9, passed=True
        )

    row = project_row(project, submission, completed_reviews=0)

    assert (row.label, row.surface, row.link_target, row.deadline_kind) == expected


def test_pooled_review_deadline_is_the_learners_batch_due_date():
    project = pooled_project(state=CS)
    user, mine = make_submission(
        project, "me@example.com", review_state=SubmissionReviewState.IN_REVIEW.value
    )
    due_at = timezone.now() + datetime.timedelta(days=3)
    batch = PeerReviewBatch.objects.create(project=project, due_at=due_at)
    review_by(mine, project, 1, batch=batch, state=PeerReviewState.SUBMITTED.value)
    review_by(mine, project, 2, batch=batch)

    [row] = project_rows_for_cohort(project.cohort, user)

    assert (row.label, row.deadline) == ("Review", due_at)
    assert row.deadline != project.peer_review_due_date


def test_row_include_renders_label_surface_and_link():
    cohort = coursework_cohort()
    make_project(cohort, slug="open", title="Open project", state=CS)
    make_project(cohort, slug="shut", title="Closed project", state=CL)
    rows = project_rows_for_cohort(cohort, AnonymousUser(), url_for=lambda p, t: f"/go/{p.slug}/")

    open_html = render_to_string("coursework/_project_row.html", {"row": rows[0]})
    closed_html = render_to_string("coursework/_project_row.html", {"row": rows[1]})

    assert '<a href="/go/open/">Open project</a>' in open_html
    assert '<span class="cb-badge" data-surface="your_move">Open</span>' in open_html
    assert "<a " not in closed_html
    assert '<span class="cb-badge" data-surface="past">Closed</span>' in closed_html
