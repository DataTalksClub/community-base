"""Optional adapter for hosts that actually use package-owned coursework rows."""

from django.apps import apps

from community_base.homework_steps.types import (
    AcceptedSubmission,
    Assignment,
    Eligibility,
    Option,
    Question,
    QuestionResult,
)


def _require_coursework():
    if not apps.is_installed("community_base.coursework"):
        raise RuntimeError("The coursework adapter requires community_base.coursework")


def _question_key(question):
    return question.source_question_id or f"db-{question.pk}"


def _options(question):
    labels = question.get_possible_answers()
    keys = question.source_option_ids or [f"option-{index}" for index in range(1, len(labels) + 1)]
    return tuple(Option(key=key, label=label) for key, label in zip(keys, labels, strict=True))


def coursework_assignment(homework, user, *, context=None):
    """Build descriptors from a package Homework; identity includes its cohort."""

    _require_coursework()
    from community_base.coursework.models import QuestionTypes, Submission

    questions = list(homework.questions.order_by("id"))
    types = {
        QuestionTypes.MULTIPLE_CHOICE.value: "choice",
        QuestionTypes.CHECKBOXES.value: "checkbox",
        QuestionTypes.FREE_FORM.value: "short_text",
        QuestionTypes.FREE_FORM_LONG.value: "long_text",
    }
    normalized = tuple(
        Question(
            key=_question_key(question),
            prompt=question.text,
            type=types[question.question_type],
            options=_options(question) if question.has_choice_answers() else (),
        )
        for question in questions
    )
    existing_answers = {}
    submission = Submission.objects.filter(homework=homework, student=user).first()
    if submission:
        answer_by_question = {
            answer.question_id: answer.answer_text or "" for answer in submission.answers.all()
        }
        for question in questions:
            if question.pk not in answer_by_question:
                continue
            text = answer_by_question[question.pk]
            key = _question_key(question)
            if question.has_choice_answers():
                option_keys = [option.key for option in _options(question)]
                try:
                    selected = [option_keys[int(index) - 1] for index in text.split(",") if index]
                except (IndexError, ValueError):
                    selected = []
                existing_answers[key] = (
                    selected
                    if question.question_type == "CB"
                    else (selected[0] if selected else "")
                )
            else:
                existing_answers[key] = text
    return Assignment(
        key=f"coursework:{homework.cohort_id}:{homework.pk}",
        title=homework.title,
        questions=normalized,
        introduction=homework.description,
        instructions=homework.instructions_markdown,
        existing_answers=existing_answers,
        has_submission=submission is not None,
        availability=_availability(homework, submission),
        accepted_submission=(
            AcceptedSubmission(
                answers=existing_answers,
                submitted_at=submission.submitted_at,
            )
            if submission
            else None
        ),
        question_results=_question_results(homework, submission, questions),
        context=context,
    )


def _availability(homework, submission):
    """The learner's view of the homework; a self-paced one is scored once they submit."""

    from community_base.coursework.homework_reveal import locked_after_submit
    from community_base.coursework.models import HomeworkState

    if locked_after_submit(homework, submission):
        return "scored"
    return {
        HomeworkState.OPEN.value: "open",
        HomeworkState.CLOSED.value: "closed",
        HomeworkState.SCORED.value: "scored",
    }[homework.state]


def _question_results(homework, submission, questions):
    """Revealed results keyed by question key, or ``None`` while the policy reveals nothing."""

    from community_base.coursework.homework_reveal import question_results, results_revealed

    if not results_revealed(homework, submission):
        return None
    by_id = question_results(homework, submission)
    results = {}
    for question in questions:
        result = by_id[question.pk]
        results[_question_key(question)] = QuestionResult(
            correct=result.correct,
            correct_answer=result.correct_answer,
            explanation=result.explanation,
        )
    return results


class CourseworkAdapter:
    """Delegate final submission to the package's existing scoring and hook path."""

    def __init__(self, homework):
        _require_coursework()
        self.homework_id = homework.pk

    def eligibility(self, request, assignment):
        from community_base.coursework.homework_reveal import locked_after_submit
        from community_base.coursework.models import Homework, HomeworkState, Submission

        homework = Homework.objects.get(pk=self.homework_id)
        accepting = homework.state == HomeworkState.OPEN.value
        reason = ""
        if not accepting:
            reason = "This homework is closed."
        submission = Submission.objects.filter(homework=homework, student=request.user).first()
        if accepting and locked_after_submit(homework, submission):
            accepting = False
            reason = "You have submitted this homework. Your results are shown on the review."
        return Eligibility(
            read=request.user.is_authenticated,
            write=accepting,
            submit=accepting,
            reason=reason,
        )

    def submit(self, request, assignment, answers, final_fields):
        from community_base.coursework.models import Homework
        from community_base.coursework.submissions import submit_homework

        homework = Homework.objects.get(pk=self.homework_id)
        by_question_id = {}
        for question in homework.questions.all():
            key = _question_key(question)
            if key not in answers:
                continue
            answer = answers[key]
            if question.has_choice_answers():
                positions = {
                    option.key: index for index, option in enumerate(_options(question), start=1)
                }
                selected = answer if isinstance(answer, list) else [answer]
                by_question_id[question.pk] = ",".join(
                    str(positions[key]) for key in selected if key
                )
            else:
                by_question_id[question.pk] = answer
        return submit_homework(homework, request.user, answers_by_question_id=by_question_id)
