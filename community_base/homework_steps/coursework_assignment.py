"""Build safe stepper descriptors from package-owned homework rows."""

from community_base.homework_steps.coursework import (
    PUBLIC_LINKS_KEY,
    _options,
    _question_key,
    _require_coursework,
)
from community_base.homework_steps.types import (
    AcceptedSubmission,
    Assignment,
    FinalField,
    Question,
    QuestionResult,
)


def _question_descriptors(questions, *, stepper):
    from community_base.coursework.models import QuestionTypes

    types = {
        QuestionTypes.MULTIPLE_CHOICE.value: "choice",
        QuestionTypes.CHECKBOXES.value: "checkbox",
        QuestionTypes.FREE_FORM.value: "short_text",
        QuestionTypes.FREE_FORM_LONG.value: "long_text",
    }
    return tuple(_question_descriptor(question, types, stepper) for question in questions)


def _question_descriptor(question, types, stepper):
    options = ()
    if question.has_choice_answers():
        options = _options(question)
    label = ""
    if stepper:
        label = question.step_label
    return Question(
        key=_question_key(question),
        prompt=question.text,
        type=types[question.question_type],
        options=options,
        step_label=label,
    )


def _submitted_answers(questions, submission):
    existing_answers = {}
    if submission is None:
        return existing_answers
    answer_by_question = {
        answer.question_id: answer.answer_text or "" for answer in submission.answers.all()
    }
    for question in questions:
        if question.pk not in answer_by_question:
            continue
        text = answer_by_question[question.pk]
        key = _question_key(question)
        if not question.has_choice_answers():
            existing_answers[key] = text
            continue
        option_keys = [option.key for option in _options(question)]
        try:
            selected = []
            for index in text.split(","):
                if index:
                    selected.append(option_keys[int(index) - 1])
        except (IndexError, ValueError):
            selected = []
        if question.question_type == "CB":
            existing_answers[key] = selected
        else:
            existing_answers[key] = ""
            if selected:
                existing_answers[key] = selected[0]
    return existing_answers


def _stepper_fields(homework, submission):
    fields = []
    values = {}
    if homework.homework_url_field:
        fields.append(FinalField("homework_link", "Homework URL", "url", required=True))
        values["homework_link"] = ""
        if submission:
            values["homework_link"] = submission.homework_link or ""
    for flag, key, label in (
        (
            homework.time_spent_lectures_field,
            "time_spent_lectures",
            "Time spent on lectures (hours) (optional)",
        ),
        (
            homework.time_spent_homework_field,
            "time_spent_homework",
            "Time spent on homework (hours) (optional)",
        ),
    ):
        if not flag:
            continue
        fields.append(FinalField(key, label))
        value = None
        if submission:
            value = getattr(submission, key)
        values[key] = ""
        if value is not None:
            values[key] = str(value)
    return tuple(fields), values


def _stepper_question(homework, submission):
    if homework.learning_in_public_cap <= 0:
        return None, ""
    links = None
    if submission:
        links = submission.learning_in_public_links
    if not isinstance(links, list):
        links = []
    question = Question(
        key=PUBLIC_LINKS_KEY,
        prompt="## Learning in Public\n\nShare your progress in public if you would like.",
        type="long_text",
        step_label="Learning in Public",
    )
    return question, "\n".join(links)


def _stepper_parts(homework, submission, questions, answers, context):
    fields, values = _stepper_fields(homework, submission)
    public_question, public_answer = _stepper_question(homework, submission)
    if public_question:
        questions += (public_question,)
        answers[PUBLIC_LINKS_KEY] = public_answer
    context = {**(context or {}), "learning_in_public_cap": homework.learning_in_public_cap}
    return questions, answers, fields, values, context


def _accepted_submission(submission, answers, final_fields):
    if submission is None:
        return None
    return AcceptedSubmission(
        answers=answers,
        final_fields=final_fields,
        submitted_at=submission.submitted_at,
    )


def coursework_assignment(homework, user, *, context=None):
    """Build descriptors from a package Homework; identity includes its cohort."""

    _require_coursework()
    from community_base.coursework.models import Submission
    from community_base.coursework.question_order import ordered_questions

    questions = list(ordered_questions(homework))
    submission = Submission.objects.filter(homework=homework, student=user).first()
    normalized = _question_descriptors(questions, stepper=homework.stepper_enabled)
    existing_answers = _submitted_answers(questions, submission)
    final_fields = ()
    existing_final_fields = {}
    if homework.stepper_enabled:
        normalized, existing_answers, final_fields, existing_final_fields, context = _stepper_parts(
            homework, submission, normalized, existing_answers, context
        )
    return _assignment(
        homework,
        submission,
        questions,
        normalized,
        existing_answers,
        final_fields,
        existing_final_fields,
        context,
    )


def _assignment(
    homework,
    submission,
    questions,
    normalized,
    existing_answers,
    final_fields,
    existing_final_fields,
    context,
):
    return Assignment(
        key=f"coursework:{homework.cohort_id}:{homework.pk}",
        title=homework.title,
        questions=normalized,
        introduction=homework.description,
        instructions=homework.instructions_markdown,
        final_fields=final_fields,
        existing_answers=existing_answers,
        existing_final_fields=existing_final_fields,
        has_submission=submission is not None,
        availability=_availability(homework, submission),
        accepted_submission=_accepted_submission(
            submission, existing_answers, existing_final_fields
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
