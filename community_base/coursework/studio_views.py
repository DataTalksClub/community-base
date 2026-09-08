"""Coursework Studio operations (plan issue C5.2e, step 1).

Every mutating route is a staff-gated POST that delegates to the packaged
service (scoring, review, leaderboard, certificates, wrapped) so Studio and
the APIs share one implementation. The donor's Datamailer operations and
deadline extensions stay site-side; they have no package service behind them.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from community_base.accounts.models import User
from community_base.coursework import studio as studio_ops
from community_base.coursework import wrapped as wrapped_stats
from community_base.coursework.certificates import issue_certificate
from community_base.coursework.leaderboard import file_leaderboard_complaint
from community_base.coursework.models import (
    Homework,
    HomeworkState,
    LeaderboardComplaint,
    PeerReview,
    Project,
    ProjectSubmission,
    Question,
    RegistrationCampaign,
    UserWrappedStatistics,
    WrappedStatistics,
)
from community_base.coursework.registration import public_course_registration_count
from community_base.coursework.review import (
    add_volunteer_peer_review,
    remove_volunteer_peer_review,
)
from community_base.coursework.studio_forms import (
    CriteriaAssignmentForm,
    HomeworkForm,
    QuestionForm,
)
from community_base.curriculum.models import Cohort, Enrollment
from community_base.kernel.decorators import staff_required
from community_base.studio.audit import hooks as studio_hooks


def _audit(request, event, target, **metadata):
    studio_hooks.audit_writer(
        event=event,
        actor_ref=str(request.user.pk),
        target_ref=str(target.pk),
        metadata=metadata,
    )


def _result_message(request, result, success_text):
    if result.ok:
        messages.success(request, result.message or success_text)
    else:
        messages.error(request, result.message)


# --- homework, questions and submissions -----------------------------------


@staff_required
def homework_list(request):
    homeworks = Homework.objects.select_related("cohort__course").order_by("due_date")
    cohort_id = request.GET.get("cohort")
    if cohort_id:
        homeworks = homeworks.filter(cohort_id=cohort_id)
    return render(
        request,
        "community_base/coursework/studio/homework_list.html",
        {"homeworks": homeworks, "cohorts": Cohort.objects.select_related("course")},
    )


@staff_required
def homework_create(request, cohort_id):
    cohort = get_object_or_404(Cohort, pk=cohort_id)
    form = HomeworkForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        homework = form.save(commit=False)
        homework.cohort = cohort
        homework.save()
        _audit(request, "coursework.homework.created", homework)
        messages.success(request, "Homework created.")
        return redirect("coursework_studio_homework_detail", homework_id=homework.pk)
    return render(
        request,
        "community_base/coursework/studio/form.html",
        {
            "form": form,
            "kind": "homework",
            "back_url": reverse("coursework_studio_homework_list"),
        },
    )


@staff_required
def homework_detail(request, homework_id):
    homework = get_object_or_404(Homework.objects.select_related("cohort__course"), pk=homework_id)
    return render(
        request,
        "community_base/coursework/studio/homework_detail.html",
        {
            "homework": homework,
            "questions": homework.questions.order_by("id"),
            "submissions": homework.submissions.select_related("student", "enrollment").order_by(
                "id"
            ),
            "states": list(HomeworkState),
        },
    )


@staff_required
def homework_edit(request, homework_id):
    homework = get_object_or_404(Homework, pk=homework_id)
    form = HomeworkForm(request.POST or None, instance=homework)
    if request.method == "POST" and form.is_valid():
        form.save()
        _audit(request, "coursework.homework.updated", homework)
        messages.success(request, "Homework updated.")
        return redirect("coursework_studio_homework_detail", homework_id=homework.pk)
    return render(
        request,
        "community_base/coursework/studio/form.html",
        {
            "form": form,
            "kind": "homework",
            "back_url": reverse("coursework_studio_homework_detail", args=[homework.pk]),
        },
    )


@staff_required
@require_POST
def homework_rescore(request, homework_id):
    homework = get_object_or_404(Homework, pk=homework_id)
    result = studio_ops.rescore_homework(homework, force=request.POST.get("force") == "1")
    _audit(request, "coursework.homework.rescored", homework, ok=result.ok)
    if result.ok:
        messages.success(request, result.message)
    else:
        messages.warning(request, result.message)
    return redirect("coursework_studio_homework_detail", homework_id=homework.pk)


@staff_required
def question_create(request, homework_id):
    homework = get_object_or_404(Homework, pk=homework_id)
    form = QuestionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        question = form.save(commit=False)
        question.homework = homework
        question.save()
        _audit(request, "coursework.question.created", question)
        messages.success(request, "Question created.")
        return redirect("coursework_studio_homework_detail", homework_id=homework.pk)
    return render(
        request,
        "community_base/coursework/studio/form.html",
        {
            "form": form,
            "kind": "question",
            "back_url": reverse("coursework_studio_homework_detail", args=[homework.pk]),
        },
    )


@staff_required
def question_edit(request, question_id):
    question = get_object_or_404(Question, pk=question_id)
    form = QuestionForm(request.POST or None, instance=question)
    if request.method == "POST" and form.is_valid():
        form.save()
        _audit(request, "coursework.question.updated", question)
        messages.success(request, "Question updated.")
        return redirect("coursework_studio_homework_detail", homework_id=question.homework_id)
    return render(
        request,
        "community_base/coursework/studio/form.html",
        {
            "form": form,
            "kind": "question",
            "back_url": reverse("coursework_studio_homework_detail", args=[question.homework_id]),
        },
    )


@staff_required
@require_POST
def question_delete(request, question_id):
    question = get_object_or_404(Question, pk=question_id)
    homework_id = question.homework_id
    question.delete()
    _audit(request, "coursework.question.deleted", type("Target", (), {"pk": question_id})())
    messages.success(request, "Question deleted.")
    return redirect("coursework_studio_homework_detail", homework_id=homework_id)


# --- projects, criteria and peer review administration ---------------------


@staff_required
def project_list(request):
    projects = Project.objects.select_related("cohort__course").order_by("submission_due_date")
    return render(
        request,
        "community_base/coursework/studio/project_list.html",
        {"projects": projects},
    )


@staff_required
def project_detail(request, project_id):
    project = get_object_or_404(Project.objects.select_related("cohort__course"), pk=project_id)
    return render(
        request,
        "community_base/coursework/studio/project_detail.html",
        {
            "project": project,
            "criteria": project.criteria_for_project(),
            "assignments": project.criteria_assignments.select_related("criteria").order_by(
                "position", "id"
            ),
            "reviews": PeerReview.objects.filter(
                submission_under_evaluation__project=project
            ).select_related("reviewer__student", "submission_under_evaluation__student"),
            "submissions": project.submissions.select_related("student").order_by("id"),
            "criteria_form": CriteriaAssignmentForm(),
        },
    )


@staff_required
@require_POST
def project_assign_reviews(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    result = studio_ops.assign_project_reviews(project)
    _audit(request, "coursework.peer_reviews.assigned", project, ok=result.ok)
    _result_message(request, result, "Peer reviews assigned.")
    return redirect("coursework_studio_project_detail", project_id=project.pk)


@staff_required
@require_POST
def project_score(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    result = studio_ops.score_project(project)
    _audit(request, "coursework.project.scored", project, ok=result.ok)
    _result_message(request, result, "Project scored.")
    return redirect("coursework_studio_project_detail", project_id=project.pk)


@staff_required
@require_POST
def criteria_add(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    form = CriteriaAssignmentForm(request.POST)
    if form.is_valid():
        assignment = form.save(commit=False)
        assignment.project = project
        assignment.full_clean()
        assignment.save()
        _audit(request, "coursework.criteria.assigned", project)
        messages.success(request, "Criterion assigned.")
    else:
        messages.error(request, "Choose a criterion and a position.")
    return redirect("coursework_studio_project_detail", project_id=project.pk)


@staff_required
@require_POST
def criteria_remove(request, project_id, assignment_id):
    project = get_object_or_404(Project, pk=project_id)
    project.criteria_assignments.filter(pk=assignment_id).delete()
    _audit(request, "coursework.criteria.removed", project)
    messages.success(request, "Criterion assignment removed.")
    return redirect("coursework_studio_project_detail", project_id=project.pk)


@staff_required
@require_POST
def volunteer_review_add(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    email = request.POST.get("email", "").strip().lower()
    volunteer = User.objects.filter(email__iexact=email).first()
    submission = project.submissions.filter(pk=request.POST.get("submission_id") or 0).first()
    if volunteer is None or submission is None:
        messages.error(request, "No account matches the email or the submission is unknown.")
        return redirect("coursework_studio_project_detail", project_id=project.pk)
    try:
        _review, created = add_volunteer_peer_review(project, volunteer, submission)
    except ValidationError:
        messages.error(request, "A reviewer cannot review their own submission.")
        return redirect("coursework_studio_project_detail", project_id=project.pk)
    _audit(request, "coursework.volunteer_review.added", project, created=created)
    messages.success(request, "Volunteer review added.")
    return redirect("coursework_studio_project_detail", project_id=project.pk)


@staff_required
@require_POST
def volunteer_review_remove(request, project_id, review_id):
    project = get_object_or_404(Project, pk=project_id)
    email = request.POST.get("email", "").strip().lower()
    removed = 0
    submission = ProjectSubmission.objects.filter(
        project=project, student__email__iexact=email
    ).first()
    if submission is not None:
        removed = remove_volunteer_peer_review(project, submission.student, review_id)
    messages.info(request, "Volunteer review removed." if removed else "Nothing removed.")
    return redirect("coursework_studio_project_detail", project_id=project.pk)


# --- leaderboard, complaints, certificates, campaigns, wrapped -------------


@staff_required
def cohort_leaderboard(request, cohort_id):
    cohort = get_object_or_404(Cohort.objects.select_related("course"), pk=cohort_id)
    rows = cohort.enrollments.select_related("user").order_by("position_on_leaderboard", "id")
    return render(
        request,
        "community_base/coursework/studio/cohort_leaderboard.html",
        {"cohort": cohort, "rows": rows},
    )


@staff_required
@require_POST
def leaderboard_recompute(request, cohort_id):
    cohort = get_object_or_404(Cohort, pk=cohort_id)
    result = studio_ops.recompute_leaderboard(cohort)
    _audit(request, "coursework.leaderboard.recomputed", cohort, ok=result.ok)
    messages.success(request, result.message)
    return redirect("coursework_studio_cohort_leaderboard", cohort_id=cohort.pk)


@staff_required
def complaints(request):
    return render(
        request,
        "community_base/coursework/studio/complaints.html",
        {
            "open_complaints": LeaderboardComplaint.objects.filter(resolved=False).select_related(
                "enrollment__user", "enrollment__cohort"
            ),
            "resolved_complaints": LeaderboardComplaint.objects.filter(resolved=True).order_by(
                "-resolved_at"
            )[:25],
        },
    )


@staff_required
@require_POST
def complaint_resolve(request, complaint_id):
    complaint = get_object_or_404(LeaderboardComplaint, pk=complaint_id)
    result = studio_ops.resolve_leaderboard_complaint(complaint, request.user)
    _audit(request, "coursework.complaint.resolved", complaint, ok=result.ok)
    messages.success(request, result.message)
    messages.success(request, "Complaint resolved.")
    return redirect("coursework_studio_complaints")


@staff_required
@require_POST
def complaint_create(request, enrollment_id):
    enrollment = get_object_or_404(
        Enrollment.objects.select_related("user", "cohort"), pk=enrollment_id
    )
    complaint = file_leaderboard_complaint(
        enrollment,
        request.user,
        issue_type=request.POST.get("issue_type") or LeaderboardComplaint.IssueType.OTHER,
        description=request.POST.get("description", ""),
    )
    _audit(request, "coursework.complaint.filed", complaint)
    messages.success(request, "Complaint filed.")
    return redirect("coursework_studio_cohort_leaderboard", cohort_id=enrollment.cohort_id)


@staff_required
def certificates(request, cohort_id):
    cohort = get_object_or_404(Cohort.objects.select_related("course"), pk=cohort_id)
    return render(
        request,
        "community_base/coursework/studio/certificates.html",
        {
            "cohort": cohort,
            "enrollments": cohort.enrollments.select_related("user").order_by("user__email"),
        },
    )


@staff_required
@require_POST
def certificate_issue(request, cohort_id, enrollment_id):
    get_object_or_404(Cohort, pk=cohort_id)
    enrollment = get_object_or_404(Enrollment, pk=enrollment_id, cohort_id=cohort_id)
    certificate, created = issue_certificate(enrollment, url=request.POST.get("url", "").strip())
    _audit(request, "coursework.certificate.issued", certificate, created=created)
    messages.success(request, "Certificate issued." if created else "Certificate updated.")
    return redirect("coursework_studio_certificates", cohort_id=cohort_id)


@staff_required
def campaigns(request):
    rows = [
        (campaign, public_course_registration_count(campaign))
        for campaign in RegistrationCampaign.objects.order_by("title", "slug")
    ]
    return render(
        request,
        "community_base/coursework/studio/campaigns.html",
        {"rows": rows},
    )


@staff_required
def wrapped(request):
    return render(
        request,
        "community_base/coursework/studio/wrapped.html",
        {
            "years": WrappedStatistics.objects.order_by("-year"),
            "user_rows": UserWrappedStatistics.objects.select_related("wrapped", "user")[:25],
        },
    )


@staff_required
@require_POST
def wrapped_recalculate(request):
    year = request.POST.get("year", "")
    try:
        year_value = int(year)
    except (TypeError, ValueError):
        messages.error(request, "Enter a valid year.")
        return redirect("coursework_studio_wrapped")
    wrapped_stats.calculate_wrapped_statistics(year=year_value, force=True)
    _audit(request, "coursework.wrapped.recalculated", type("Target", (), {"pk": year_value})())
    messages.success(request, f"Wrapped statistics for {year_value} recalculated.")
    return redirect("coursework_studio_wrapped")
