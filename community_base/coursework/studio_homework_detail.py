"""Studio homework detail presentation and authored question order."""

from django.shortcuts import get_object_or_404, render

from community_base.coursework.models import Homework, HomeworkState
from community_base.coursework.question_order import ordered_questions
from community_base.kernel.decorators import staff_required


@staff_required
def homework_detail(request, homework_id):
    homework = get_object_or_404(Homework.objects.select_related("cohort__course"), pk=homework_id)
    return render(
        request,
        "community_base/coursework/studio/homework_detail.html",
        {
            "homework": homework,
            "questions": ordered_questions(homework),
            "submissions": homework.submissions.select_related("student", "enrollment").order_by(
                "id"
            ),
            "states": list(HomeworkState),
        },
    )
