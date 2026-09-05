import json

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from community_base.kernel.decorators import staff_required
from community_base.questionnaires.models import (
    Persona,
    Question,
    Questionnaire,
    QuestionOption,
    ResponseQuestion,
)
from community_base.questionnaires.response_workflows import (
    ResponseNotSubmitted,
    compact_response_queryset,
    response_queryset,
    transition_response_review,
)
from community_base.questionnaires.studio_forms import (
    PersonaForm,
    QuestionForm,
    QuestionnaireForm,
    ResponseQuestionForm,
)
from community_base.studio.utils import studio_pagination_context


def _parse_reorder_payload(request):
    if request.method != "POST":
        return None, JsonResponse({"error": "POST required"}, status=405)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return None, JsonResponse({"error": "Invalid JSON"}, status=400)
    if not isinstance(data, list):
        return None, JsonResponse({"error": "Payload must be a list"}, status=400)
    items = []
    for entry in data:
        if not isinstance(entry, dict) or set(("id", "order")) - entry.keys():
            return None, JsonResponse({"error": "Each item needs an id and an order"}, status=400)
        item_id, order = entry["id"], entry["order"]
        if (
            isinstance(item_id, bool)
            or isinstance(order, bool)
            or not isinstance(item_id, int)
            or not isinstance(order, int)
        ):
            return None, JsonResponse({"error": "id and order must be integers"}, status=400)
        if order < 0:
            return None, JsonResponse({"error": "order must be zero or positive"}, status=400)
        items.append((item_id, order))
    return items, None


def _apply_reorder(*, items, queryset, model, parent_filters=None):
    submitted_ids = [item_id for item_id, _order in items]
    if len(submitted_ids) != len(set(submitted_ids)):
        return JsonResponse({"error": "Duplicate ids are not allowed"}, status=400)
    if queryset.filter(pk__in=submitted_ids).count() != len(submitted_ids):
        return JsonResponse({"error": "One or more ids are outside this collection"}, status=400)
    filters = parent_filters or {}
    with transaction.atomic():
        for item_id, order in items:
            model.objects.filter(pk=item_id, **filters).update(order=order)
    return JsonResponse({"status": "ok"})


@staff_required
def questionnaire_list(request):
    rows = Questionnaire.objects.annotate(
        questions_total=Count("questions", distinct=True),
        responses_total=Count("responses", distinct=True),
    )
    search = request.GET.get("q", "").strip()
    if search:
        rows = rows.filter(Q(title__icontains=search) | Q(slug__icontains=search))
    return render(
        request,
        "questionnaires/studio/list.html",
        {"questionnaires": studio_pagination_context(request, rows)["page"], "q": search},
    )


def _model_form(request, *, form_class, instance=None, template="questionnaires/studio/form.html"):
    form = form_class(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        return form.save()
    return render(
        request,
        template,
        {"form": form, "object": instance},
        status=400 if request.method == "POST" else 200,
    )


@staff_required
def questionnaire_create(request):
    result = _model_form(request, form_class=QuestionnaireForm)
    if isinstance(result, Questionnaire):
        messages.success(request, "Questionnaire created.")
        return redirect("questionnaires_studio_detail", questionnaire_id=result.pk)
    return result


@staff_required
def questionnaire_edit(request, questionnaire_id):
    questionnaire = get_object_or_404(Questionnaire, pk=questionnaire_id)
    result = _model_form(request, form_class=QuestionnaireForm, instance=questionnaire)
    if isinstance(result, Questionnaire):
        messages.success(request, "Questionnaire updated.")
        return redirect("questionnaires_studio_detail", questionnaire_id=result.pk)
    return result


@staff_required
def questionnaire_detail(request, questionnaire_id):
    questionnaire = get_object_or_404(Questionnaire, pk=questionnaire_id)
    return render(
        request,
        "questionnaires/studio/detail.html",
        {
            "questionnaire": questionnaire,
            "questions": questionnaire.questions.prefetch_related("options"),
        },
    )


def _question_form(request, questionnaire, question=None):
    form = QuestionForm(request.POST or None, instance=question)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.questionnaire = questionnaire
        item.save()
        form.save_options(item)
        messages.success(request, "Question saved.")
        return redirect("questionnaires_studio_detail", questionnaire_id=questionnaire.pk)
    return render(
        request,
        "questionnaires/studio/form.html",
        {"form": form, "object": question, "questionnaire": questionnaire},
        status=400 if request.method == "POST" else 200,
    )


@staff_required
def question_create(request, questionnaire_id):
    return _question_form(request, get_object_or_404(Questionnaire, pk=questionnaire_id))


@staff_required
def question_edit(request, questionnaire_id, question_id):
    questionnaire = get_object_or_404(Questionnaire, pk=questionnaire_id)
    question = get_object_or_404(Question, pk=question_id, questionnaire=questionnaire)
    return _question_form(request, questionnaire, question)


@require_POST
@staff_required
def question_delete(request, questionnaire_id, question_id):
    questionnaire = get_object_or_404(Questionnaire, pk=questionnaire_id)
    get_object_or_404(Question, pk=question_id, questionnaire=questionnaire).delete()
    return redirect("questionnaires_studio_detail", questionnaire_id=questionnaire.pk)


@staff_required
def question_reorder(request, questionnaire_id):
    questionnaire = get_object_or_404(Questionnaire, pk=questionnaire_id)
    items, error = _parse_reorder_payload(request)
    if error is not None:
        return error
    return _apply_reorder(
        items=items,
        queryset=questionnaire.questions,
        model=Question,
        parent_filters={"questionnaire": questionnaire},
    )


@staff_required
def question_option_reorder(request, questionnaire_id, question_id):
    questionnaire = get_object_or_404(Questionnaire, pk=questionnaire_id)
    question = get_object_or_404(Question, pk=question_id, questionnaire=questionnaire)
    items, error = _parse_reorder_payload(request)
    if error is not None:
        return error
    return _apply_reorder(
        items=items,
        queryset=question.options,
        model=QuestionOption,
        parent_filters={"question": question},
    )


@staff_required
def persona_list(request):
    return render(
        request,
        "questionnaires/studio/personas.html",
        {"personas": Persona.objects.select_related("default_questionnaire")},
    )


@staff_required
def persona_create(request):
    result = _model_form(request, form_class=PersonaForm)
    return redirect("questionnaires_studio_persona_list") if isinstance(result, Persona) else result


@staff_required
def persona_edit(request, persona_id):
    result = _model_form(
        request, form_class=PersonaForm, instance=get_object_or_404(Persona, pk=persona_id)
    )
    return redirect("questionnaires_studio_persona_list") if isinstance(result, Persona) else result


@staff_required
def persona_reorder(request):
    items, error = _parse_reorder_payload(request)
    if error is not None:
        return error
    return _apply_reorder(items=items, queryset=Persona.objects, model=Persona)


@staff_required
def response_queue(request):
    filters = {
        "status": request.GET.get("status", "submitted"),
        "review": request.GET.get("review", "awaiting"),
        "purpose": request.GET.get("purpose", "all"),
        "search": request.GET.get("q", "").strip(),
    }
    try:
        rows = compact_response_queryset(**filters)
    except ValueError as error:
        return HttpResponseBadRequest(str(error))
    return render(
        request,
        "questionnaires/studio/responses.html",
        {"responses": studio_pagination_context(request, rows)["page"], "filters": filters},
    )


@staff_required
def questionnaire_responses(request, questionnaire_id):
    questionnaire = get_object_or_404(Questionnaire, pk=questionnaire_id)
    filters = {
        "status": request.GET.get("status", "all"),
        "review": request.GET.get("review", "all"),
        "purpose": "all",
        "questionnaire": questionnaire.pk,
        "search": request.GET.get("q", "").strip(),
    }
    try:
        rows = compact_response_queryset(**filters)
    except ValueError as error:
        return HttpResponseBadRequest(str(error))
    return render(
        request,
        "questionnaires/studio/responses.html",
        {
            "questionnaire": questionnaire,
            "responses": studio_pagination_context(request, rows)["page"],
            "filters": filters,
        },
    )


@staff_required
def response_detail(request, questionnaire_id, response_id):
    response = get_object_or_404(
        response_queryset(include_answers=True), pk=response_id, questionnaire_id=questionnaire_id
    )
    answers = {answer.question_id: answer for answer in response.answers.all()}
    rows = [(question, answers.get(question.pk)) for question in response.response_questions.all()]
    return render(
        request,
        "questionnaires/studio/response_detail.html",
        {"response": response, "answer_rows": rows},
    )


@require_POST
@staff_required
def response_review(request, questionnaire_id, response_id):
    try:
        transition_response_review(
            response_id=response_id,
            questionnaire_id=questionnaire_id,
            reviewed=request.POST.get("reviewed") == "1",
            actor=request.user,
        )
    except ResponseNotSubmitted:
        return HttpResponseBadRequest("Draft responses cannot be reviewed.")
    return redirect(
        "questionnaires_studio_response_detail",
        questionnaire_id=questionnaire_id,
        response_id=response_id,
    )


def _response_question_form(request, response, question=None):
    form = ResponseQuestionForm(request.POST or None, instance=question)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.response = response
        item.source_question = None
        item.save()
        form.save_options(item)
        return redirect(
            "questionnaires_studio_response_detail",
            questionnaire_id=response.questionnaire_id,
            response_id=response.pk,
        )
    return render(
        request,
        "questionnaires/studio/form.html",
        {"form": form, "object": question, "response": response},
        status=400 if request.method == "POST" else 200,
    )


@staff_required
def response_question_create(request, questionnaire_id, response_id):
    response = get_object_or_404(
        response_queryset(), pk=response_id, questionnaire_id=questionnaire_id
    )
    return _response_question_form(request, response)


@staff_required
def response_question_edit(request, questionnaire_id, response_id, question_id):
    response = get_object_or_404(
        response_queryset(), pk=response_id, questionnaire_id=questionnaire_id
    )
    question = get_object_or_404(ResponseQuestion, pk=question_id, response=response)
    return _response_question_form(request, response, question)


@require_POST
@staff_required
def response_question_delete(request, questionnaire_id, response_id, question_id):
    response = get_object_or_404(
        response_queryset(), pk=response_id, questionnaire_id=questionnaire_id
    )
    get_object_or_404(ResponseQuestion, pk=question_id, response=response).delete()
    return redirect(
        "questionnaires_studio_response_detail",
        questionnaire_id=questionnaire_id,
        response_id=response_id,
    )
