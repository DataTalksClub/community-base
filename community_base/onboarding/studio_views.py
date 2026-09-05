from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from community_base.kernel.decorators import staff_required
from community_base.onboarding.models import (
    FlowAssignment,
    OnboardingFlow,
    OnboardingProgress,
    OnboardingStep,
)
from community_base.onboarding.studio_forms import (
    FlowAssignmentForm,
    OnboardingFlowForm,
    OnboardingStepForm,
)
from community_base.studio.utils import studio_pagination_context


@staff_required
def flow_list(request):
    flows = OnboardingFlow.objects.annotate(
        step_count=Count("steps", distinct=True),
        assignment_count=Count("assignments", distinct=True),
        progress_count=Count("progress_records", distinct=True),
    )
    return render(request, "community_base/onboarding/studio/flow_list.html", {"flows": flows})


def _flow_form(request, instance=None):
    form = OnboardingFlowForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        flow = form.save()
        messages.success(request, "Onboarding flow saved.")
        return redirect("onboarding_studio_flow_detail", flow_id=flow.pk)
    return render(
        request,
        "community_base/onboarding/studio/form.html",
        {"form": form, "object": instance},
        status=400 if request.method == "POST" else 200,
    )


@staff_required
def flow_create(request):
    return _flow_form(request)


@staff_required
def flow_edit(request, flow_id):
    return _flow_form(request, get_object_or_404(OnboardingFlow, pk=flow_id))


@staff_required
def flow_detail(request, flow_id):
    flow = get_object_or_404(OnboardingFlow, pk=flow_id)
    return render(
        request,
        "community_base/onboarding/studio/flow_detail.html",
        {
            "flow": flow,
            "steps": flow.steps.all(),
            "assignments": flow.assignments.select_related("group"),
        },
    )


def _step_form(request, flow, instance=None):
    form = OnboardingStepForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        step = form.save(commit=False)
        step.flow = flow
        step.full_clean()
        step.save()
        messages.success(request, "Onboarding step saved.")
        return redirect("onboarding_studio_flow_detail", flow_id=flow.pk)
    return render(
        request,
        "community_base/onboarding/studio/form.html",
        {"form": form, "object": instance, "flow": flow},
        status=400 if request.method == "POST" else 200,
    )


@staff_required
def step_create(request, flow_id):
    return _step_form(request, get_object_or_404(OnboardingFlow, pk=flow_id))


@staff_required
def step_edit(request, flow_id, step_id):
    flow = get_object_or_404(OnboardingFlow, pk=flow_id)
    return _step_form(request, flow, get_object_or_404(OnboardingStep, pk=step_id, flow=flow))


@require_POST
@staff_required
def step_delete(request, flow_id, step_id):
    flow = get_object_or_404(OnboardingFlow, pk=flow_id)
    get_object_or_404(OnboardingStep, pk=step_id, flow=flow).delete()
    return redirect("onboarding_studio_flow_detail", flow_id=flow.pk)


@staff_required
def assignment_create(request, flow_id):
    flow = get_object_or_404(OnboardingFlow, pk=flow_id)
    form = FlowAssignmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        assignment = form.save(commit=False)
        assignment.flow = flow
        assignment.full_clean()
        assignment.save()
        messages.success(request, "Flow assignment saved.")
        return redirect("onboarding_studio_flow_detail", flow_id=flow.pk)
    return render(
        request,
        "community_base/onboarding/studio/form.html",
        {"form": form, "flow": flow},
        status=400 if request.method == "POST" else 200,
    )


@require_POST
@staff_required
def assignment_delete(request, flow_id, assignment_id):
    flow = get_object_or_404(OnboardingFlow, pk=flow_id)
    get_object_or_404(FlowAssignment, pk=assignment_id, flow=flow).delete()
    return redirect("onboarding_studio_flow_detail", flow_id=flow.pk)


@staff_required
def progress_list(request):
    rows = OnboardingProgress.objects.select_related("user", "flow", "current_step")
    search = request.GET.get("q", "").strip()
    if search:
        rows = rows.filter(
            Q(user__email__icontains=search)
            | Q(flow__title__icontains=search)
            | Q(flow__slug__icontains=search)
        )
    return render(
        request,
        "community_base/onboarding/studio/progress_list.html",
        {
            "progress_records": studio_pagination_context(request, rows)["page"],
            "q": search,
        },
    )
