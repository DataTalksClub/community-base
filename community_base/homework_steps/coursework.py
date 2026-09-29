"""Optional adapter for hosts that actually use package-owned coursework rows."""

from django.apps import apps

from community_base.homework_steps.types import Eligibility, Option


def _require_coursework():
    if not apps.is_installed("community_base.coursework"):
        raise RuntimeError("The coursework adapter requires community_base.coursework")


def _question_key(question):
    return question.source_question_id or f"db-{question.pk}"


def _options(question):
    labels = question.get_possible_answers()
    keys = question.source_option_ids or [f"option-{index}" for index in range(1, len(labels) + 1)]
    return tuple(Option(key=key, label=label) for key, label in zip(keys, labels, strict=True))


PUBLIC_LINKS_KEY = "learning-in-public"


def coursework_assignment(homework, user, *, context=None):
    """Build descriptors from a package Homework; identity includes its cohort."""

    from community_base.homework_steps.coursework_assignment import coursework_assignment as build

    return build(homework, user, context=context)


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
        return submit_homework(
            homework,
            request.user,
            answers_by_question_id=_converted_answers(homework, answers),
            stepper_fields=_submitted_fields(homework, final_fields),
            public_answer=answers.get(PUBLIC_LINKS_KEY, ""),
        )


def _submitted_fields(homework, final_fields):
    if homework.stepper_enabled:
        return final_fields
    return None


def _converted_answers(homework, answers):
    by_question_id = {}
    for question in homework.questions.all():
        key = _question_key(question)
        if key not in answers:
            continue
        answer = answers[key]
        if not question.has_choice_answers():
            by_question_id[question.pk] = answer
            continue
        positions = {option.key: index for index, option in enumerate(_options(question), start=1)}
        selected = [answer]
        if isinstance(answer, list):
            selected = answer
        indices = []
        for option_key in selected:
            if option_key:
                indices.append(str(positions[option_key]))
        by_question_id[question.pk] = ",".join(indices)
    return by_question_id
