"""Learner views for the coursework flows: homework, project, peer review, leaderboard, certificate.

Donor mapping: ``courses/views/homework.py`` (homework form),
``courses/views/project.py`` (project submission),
``courses/views/project_eval.py`` and ``project_eval_submit.py`` (peer
review list, submit, volunteer add and delete) and
``courses/views/course_leaderboard.py`` (leaderboard, score breakdown,
complaint). The donor context keys recorded in
``docs/plan/evidence/c5.2d-learner-views-donors.md`` are the template
contract. The package has no separate course-family model, so the
``course_family`` context key carries the cohort's ``Course``. Donor
``record_event`` observability, emails and datamailer syncs stay site-side:
sites wire them to the coursework hooks. The donor's operator certificate
endpoint stays in each site's compatibility API.
"""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from community_base.coursework import certificates, leaderboard, projects, submissions, votes
from community_base.coursework import review as peer_reviews
from community_base.coursework.models import (
    Homework,
    HomeworkState,
    LeaderboardComplaint,
    PeerReview,
    PeerReviewState,
    Project,
    ProjectState,
    ProjectSubmission,
    Submission,
)
from community_base.curriculum.models import Cohort, Enrollment

CRITERIA_ANSWER_PREFIX = "criteria_"
ANSWER_PREFIX = "answer_"


def _cohort_or_404(course_slug: str, cohort_identifier: str) -> Cohort:
    return get_object_or_404(Cohort, course__slug=course_slug, slug=cohort_identifier)


def _page_context(cohort: Cohort) -> dict:
    return {"course": cohort.course, "course_family": cohort.course}


def _active_enrollment(cohort: Cohort, user):
    return (
        Enrollment.objects.filter(cohort=cohort, user=user, unenrolled_at__isnull=True)
        .order_by("id")
        .first()
    )


def _answers_from_post(post) -> dict[int, str]:
    """Parse ``answer_<question_id>`` POST fields; malformed ids are skipped."""

    answers = {}
    for key, value in post.items():
        if not key.startswith(ANSWER_PREFIX):
            continue
        try:
            answers[int(key[len(ANSWER_PREFIX) :])] = value
        except ValueError:
            continue
    return answers


def _optional_float(value):
    if value in (None, ""):
        return None
    return float(value)


def _homework_navigation(homework) -> tuple:
    siblings = list(Homework.objects.filter(cohort=homework.cohort).order_by("id"))
    position = siblings.index(homework)
    previous_homework = siblings[position - 1] if position > 0 else None
    next_homework = siblings[position + 1] if position + 1 < len(siblings) else None
    return previous_homework, next_homework


def homework_view(request, course_slug: str, cohort_identifier: str, homework_slug: str):
    """Homework form; public GET, learner POST, anonymous renders the disabled page."""

    cohort = _cohort_or_404(course_slug, cohort_identifier)
    homework = get_object_or_404(Homework, cohort=cohort, slug=homework_slug)
    accepting_submissions = homework.state == HomeworkState.OPEN.value
    deadline_passed = homework.due_date < timezone.now()
    previous_homework, next_homework = _homework_navigation(homework)
    context = {
        **_page_context(cohort),
        "homework": homework,
        "instructions_url": homework.instructions_url,
        "homework_module": None,
        "previous_homework": previous_homework,
        "next_homework": next_homework,
        "accepting_submissions": accepting_submissions,
        "deadline_passed": deadline_passed,
    }

    if not request.user.is_authenticated:
        # Donor parity: anonymous GET and anonymous POST both render the
        # disabled page; no enrollment and no submission are created.
        question_answers = [(question, None) for question in homework.questions.order_by("id")]
        return render(
            request,
            "coursework/homework.html",
            {
                **context,
                "question_answers": question_answers,
                "is_authenticated": False,
                "disabled": True,
            },
        )

    if request.method == "POST":
        submission = submissions.submit_homework(
            homework,
            request.user,
            answers_by_question_id=_answers_from_post(request.POST),
        )
        if submission is None:
            # Donor parity: the state guard rejects the POST with an error
            # message and redirects back to the homework page.
            messages.error(request, "This homework is closed and no longer accepts submissions.")
        else:
            messages.success(request, "Your submission was saved.")
        return redirect("coursework_homework", course_slug, cohort_identifier, homework_slug)

    enrollment = _active_enrollment(cohort, request.user)
    submission = (
        Submission.objects.filter(homework=homework, student=request.user)
        .select_related("enrollment")
        .first()
    )
    answers_by_question = (
        {answer.question_id: answer for answer in submission.answers.all()}
        if submission is not None
        else {}
    )
    question_answers = [
        (question, answers_by_question.get(question.id))
        for question in homework.questions.order_by("id")
    ]
    return render(
        request,
        "coursework/homework.html",
        {
            **context,
            "question_answers": question_answers,
            "is_authenticated": True,
            "disabled": not accepting_submissions,
            "submission": submission,
            "disable_learning_in_public": (
                enrollment.disable_learning_in_public if enrollment is not None else False
            ),
        },
    )


def project_view(request, course_slug: str, cohort_identifier: str, project_slug: str):
    """Project submission; public GET, authenticated POST, closed gate re-renders."""

    cohort = _cohort_or_404(course_slug, cohort_identifier)
    project = get_object_or_404(Project, cohort=cohort, slug=project_slug)
    accepting_submissions = project.state == ProjectState.COLLECTING_SUBMISSIONS.value

    enrollment = None
    submission = None
    if request.user.is_authenticated:
        # Donor parity: unlike the homework page, an authenticated GET
        # get-or-creates the enrollment.
        enrollment, _created = leaderboard.ensure_enrollment(cohort, request.user)
        submission = projects.learner_submission_for(project, request.user)

    if request.method == "POST":
        if not request.user.is_authenticated:
            messages.error(request, "Sign in to submit this project.")
        elif not accepting_submissions:
            messages.error(request, "The submission form is closed.")
        elif request.POST.get("action") == "delete":
            if projects.delete_project_submission(project, request.user):
                messages.success(request, "Your submission was deleted.")
            return redirect("coursework_project", course_slug, cohort_identifier, project_slug)
        else:
            try:
                submission, _created = projects.submit_project(
                    project,
                    enrollment,
                    github_link=request.POST.get("github_link", ""),
                    commit_id=request.POST.get("commit_id", ""),
                )
            except ValidationError:
                messages.error(request, "The submission could not be saved.")
            else:
                messages.success(request, "Your submission was saved.")
                return redirect("coursework_project", course_slug, cohort_identifier, project_slug)

    certificate_name = ""
    if enrollment is not None:
        certificate_name = enrollment.certificate_name or enrollment.display_name
    return render(
        request,
        "coursework/project.html",
        {
            **_page_context(cohort),
            "project": project,
            "submission": submission,
            "has_submission": submission is not None,
            "is_authenticated": request.user.is_authenticated,
            "disabled": not accepting_submissions,
            "accepting_submissions": accepting_submissions,
            "certificate_name": certificate_name,
            "disable_learning_in_public": (
                enrollment.disable_learning_in_public if enrollment is not None else False
            ),
        },
    )


def _learner_reviews(project, user):
    return PeerReview.objects.filter(
        reviewer__student=user,
        submission_under_evaluation__project=project,
    ).order_by("optional", "id")


def projects_eval_view(request, course_slug: str, cohort_identifier: str, project_slug: str):
    """Peer review list; public GET, personalized when signed in."""

    cohort = _cohort_or_404(course_slug, cohort_identifier)
    project = get_object_or_404(Project, cohort=cohort, slug=project_slug)
    context = {
        **_page_context(cohort),
        "project": project,
        "eval_closed": project.state != ProjectState.PEER_REVIEWING.value,
    }
    if not request.user.is_authenticated:
        return render(request, "coursework/eval.html", {**context, "is_authenticated": False})

    reviews = list(_learner_reviews(project, request.user))
    assigned_reviews = [review for review in reviews if not review.optional]
    selected_reviews = [review for review in reviews if review.optional]
    return render(
        request,
        "coursework/eval.html",
        {
            **context,
            "is_authenticated": True,
            "reviews": reviews,
            "assigned_reviews": assigned_reviews,
            "selected_reviews": selected_reviews,
            "number_of_completed_evaluation": sum(
                1 for review in assigned_reviews if review.state == PeerReviewState.SUBMITTED.value
            ),
            "has_submission": projects.learner_submission_for(project, request.user) is not None,
        },
    )


def _eval_submit_context(request, cohort, project, review) -> dict:
    enrollment = _active_enrollment(cohort, request.user)
    criteria = list(project.criteria_for_project())
    responses = {response.criteria_id: response for response in review.criteria_responses.all()}
    vote_counts = votes.get_project_vote_counts(request.user, cohort)
    return {
        **_page_context(cohort),
        "project": project,
        "review": review,
        "submission": review.submission_under_evaluation,
        "criteria_response_pairs": [
            (criterion, responses.get(criterion.id)) for criterion in criteria
        ],
        "accepting_submissions": project.state == ProjectState.PEER_REVIEWING.value,
        "disabled": project.state != ProjectState.PEER_REVIEWING.value,
        "disable_learning_in_public": (
            enrollment.disable_learning_in_public if enrollment is not None else False
        ),
        "voted_submission_ids": votes.get_voted_submission_ids(request.user, cohort),
        "vote_limit_reached": vote_counts.get(project.id, 0) >= votes.PROJECT_VOTES_PER_PROJECT,
        "project_votes_per_project": votes.PROJECT_VOTES_PER_PROJECT,
    }


@login_required
def projects_eval_submit(
    request, course_slug: str, cohort_identifier: str, project_slug: str, review_id: int
):
    """Peer review submit; ownership check, closed gate, vote action."""

    cohort = _cohort_or_404(course_slug, cohort_identifier)
    project = get_object_or_404(Project, cohort=cohort, slug=project_slug)
    review = get_object_or_404(
        PeerReview, id=review_id, submission_under_evaluation__project=project
    )

    if review.reviewer.student_id != request.user.id:
        messages.error(request, "This review is not yours to submit.")
        return redirect("coursework_projects_eval", course_slug, cohort_identifier, project_slug)

    if request.method == "POST" and request.POST.get("form_action") == "vote":
        votes.update_project_vote(
            request.user,
            review.submission_under_evaluation,
            action=request.POST.get("vote_action", "vote"),
        )
        return redirect(
            "coursework_projects_eval_submit",
            course_slug,
            cohort_identifier,
            project_slug,
            review_id,
        )

    if request.method == "POST":
        if project.state != ProjectState.PEER_REVIEWING.value:
            messages.error(request, "Peer review is closed for this project.")
        else:
            answers_by_criteria_id = {
                key[len(CRITERIA_ANSWER_PREFIX) :]: value
                for key, value in request.POST.items()
                if key.startswith(CRITERIA_ANSWER_PREFIX)
            }
            try:
                peer_reviews.submit_peer_review(
                    review,
                    answers_by_criteria_id,
                    learning_in_public_links=request.POST.getlist("learning_in_public_links"),
                    time_spent_reviewing=_optional_float(request.POST.get("time_spent_reviewing")),
                    problems_comments=request.POST.get("problems_comments", ""),
                    note_to_peer=request.POST.get("note_to_peer", ""),
                )
            except peer_reviews.ProjectCriteriaValidationError:
                return HttpResponseBadRequest("The review contains an unknown criterion.")
            except (ValidationError, ValueError):
                messages.error(request, "The review could not be saved.")
            else:
                messages.success(request, "Your review was submitted.")
                return redirect(
                    "coursework_projects_eval", course_slug, cohort_identifier, project_slug
                )

    return render(
        request,
        "coursework/eval_submit.html",
        _eval_submit_context(request, cohort, project, review),
    )


@login_required
def projects_eval_add(
    request, course_slug: str, cohort_identifier: str, project_slug: str, submission_id: int
):
    """Add one optional volunteer review for another learner's submission."""

    cohort = _cohort_or_404(course_slug, cohort_identifier)
    project = get_object_or_404(Project, cohort=cohort, slug=project_slug)
    submission_under_evaluation = get_object_or_404(
        ProjectSubmission, id=submission_id, project=project
    )
    try:
        _review, created = peer_reviews.add_volunteer_peer_review(
            project, request.user, submission_under_evaluation
        )
    except ValidationError:
        messages.error(request, "You cannot review your own submission.")
    else:
        messages.success(
            request,
            "Review added." if created else "You already review this submission.",
        )
    return redirect("coursework_projects_eval", course_slug, cohort_identifier, project_slug)


@login_required
def projects_eval_delete(
    request, course_slug: str, cohort_identifier: str, project_slug: str, review_id: int
):
    """Remove one of the caller's optional volunteer reviews."""

    cohort = _cohort_or_404(course_slug, cohort_identifier)
    project = get_object_or_404(Project, cohort=cohort, slug=project_slug)
    if not peer_reviews.remove_volunteer_peer_review(project, request.user, review_id):
        messages.error(request, "That review could not be removed.")
    return redirect("coursework_projects_eval", course_slug, cohort_identifier, project_slug)


def leaderboard_view(request, course_slug: str, cohort_identifier: str):
    """Public paginated leaderboard, personalized when signed in."""

    cohort = _cohort_or_404(course_slug, cohort_identifier)
    context = leaderboard.leaderboard_context(cohort, request.user, request.GET.get("page"))
    return render(
        request,
        "coursework/leaderboard.html",
        {
            **_page_context(cohort),
            **context,
            "enrollments": context["page_obj"].object_list,
            "total_enrollments": context["page_obj"].paginator.count,
        },
    )


def leaderboard_score_breakdown_view(
    request, course_slug: str, cohort_identifier: str, enrollment_id: int
):
    """Public per-enrollment score breakdown."""

    cohort = _cohort_or_404(course_slug, cohort_identifier)
    enrollment = get_object_or_404(Enrollment, id=enrollment_id, cohort=cohort)
    context = leaderboard.leaderboard_score_breakdown_context(enrollment, request.user)
    return render(
        request,
        "coursework/leaderboard_score_breakdown.html",
        {**_page_context(cohort), **context},
    )


@login_required
def leaderboard_complaint_view(
    request, course_slug: str, cohort_identifier: str, enrollment_id: int
):
    """File a leaderboard complaint for one enrollment; redirects to the breakdown."""

    cohort = _cohort_or_404(course_slug, cohort_identifier)
    enrollment = get_object_or_404(Enrollment, id=enrollment_id, cohort=cohort)
    error = None
    if request.method == "POST":
        try:
            leaderboard.file_leaderboard_complaint(
                enrollment,
                request.user,
                issue_type=request.POST.get("issue_type", ""),
                description=request.POST.get("description", ""),
            )
        except ValidationError:
            error = "The complaint could not be saved."
        else:
            messages.success(request, "Your report was received.")
            return redirect(
                "coursework_leaderboard_score_breakdown",
                course_slug,
                cohort_identifier,
                enrollment_id,
            )
    return render(
        request,
        "coursework/leaderboard_complaint.html",
        {
            **_page_context(cohort),
            "enrollment": enrollment,
            "error": error,
            "issue_types": LeaderboardComplaint.IssueType.choices,
        },
    )


@require_POST
@login_required
def enrollment_preferences_toggle(request, course_slug: str, cohort_identifier: str):
    """Donor JSON toggle: ``{"field", "value"}`` or ``400 {"error": ...}``."""

    cohort = _cohort_or_404(course_slug, cohort_identifier)
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)
    field = payload.get("field")
    value = payload.get("value")
    if isinstance(value, bool):
        value = "true" if value else "false"
    try:
        _enrollment, enabled, _changed = leaderboard.set_enrollment_preference(
            cohort, request.user, field, value
        )
    except ValueError:
        return JsonResponse({"error": f"Unknown enrollment preference field: {field}"}, status=400)
    except Enrollment.DoesNotExist:
        return JsonResponse({"error": "No active enrollment in this cohort."}, status=400)
    return JsonResponse({"field": field, "value": enabled})


@login_required
def certificate_view(request, course_slug: str, cohort_identifier: str):
    """The signed-in learner's certificate; ``Certificate`` row first, legacy url fallback."""

    cohort = _cohort_or_404(course_slug, cohort_identifier)
    enrollment = get_object_or_404(
        Enrollment, cohort=cohort, user=request.user, unenrolled_at__isnull=True
    )
    certificate = certificates.certificate_for_enrollment(enrollment)
    certificate_url = certificate.url if certificate is not None else enrollment.certificate_url
    return render(
        request,
        "coursework/certificate.html",
        {
            **_page_context(cohort),
            "enrollment": enrollment,
            "certificate": certificate,
            "certificate_url": certificate_url,
        },
    )
