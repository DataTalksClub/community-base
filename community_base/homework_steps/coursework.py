"""Optional adapter for hosts that actually use package-owned coursework rows."""

from django.apps import apps

from community_base.homework_steps.types import Assignment, Eligibility, Option, Question


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
        context=context,
    )


class CourseworkAdapter:
    """Delegate final submission to the package's existing scoring and hook path."""

    def __init__(self, homework):
        _require_coursework()
        self.homework_id = homework.pk

    def eligibility(self, request, assignment):
        from community_base.coursework.models import Homework, HomeworkState

        homework = Homework.objects.get(pk=self.homework_id)
        accepting = homework.state == HomeworkState.OPEN.value
        return Eligibility(
            read=request.user.is_authenticated,
            write=accepting,
            submit=accepting,
            reason="This homework is closed." if not accepting else "",
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
