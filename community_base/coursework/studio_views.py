"""Studio operations for the coursework app (section: Coursework).

Donor mapping: ``studio_courses/views/homework.py``,
``homework_submission_edit.py``, ``homework_submission_list.py``,
``course_admin.py`` and ``helpers.py``. The donor's score-notification emails
(``homework_notify_scores``), datamailer syncs and impersonation stay
site-side: sites wire them to the coursework hooks. The package account
identifies by email, so submission search matches the enrollment display name
where the donor matched the username.
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from community_base.coursework.models import (
    ANSWER_TYPES,
    Homework,
    HomeworkState,
    Submission,
)
from community_base.coursework.scoring import (
    HomeworkScoringStatus,
    score_homework_submissions,
)
from community_base.coursework.studio_forms import (
    HomeworkSubmissionEditForm,
    first_form_error,
)
from community_base.coursework.studio_services import (
    EXTENSION_OPTIONS,
    clear_correct_answers,
    cohort_homework_rows,
    cohort_support_metrics,
    extend_deadlines,
    extension_label,
    fill_correct_answers,
    homework_submissions_queryset,
    parse_extension_days,
    save_correct_answers_from_admin,
    update_homework_submission_from_admin,
)
from community_base.curriculum.models import Cohort
from community_base.kernel.decorators import staff_required
from community_base.studio.audit import hooks as studio_hooks
from community_base.studio.utils import studio_pagination_context


def _audit(request, event, target, **metadata):
    studio_hooks.audit_writer(
        event=event,
        actor_ref=str(request.user.pk),
        target_ref=str(target.pk),
        metadata=metadata,
    )


def _redirect_after_action(request, fallback_name, **fallback_kwargs):
    """Honour a safe ``next`` POST field, else fall back to the cohort page."""

    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect(fallback_name, **fallback_kwargs)


def _homework_or_404(homework_id):
    return get_object_or_404(Homework.objects.select_related("cohort"), pk=homework_id)


# --- cohorts ---


@staff_required
def cohort_list(request):
    cohorts = Cohort.objects.select_related("course").order_by("finished", "-id")
    return render(
        request,
        "community_base/coursework/studio/cohort_list.html",
        {"cohorts": cohorts},
    )


@staff_required
def cohort_admin(request, cohort_id):
    cohort = get_object_or_404(Cohort.objects.select_related("course"), pk=cohort_id)
    return render(
        request,
        "community_base/coursework/studio/cohort_admin.html",
        {
            "cohort": cohort,
            "homeworks": cohort_homework_rows(cohort),
            "support_metrics": cohort_support_metrics(cohort),
            "extension_options": EXTENSION_OPTIONS,
        },
    )


# --- homework actions ---


@staff_required
@require_POST
def homework_score(request, homework_id):
    """Score a homework with the batch scoring service."""

    homework = _homework_or_404(homework_id)
    status, message = score_homework_submissions(homework.id)
    if status == HomeworkScoringStatus.OK:
        _audit(request, "coursework.homework.scored", homework)
        messages.success(request, message)
    else:
        messages.warning(request, message)
    return _redirect_after_action(request, "coursework_studio_cohort", cohort_id=homework.cohort_id)


@staff_required
@require_POST
def homework_rescore(request, homework_id):
    """Re-score an already scored homework by resetting it to OPEN."""

    homework = _homework_or_404(homework_id)
    if not homework.is_scored():
        messages.warning(
            request,
            f"{homework.title} is not scored yet. Use Score submissions instead.",
        )
        return _redirect_after_action(
            request, "coursework_studio_cohort", cohort_id=homework.cohort_id
        )
    homework.state = HomeworkState.OPEN.value
    homework.save(update_fields=["state"])
    status, message = score_homework_submissions(homework.id)
    if status == HomeworkScoringStatus.OK:
        _audit(request, "coursework.homework.rescored", homework)
        messages.success(request, message)
    else:
        messages.warning(request, message)
    return _redirect_after_action(request, "coursework_studio_cohort", cohort_id=homework.cohort_id)


@staff_required
@require_POST
def homework_extend_deadline(request, homework_id):
    """Push the homework due date forward by a fixed amount."""

    homework = _homework_or_404(homework_id)
    if homework.state != HomeworkState.OPEN.value:
        messages.warning(request, "Only open homework can have its deadline extended.")
        return _redirect_after_action(
            request, "coursework_studio_cohort", cohort_id=homework.cohort_id
        )
    days = parse_extension_days(request.POST.get("days"))
    if days is None:
        messages.warning(request, "Invalid deadline extension.")
        return _redirect_after_action(
            request, "coursework_studio_cohort", cohort_id=homework.cohort_id
        )
    extend_deadlines(homework, ["due_date"], days)
    _audit(request, "coursework.homework.deadline_extended", homework, days=days)
    messages.success(
        request,
        f"Extended the deadline for {homework.title} by {extension_label(days)}.",
    )
    return _redirect_after_action(request, "coursework_studio_cohort", cohort_id=homework.cohort_id)


@staff_required
@require_POST
def homework_save_answers(request, homework_id):
    """Save the correct answers posted from the submissions page."""

    homework = _homework_or_404(homework_id)
    save_correct_answers_from_admin(homework, request.POST)
    _audit(request, "coursework.homework.answers_saved", homework)
    messages.success(request, f"Correct answers for {homework.title} updated.")
    return _redirect_after_action(
        request,
        "coursework_studio_homework_submissions",
        homework_id=homework.id,
    )


@staff_required
@require_POST
def homework_set_correct_answers(request, homework_id):
    """Set correct answers to the most popular submission answer."""

    homework = _homework_or_404(homework_id)
    fill_correct_answers(homework)
    _audit(request, "coursework.homework.correct_answers_filled", homework)
    messages.success(
        request,
        f"Correct answers for {homework.title} set to most popular",
    )
    return _redirect_after_action(
        request,
        "coursework_studio_homework_submissions",
        homework_id=homework.id,
    )


@staff_required
@require_POST
def homework_clear_correct_answers(request, homework_id):
    """Clear correct answers for every question of the homework."""

    homework = _homework_or_404(homework_id)
    updated_count = clear_correct_answers(homework)
    _audit(request, "coursework.homework.correct_answers_cleared", homework)
    messages.success(
        request,
        f"Correct answers for {updated_count} questions in {homework.title} cleared",
    )
    return _redirect_after_action(
        request,
        "coursework_studio_homework_submissions",
        homework_id=homework.id,
    )


# --- submissions ---


def _questions_with_answers(homework, submission):
    answers = {answer.question_id: answer for answer in submission.answers.all()}
    return [
        {
            "question": question,
            "answer": answers.get(question.id),
            "answer_text": getattr(answers.get(question.id), "answer_text", "") or "",
        }
        for question in homework.questions.order_by("id")
    ]


@staff_required
def homework_submissions(request, homework_id):
    """View all submissions for a homework."""

    homework = _homework_or_404(homework_id)
    search_query = request.GET.get("q", "")
    submissions = homework_submissions_queryset(homework, search_query)
    pager = studio_pagination_context(request, submissions)
    questions = list(homework.questions.order_by("id"))
    return render(
        request,
        "community_base/coursework/studio/homework_submissions.html",
        {
            "cohort": homework.cohort,
            "homework": homework,
            "submissions": pager["page"],
            "search_query": search_query,
            "questions": questions,
            "answer_types": ANSWER_TYPES,
            **pager,
        },
    )


@staff_required
def homework_submission_edit(request, homework_id, submission_id):
    """Edit one homework submission and rescore it."""

    homework = _homework_or_404(homework_id)
    submission = get_object_or_404(
        Submission.objects.select_related("student", "enrollment"),
        pk=submission_id,
        homework=homework,
    )
    questions_with_answers = _questions_with_answers(homework, submission)

    if request.method == "POST":
        form = HomeworkSubmissionEditForm(request.POST, submission=submission, homework=homework)
        if form.is_valid():
            score_changed = update_homework_submission_from_admin(
                submission,
                answers_by_question=form.cleaned_data["answers_by_question"],
                learning_in_public_links=form.cleaned_data["learning_in_public_links_list"],
                faq_contribution_url=form.cleaned_data["faq_contribution_url"],
                faq_score=form.cleaned_data["faq_score"],
            )
            if score_changed:
                _audit(request, "coursework.submission.rescored", submission)
            messages.success(
                request,
                f"Homework submission for {submission.student.email} updated successfully",
            )
            return redirect("coursework_studio_homework_submissions", homework_id=homework.id)
        messages.error(request, f"Error updating submission: {first_form_error(form)}")

    form = HomeworkSubmissionEditForm(None, submission=submission, homework=homework)
    return render(
        request,
        "community_base/coursework/studio/homework_submission_edit.html",
        {
            "cohort": homework.cohort,
            "homework": homework,
            "submission": submission,
            "form": form,
            "questions_with_answers": questions_with_answers,
        },
    )
