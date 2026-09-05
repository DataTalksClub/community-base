from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from community_base.accounts.models import MemberProfile
from community_base.accounts.services.profile import ProfileUpdateError
from community_base.onboarding.forms import ProfileStepForm
from community_base.onboarding.hooks import hooks
from community_base.onboarding.models import OnboardingStep
from community_base.onboarding.services import (
    OnboardingUnavailable,
    advance,
    advance_completed,
    bind_response,
    progress_for,
    questionnaire_for_step,
    response_for_step,
)
from community_base.questionnaires.models import Response
from community_base.questionnaires.onboarding import (
    get_onboarding_response,
    resolve_target_questionnaire,
    self_identification_options,
)
from community_base.questionnaires.services import (
    AnswerSaveError,
    build_response_form_rows,
    build_response_questions,
    find_unanswered_required,
    save_response_answers,
)


def _state(request):
    try:
        state = progress_for(request.user)
    except OnboardingUnavailable:
        return None
    state.progress = advance_completed(state.progress)
    return state


def _unavailable():
    return HttpResponseForbidden("Onboarding is unavailable.")


def _step_url():
    return reverse("community_base_onboarding_step")


@login_required
@never_cache
def start(request):
    state = _state(request)
    if state is None:
        return _unavailable()
    if state.progress.completed_at is not None:
        return render(
            request, "community_base/onboarding/complete.html", {"progress": state.progress}
        )
    return redirect(_step_url())


@login_required
@never_cache
def resume(request):
    return start(request)


def _profile_context(progress, *, form=None, error=""):
    profile = MemberProfile.objects.filter(user=progress.user).first()
    return {
        "progress": progress,
        "step": progress.current_step,
        "form": form or ProfileStepForm(instance=profile),
        "error": error,
    }


def _questionnaire_response(progress, step, *, selection=""):
    response = response_for_step(progress, step)
    if response is not None:
        return response
    questionnaire = (
        resolve_target_questionnaire(selection)
        if step.config.get("persona_selection") and selection
        else questionnaire_for_step(step)
    )
    if questionnaire is None:
        return None
    response, _created = Response.objects.get_or_create(
        questionnaire=questionnaire, respondent=progress.user, defaults={"status": "draft"}
    )
    build_response_questions(response)
    bind_response(progress, step, response)
    return response


def _questionnaire_context(progress, response=None, *, post_data=None, errors=None):
    step = progress.current_step
    if response is None and step.config.get("persona_selection"):
        return {
            "progress": progress,
            "step": step,
            "identify_options": self_identification_options(),
        }
    return {
        "progress": progress,
        "step": step,
        "response": response,
        "response_form_rows": (
            build_response_form_rows(response, post_data=post_data, field_errors=errors)
            if response is not None
            else []
        ),
    }


def _render_current(request, progress, *, context=None, status=200):
    step = progress.current_step
    if step.kind == OnboardingStep.Kind.PROFILE:
        return render(
            request,
            "community_base/onboarding/profile.html",
            context or _profile_context(progress),
            status=status,
        )
    if step.kind == OnboardingStep.Kind.QUESTIONNAIRE:
        response = response_for_step(progress, step)
        if response is None and not step.config.get("persona_selection"):
            response = _questionnaire_response(progress, step)
        return render(
            request,
            "community_base/onboarding/questionnaire.html",
            context or _questionnaire_context(progress, response),
            status=status,
        )
    if step.kind == OnboardingStep.Kind.AI_CHAT:
        response = get_onboarding_response(request.user)
        if response is not None:
            bind_response(progress, step, response)
            if response.status == "submitted":
                advance(progress, step=step)
                return redirect("community_base_onboarding_start")
        return redirect("questionnaires_ai_chat")
    if step.kind == OnboardingStep.Kind.PLAN:
        result = hooks.plan_step(request=request, step=step, progress=progress)
        if isinstance(result, HttpResponse):
            return result
        return render(
            request,
            "community_base/onboarding/plan.html",
            {"progress": progress, "step": step, "plan": result or {}},
            status=status,
        )
    template = str(step.config.get("template", "")).strip()
    if not template:
        return HttpResponse("Custom onboarding step has no template.", status=503)
    return render(request, template, {"progress": progress, "step": step}, status=status)


@login_required
@never_cache
def step(request):
    state = _state(request)
    if state is None:
        return _unavailable()
    if state.progress.completed_at is not None:
        return redirect("community_base_onboarding_start")
    return _render_current(request, state.progress)


def _submit_profile(request, progress, step):
    profile = MemberProfile.objects.filter(user=request.user).first()
    form = ProfileStepForm(request.POST, instance=profile)
    if not form.is_valid():
        return _render_current(
            request, progress, context=_profile_context(progress, form=form), status=400
        )
    try:
        state = form.save_for(request.user)
    except ProfileUpdateError as error:
        return _render_current(
            request,
            progress,
            context=_profile_context(progress, form=form, error=error.message),
            status=400,
        )
    if state.data["completion_version"] == 0:
        return _render_current(
            request,
            progress,
            context=_profile_context(
                progress,
                form=ProfileStepForm(instance=state.profile),
                error="Verify your email to continue.",
            ),
            status=400,
        )
    advance(progress, step=step)
    return redirect("community_base_onboarding_start")


def _submit_questionnaire(request, progress, step):
    response = response_for_step(progress, step)
    if response is None:
        response = _questionnaire_response(
            progress, step, selection=request.POST.get("self_id", "").strip()
        )
        if response is None:
            context = _questionnaire_context(progress)
            context["error"] = "Choose an available questionnaire."
            return _render_current(request, progress, context=context, status=400)
        if step.config.get("persona_selection"):
            return redirect(_step_url())
    try:
        save_response_answers(response, request.POST, require_choice_free_text=True)
    except AnswerSaveError as error:
        return _render_current(
            request,
            progress,
            context=_questionnaire_context(
                progress, response, post_data=request.POST, errors=error.field_errors
            ),
            status=400,
        )
    if request.POST.get("action") == "save":
        return redirect(_step_url())
    missing = find_unanswered_required(response)
    if missing:
        context = _questionnaire_context(progress, response)
        context["error"] = "Answer every required question before continuing."
        return _render_current(request, progress, context=context, status=400)
    response.mark_submitted()
    advance(progress, step=step)
    return redirect("community_base_onboarding_start")


@login_required
@require_POST
@never_cache
def submit(request):
    state = _state(request)
    if state is None:
        return _unavailable()
    progress = state.progress
    step = progress.current_step
    if step is None:
        return redirect("community_base_onboarding_start")
    if request.POST.get("action") == "skip" and not step.required:
        advance(progress, step=step)
        return redirect("community_base_onboarding_start")
    if step.kind == OnboardingStep.Kind.PROFILE:
        return _submit_profile(request, progress, step)
    if step.kind == OnboardingStep.Kind.QUESTIONNAIRE:
        return _submit_questionnaire(request, progress, step)
    if step.kind == OnboardingStep.Kind.PLAN:
        result = hooks.plan_step(request=request, step=step, progress=progress)
        if isinstance(result, HttpResponse):
            return result
        if not isinstance(result, dict) or not result.get("complete"):
            return _render_current(request, progress, status=400)
    advance(progress, step=step)
    return redirect("community_base_onboarding_start")


@login_required
@never_cache
def dashboard_prompt(request):
    try:
        state = progress_for(request.user, create=False)
    except OnboardingUnavailable:
        state = None
    if state is not None and state.progress.completed_at is not None:
        return HttpResponse("")
    return render(request, "community_base/onboarding/_dashboard_prompt.html", {"state": state})
