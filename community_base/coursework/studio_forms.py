from django import forms

from community_base.coursework.models import Homework, ProjectCriteriaAssignment, Question


class HomeworkForm(forms.ModelForm):
    class Meta:
        model = Homework
        fields = (
            "title",
            "slug",
            "description",
            "instructions_markdown",
            "instructions_url",
            "due_date",
            "state",
            "learning_in_public_cap",
            "homework_url_field",
            "time_spent_lectures_field",
            "time_spent_homework_field",
            "faq_contribution_field",
        )


class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = (
            "text",
            "question_type",
            "answer_type",
            "possible_answers",
            "correct_answer",
            "scores_for_correct_answer",
        )


class CriteriaAssignmentForm(forms.ModelForm):
    class Meta:
        model = ProjectCriteriaAssignment
        fields = ("criteria", "position")
