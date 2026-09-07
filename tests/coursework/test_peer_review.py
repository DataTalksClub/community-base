import datetime

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.models import (
    CriteriaResponse,
    PeerReview,
    ProjectCriteriaAssignment,
    ProjectEvaluationScore,
    ProjectState,
    ProjectSubmission,
    ReviewCriteria,
    ReviewCriteriaTypes,
)
from community_base.coursework.projects import submit_project
from community_base.coursework.review import (
    ProjectActionStatus,
    ProjectCriteriaValidationError,
    add_volunteer_peer_review,
    assign_peer_reviews_for_project,
    calculate_project_score,
    ensure_volunteer_reviewer_submission,
    remove_volunteer_peer_review,
    score_project,
    submit_peer_review,
)
from community_base.coursework.statistics import calculate_project_statistics
from tests.coursework.test_models import coursework_cohort, enrollment_for
from tests.coursework.test_projects import lip_links, make_project

pytestmark = pytest.mark.django_db

TOP_OPTION = "2"  # answer index 2 -> option score 6
LOW_OPTION = "1"  # answer index 1 -> option score 0


def make_criteria(project, description="Quality", position=0):
    criteria = ReviewCriteria.objects.create(
        description=description,
        options=[{"criteria": "Poor", "score": 0}, {"criteria": "Good", "score": 6}],
        review_criteria_type=ReviewCriteriaTypes.RADIO_BUTTONS.value,
    )
    ProjectCriteriaAssignment.objects.create(project=project, criteria=criteria, position=position)
    return criteria


def make_submissions(project, cohort, count, prefix="learner"):
    submissions = []
    for index in range(count):
        user, enrollment = enrollment_for(cohort, email=f"{prefix}{index}@example.com")
        submission, _created = submit_project(
            project,
            enrollment,
            github_link="https://github.com/example/repo",
            commit_id="a" * 40,
            learning_in_public_links=lip_links(2),
            faq_contribution_url="https://example.com/faq",
        )
        submissions.append(submission)
    return submissions


def close_review_window(project):
    project.peer_review_due_date = timezone.now() - datetime.timedelta(days=1)
    project.save()


def submit_all_reviews(project, skip=None, links=("https://example.com/watch",)):
    criteria_ids = [criteria.id for criteria in project.criteria_for_project()]
    for review in PeerReview.objects.filter(submission_under_evaluation__project=project):
        if skip is not None and review.id == skip.id:
            continue
        submit_peer_review(
            review,
            {criteria_id: TOP_OPTION for criteria_id in criteria_ids},
            learning_in_public_links=list(links),
            time_spent_reviewing=1.5,
            note_to_peer="well done",
        )


def test_assign_peer_reviews_preconditions():
    cohort = coursework_cohort()
    project = make_project(cohort)
    make_submissions(project, cohort, 3)

    status, message = assign_peer_reviews_for_project(project)
    assert status is ProjectActionStatus.FAIL
    assert "submission due date is in the future" in message

    project.submission_due_date = timezone.now() - datetime.timedelta(days=1)
    project.state = ProjectState.PEER_REVIEWING.value
    project.save()
    status, message = assign_peer_reviews_for_project(project)
    assert status is ProjectActionStatus.FAIL
    assert "COLLECTING_SUBMISSIONS" in message

    project.state = ProjectState.COLLECTING_SUBMISSIONS.value
    project.number_of_peers_to_evaluate = 3
    project.save()
    status, message = assign_peer_reviews_for_project(project)
    assert status is ProjectActionStatus.FAIL
    assert "Not enough submissions" in message
    assert PeerReview.objects.count() == 0


def test_assign_peer_reviews_builds_required_graph_excluding_volunteers():
    cohort = coursework_cohort()
    project = make_project(
        cohort,
        number_of_peers_to_evaluate=2,
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
    )
    real_submissions = make_submissions(project, cohort, 4)
    volunteer = User.objects.create_user(email="early-volunteer@example.com")
    ensure_volunteer_reviewer_submission(project, volunteer)

    status, message = assign_peer_reviews_for_project(project)

    assert status is ProjectActionStatus.OK
    assert "PEER_REVIEWING" in message
    project.refresh_from_db()
    assert project.state == ProjectState.PEER_REVIEWING.value
    assert project.peer_review_due_date > timezone.now()

    real_ids = {submission.id for submission in real_submissions}
    reviews = PeerReview.objects.filter(submission_under_evaluation__project=project)
    assert reviews.count() == 8
    assert all(review.optional is False for review in reviews)
    assert all(review.submission_under_evaluation_id in real_ids for review in reviews)
    assert all(review.reviewer_id in real_ids for review in reviews)
    assert all(review.submission_under_evaluation_id != review.reviewer_id for review in reviews)
    for submission_id in real_ids:
        targets = {
            review.submission_under_evaluation_id
            for review in reviews
            if review.reviewer_id == submission_id
        }
        assert len(targets) == 2


def test_project_flow_assigns_reviews_scores_and_computes_statistics():
    cohort = coursework_cohort()
    project = make_project(
        cohort,
        number_of_peers_to_evaluate=2,
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
    )
    make_criteria(project)
    make_criteria(project, description="Impact", position=1)
    submissions = make_submissions(project, cohort, 3)

    with pytest.raises(ValueError):
        calculate_project_statistics(project)

    status, _message = assign_peer_reviews_for_project(project)
    assert status is ProjectActionStatus.OK
    submit_all_reviews(project)

    close_review_window(project)
    status, message = score_project(project)
    assert status is ProjectActionStatus.OK
    project.refresh_from_db()
    assert project.state == ProjectState.COMPLETED.value

    for submission in submissions:
        submission.refresh_from_db()
        assert submission.project_score == 12
        assert submission.peer_review_score == 6
        assert submission.project_learning_in_public_score == 2
        assert submission.peer_review_learning_in_public_score == 2
        assert submission.project_faq_score == 1
        assert submission.total_score == 23
        assert submission.reviewed_enough_peers is True
        assert submission.passed is True

    evaluation_scores = ProjectEvaluationScore.objects.filter(
        submission_id__in=[submission.id for submission in submissions]
    )
    assert evaluation_scores.count() == 6
    assert set(evaluation_scores.values_list("score", flat=True)) == {6}

    stats = calculate_project_statistics(project)
    assert stats.total_submissions == 3
    assert stats.min_total_score == 23
    assert stats.max_total_score == 23
    assert stats.avg_total_score == 23


def test_evaluation_score_is_the_median_of_reviewer_responses():
    cohort = coursework_cohort()
    project = make_project(
        cohort,
        number_of_peers_to_evaluate=2,
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
    )
    criteria = make_criteria(project)
    submissions = make_submissions(project, cohort, 3)
    low_target = submissions[0]

    assign_peer_reviews_for_project(project)
    low_target_answers = [LOW_OPTION, TOP_OPTION]
    low_seen = 0
    for review in PeerReview.objects.filter(submission_under_evaluation__project=project):
        if review.submission_under_evaluation_id == low_target.id:
            answer = low_target_answers[low_seen]
            low_seen += 1
        else:
            answer = TOP_OPTION
        submit_peer_review(review, {criteria.id: answer})

    close_review_window(project)
    status, _message = score_project(project)
    assert status is ProjectActionStatus.OK

    low_target.refresh_from_db()
    assert low_target.project_score == 3  # ceil(median([0, 6]))
    assert low_target.passed is False


def test_reviewers_who_skip_a_required_review_do_not_pass():
    cohort = coursework_cohort()
    project = make_project(
        cohort,
        number_of_peers_to_evaluate=2,
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
    )
    make_criteria(project)
    make_submissions(project, cohort, 3)

    assign_peer_reviews_for_project(project)
    skipped = PeerReview.objects.filter(submission_under_evaluation__project=project).first()
    submit_all_reviews(project, skip=skipped)

    close_review_window(project)
    status, _message = score_project(project)
    assert status is ProjectActionStatus.OK

    reviewer = ProjectSubmission.objects.get(id=skipped.reviewer_id)
    assert reviewer.peer_review_score == 3  # one mandatory review times points_for_peer_review
    assert reviewer.reviewed_enough_peers is False
    assert reviewer.passed is False


def test_evaluation_falls_back_to_rubric_median_without_reviews():
    cohort = coursework_cohort()
    project = make_project(cohort)
    criteria = make_criteria(project)
    _user, enrollment = enrollment_for(cohort, email="unreviewed@example.com")
    submission = ProjectSubmission.objects.create(
        project=project,
        student=enrollment.user,
        enrollment=enrollment,
        github_link="https://github.com/example/repo",
        commit_id="a" * 40,
    )

    total_score, scores = calculate_project_score(
        submission, list(project.criteria_for_project()), []
    )

    assert total_score == 3  # ceil(median([0, 6]))
    assert scores[0].submission_id == submission.id
    assert scores[0].review_criteria_id == criteria.id
    assert scores[0].score == 3


def test_score_project_refuses_unscoreable_projects():
    cohort = coursework_cohort()
    project = make_project(cohort, submission_due_date=timezone.now() - datetime.timedelta(days=1))
    make_submissions(project, cohort, 4, prefix="scorer")

    cohort.project_passing_score = 0
    cohort.save()
    status, message = score_project(project)
    assert status is ProjectActionStatus.FAIL
    assert "no points to pass" in message

    cohort.project_passing_score = 5
    cohort.save()
    status, message = score_project(project)
    assert status is ProjectActionStatus.FAIL
    assert "not in 'PEER_REVIEWING'" in message

    assign_peer_reviews_for_project(project)
    status, message = score_project(project)
    assert status is ProjectActionStatus.FAIL
    assert "peer review due date is in the future" in message

    close_review_window(project)
    PeerReview.objects.filter(submission_under_evaluation__project=project).delete()
    status, message = score_project(project)
    assert status is ProjectActionStatus.FAIL
    assert "No peer reviews found" in message


def test_submit_peer_review_records_criteria_responses_idempotently():
    cohort = coursework_cohort()
    project = make_project(
        cohort,
        number_of_peers_to_evaluate=2,
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
    )
    criteria = make_criteria(project)
    make_submissions(project, cohort, 3)
    assign_peer_reviews_for_project(project)
    review = PeerReview.objects.filter(submission_under_evaluation__project=project).first()

    submitted = submit_peer_review(
        review,
        {criteria.id: "2,1"},
        learning_in_public_links=["https://example.com/watch"],
        time_spent_reviewing=2.0,
        problems_comments="  none  ",
        note_to_peer="  nice work  ",
    )

    assert submitted.state == "SU"
    assert submitted.submitted_at is not None
    assert submitted.learning_in_public_links == ["https://example.com/watch"]
    assert submitted.time_spent_reviewing == 2.0
    assert submitted.problems_comments == "none"
    assert submitted.note_to_peer == "nice work"
    response = CriteriaResponse.objects.get(review=review, criteria=criteria)
    assert response.answer == "2,1"
    assert response.get_score() == 6

    submit_peer_review(review, {criteria.id: "1"})
    assert CriteriaResponse.objects.filter(review=review, criteria=criteria).count() == 1
    assert CriteriaResponse.objects.get(review=review, criteria=criteria).answer == "1"


def test_submit_peer_review_rejects_criteria_outside_the_rubric():
    cohort = coursework_cohort()
    project = make_project(
        cohort,
        number_of_peers_to_evaluate=2,
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
    )
    make_criteria(project)
    make_submissions(project, cohort, 3)
    assign_peer_reviews_for_project(project)
    review = PeerReview.objects.filter(submission_under_evaluation__project=project).first()

    with pytest.raises(ProjectCriteriaValidationError):
        submit_peer_review(review, {"999999": TOP_OPTION})

    review.refresh_from_db()
    assert review.state == "TR"
    assert CriteriaResponse.objects.filter(review=review).count() == 0


def test_volunteer_peer_review_flow():
    cohort = coursework_cohort()
    project = make_project(
        cohort,
        number_of_peers_to_evaluate=2,
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
    )
    submissions = make_submissions(project, cohort, 3)
    assign_peer_reviews_for_project(project)
    volunteer = User.objects.create_user(email="volunteer@example.com")
    target = submissions[0]

    review, created = add_volunteer_peer_review(project, volunteer, target)
    assert created is True
    assert review.optional is True
    assert review.reviewer_id != target.id

    volunteer_submission = ProjectSubmission.objects.get(project=project, student=volunteer)
    assert volunteer_submission.volunteer_review_only is True
    assert volunteer_submission.commit_id == "volunteer"

    again, created_again = add_volunteer_peer_review(project, volunteer, target)
    assert created_again is False
    assert again.id == review.id

    with pytest.raises(ValidationError):
        add_volunteer_peer_review(project, volunteer, volunteer_submission)

    assert remove_volunteer_peer_review(project, volunteer, review.id) == 1
    assert remove_volunteer_peer_review(project, volunteer, review.id) == 0


def test_volunteer_review_anchors_on_the_real_submission():
    cohort = coursework_cohort()
    project = make_project(
        cohort,
        number_of_peers_to_evaluate=2,
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
    )
    submissions = make_submissions(project, cohort, 3)
    assign_peer_reviews_for_project(project)
    learner = submissions[0].student
    other = submissions[1]

    reviewer_submission = ensure_volunteer_reviewer_submission(project, learner)
    assert reviewer_submission.id == submissions[0].id
    assert ProjectSubmission.objects.filter(project=project, student=learner).count() == 1

    review, created = add_volunteer_peer_review(project, learner, other)
    assert created is True
    assert review.optional is True
    assert review.reviewer_id == submissions[0].id

    with pytest.raises(ValidationError):
        add_volunteer_peer_review(project, learner, submissions[0])
    assert PeerReview.objects.filter(reviewer_id=submissions[0].id, optional=True).count() == 1

    assert remove_volunteer_peer_review(project, learner, review.id) == 1
    assert ProjectSubmission.objects.filter(project=project, student=learner).count() == 1
