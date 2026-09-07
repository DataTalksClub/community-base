"""Studio operations for the curriculum app (section: Courses)."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from community_base.curriculum.models import (
    Certificate,
    Cohort,
    Course,
    CourseInstructor,
    Enrollment,
    Module,
    Unit,
)
from community_base.curriculum.studio_forms import CohortForm, CourseForm, ModuleForm, UnitForm
from community_base.events.models import Host
from community_base.kernel.decorators import staff_required
from community_base.studio.audit import hooks as studio_hooks


def _audit(request, event, target, **metadata):
    studio_hooks.audit_writer(
        event=event,
        actor_ref=str(request.user.pk),
        target_ref=str(target.pk),
        metadata=metadata,
    )


def _source_locked(instance) -> bool:
    return instance.pk is not None and instance.source_content_id is not None


def _locked_response(request, instance, redirect_to):
    """Reject edits of source-managed rows; the repository is the truth."""

    messages.error(
        request,
        f"{instance._meta.verbose_name.capitalize()} is source-managed; "
        "edit the repository and re-sync instead.",
    )
    if hasattr(redirect_to, "status_code"):
        return redirect_to
    return redirect(redirect_to)


def _save_form(request, form_class, *, instance=None, locked_redirect):
    """Save the form unless the row is source-managed.

    ``locked_redirect`` is a callable returning the redirect used when the
    row is source-managed.
    """

    if instance is not None and _source_locked(instance):
        return _locked_response(request, instance, locked_redirect())
    form = form_class(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        return form.save()
    return form


# --- courses ---


@staff_required
def course_list(request):
    courses = Course.objects.all().order_by("-created_at")
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    if query:
        courses = courses.filter(Q(title__icontains=query) | Q(slug__icontains=query))
    if status:
        courses = courses.filter(status=status)
    return render(
        request,
        "community_base/curriculum/studio/course_list.html",
        {"courses": courses, "q": query, "status": status},
    )


@staff_required
def course_create(request):
    result = _save_form(
        request, CourseForm, locked_redirect=lambda: redirect("curriculum_studio_course_list")
    )
    if isinstance(result, Course):
        _audit(request, "curriculum.course.created", result)
        messages.success(request, "Course created.")
        return redirect("curriculum_studio_course_detail", course_id=result.pk)
    return render(
        request,
        "community_base/curriculum/studio/form.html",
        {"form": result, "kind": "course"},
    )


@staff_required
def course_detail(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    return render(
        request,
        "community_base/curriculum/studio/course_detail.html",
        {
            "course": course,
            "cohorts": course.cohorts.order_by("start_date", "pk"),
            "instructor_links": CourseInstructor.objects.filter(course=course).order_by(
                "position", "pk"
            ),
            "source_locked": _source_locked(course),
        },
    )


@staff_required
def course_edit(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    result = _save_form(
        request,
        CourseForm,
        instance=course,
        locked_redirect=lambda: redirect("curriculum_studio_course_detail", course_id=course.pk),
    )
    if isinstance(result, Course):
        _audit(request, "curriculum.course.updated", result)
        messages.success(request, "Course updated.")
        return redirect("curriculum_studio_course_detail", course_id=result.pk)
    return render(
        request,
        "community_base/curriculum/studio/form.html",
        {
            "form": result,
            "kind": "course",
            "instance": course,
            "source_locked": _source_locked(course),
        },
    )


@staff_required
@require_POST
def course_delete(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    target = course.pk
    course.delete()
    _audit(request, "curriculum.course.deleted", type("Target", (), {"pk": target})())
    messages.success(request, "Course deleted.")
    return redirect("curriculum_studio_course_list")


# --- instructors ---


@staff_required
@require_POST
def instructor_add(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if _source_locked(course):
        return _locked_response(
            request, course, redirect("curriculum_studio_course_detail", course_id=course.pk)
        )
    slug_or_name = request.POST.get("host", "").strip()
    host = (
        Host.objects.filter(slug=slug_or_name).first()
        or Host.objects.filter(name=slug_or_name).first()
    )
    if host is None:
        messages.error(request, f"No host or instructor matches '{slug_or_name}'.")
        return redirect("curriculum_studio_course_detail", course_id=course.pk)
    CourseInstructor.objects.get_or_create(
        course=course,
        host=host,
        defaults={"position": course.courseinstructor_set.count()},
    )
    _audit(request, "curriculum.course.instructor_added", course, host=host.slug)
    messages.success(request, "Instructor linked.")
    return redirect("curriculum_studio_course_detail", course_id=course.pk)


@staff_required
@require_POST
def instructor_remove(request, course_id, link_id):
    course = get_object_or_404(Course, pk=course_id)
    if _source_locked(course):
        return _locked_response(
            request, course, redirect("curriculum_studio_course_detail", course_id=course.pk)
        )
    link = get_object_or_404(CourseInstructor, pk=link_id, course=course)
    link.delete()
    _audit(request, "curriculum.course.instructor_removed", course)
    messages.success(request, "Instructor unlinked.")
    return redirect("curriculum_studio_course_detail", course_id=course.pk)


# --- cohorts ---


@staff_required
def cohort_create(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    form = CohortForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            cohort = form.save(commit=False)
            cohort.course = course
            cohort.save()
        _audit(request, "curriculum.cohort.created", cohort)
        messages.success(request, "Cohort created.")
        return redirect("curriculum_studio_cohort_detail", cohort_id=cohort.pk)
    return render(
        request,
        "community_base/curriculum/studio/form.html",
        {"form": form, "kind": "cohort"},
    )


@staff_required
def cohort_detail(request, cohort_id):
    cohort = get_object_or_404(Cohort, pk=cohort_id)
    return render(
        request,
        "community_base/curriculum/studio/cohort_detail.html",
        {
            "cohort": cohort,
            "modules": cohort.modules.order_by("sort_order", "pk"),
            "enrollments": cohort.enrollments.select_related("user").order_by("-enrolled_at"),
            "source_locked": _source_locked(cohort),
        },
    )


@staff_required
def cohort_edit(request, cohort_id):
    cohort = get_object_or_404(Cohort, pk=cohort_id)
    result = _save_form(
        request,
        CohortForm,
        instance=cohort,
        locked_redirect=lambda: redirect("curriculum_studio_cohort_detail", cohort_id=cohort.pk),
    )
    if isinstance(result, Cohort):
        _audit(request, "curriculum.cohort.updated", result)
        messages.success(request, "Cohort updated.")
        return redirect("curriculum_studio_cohort_detail", cohort_id=result.pk)
    return render(
        request,
        "community_base/curriculum/studio/form.html",
        {
            "form": result,
            "kind": "cohort",
            "instance": cohort,
            "source_locked": _source_locked(cohort),
        },
    )


@staff_required
@require_POST
def cohort_delete(request, cohort_id):
    cohort = get_object_or_404(Cohort, pk=cohort_id)
    course_id = cohort.course_id
    cohort.delete()
    _audit(request, "curriculum.cohort.deleted", type("Target", (), {"pk": cohort_id})())
    messages.success(request, "Cohort deleted.")
    return redirect("curriculum_studio_course_detail", course_id=course_id)


# --- modules and units ---


@staff_required
def module_create(request, cohort_id):
    cohort = get_object_or_404(Cohort, pk=cohort_id)
    form = ModuleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            module = form.save(commit=False)
            module.cohort = cohort
            module.save()
        _audit(request, "curriculum.module.created", module)
        messages.success(request, "Module created.")
        return redirect("curriculum_studio_cohort_detail", cohort_id=cohort.pk)
    return render(
        request,
        "community_base/curriculum/studio/form.html",
        {"form": form, "kind": "module"},
    )


@staff_required
def module_edit(request, module_id):
    module = get_object_or_404(Module, pk=module_id)
    result = _save_form(
        request,
        ModuleForm,
        instance=module,
        locked_redirect=lambda: redirect(
            "curriculum_studio_cohort_detail", cohort_id=module.cohort_id
        ),
    )
    if isinstance(result, Module):
        _audit(request, "curriculum.module.updated", result)
        messages.success(request, "Module updated.")
        return redirect("curriculum_studio_cohort_detail", cohort_id=result.cohort_id)
    return render(
        request,
        "community_base/curriculum/studio/form.html",
        {
            "form": result,
            "kind": "module",
            "instance": module,
            "source_locked": _source_locked(module),
        },
    )


@staff_required
@require_POST
def module_delete(request, module_id):
    module = get_object_or_404(Module, pk=module_id)
    cohort_id = module.cohort_id
    module.delete()
    _audit(request, "curriculum.module.deleted", type("Target", (), {"pk": module_id})())
    messages.success(request, "Module deleted.")
    return redirect("curriculum_studio_cohort_detail", cohort_id=cohort_id)


@staff_required
def unit_create(request, module_id):
    module = get_object_or_404(Module, pk=module_id)
    form = UnitForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            unit = form.save(commit=False)
            unit.module = module
            unit.save()
        _audit(request, "curriculum.unit.created", unit)
        messages.success(request, "Unit created.")
        return redirect("curriculum_studio_cohort_detail", cohort_id=module.cohort_id)
    return render(
        request,
        "community_base/curriculum/studio/form.html",
        {"form": form, "kind": "unit"},
    )


@staff_required
def unit_edit(request, unit_id):
    unit = get_object_or_404(Unit, pk=unit_id)
    result = _save_form(
        request,
        UnitForm,
        instance=unit,
        locked_redirect=lambda: redirect(
            "curriculum_studio_cohort_detail", cohort_id=unit.module.cohort_id
        ),
    )
    if isinstance(result, Unit):
        _audit(request, "curriculum.unit.updated", result)
        messages.success(request, "Unit updated.")
        return redirect("curriculum_studio_cohort_detail", cohort_id=result.module.cohort_id)
    return render(
        request,
        "community_base/curriculum/studio/form.html",
        {"form": result, "kind": "unit", "instance": unit, "source_locked": _source_locked(unit)},
    )


@staff_required
@require_POST
def unit_delete(request, unit_id):
    unit = get_object_or_404(Unit, pk=unit_id)
    cohort_id = unit.module.cohort_id
    unit.delete()
    _audit(request, "curriculum.unit.deleted", type("Target", (), {"pk": unit_id})())
    messages.success(request, "Unit deleted.")
    return redirect("curriculum_studio_cohort_detail", cohort_id=cohort_id)


# --- enrollments and certificates ---


@staff_required
@require_POST
def enrollment_create(request, cohort_id):
    cohort = get_object_or_404(Cohort, pk=cohort_id)
    if _source_locked(cohort):
        return _locked_response(
            request, cohort, redirect("curriculum_studio_cohort_detail", cohort_id=cohort.pk)
        )
    email = request.POST.get("email", "").strip().lower()
    user = get_user_model().objects.filter(email__iexact=email).first()
    if user is None:
        messages.error(request, f"No account matches '{email}'.")
        return redirect("curriculum_studio_cohort_detail", cohort_id=cohort.pk)
    _enrollment, created = Enrollment.objects.get_or_create(
        user=user, cohort=cohort, defaults={"source": "admin"}
    )
    if created:
        _audit(request, "curriculum.enrollment.created", cohort, email=email)
        messages.success(request, "Enrolled.")
    else:
        messages.info(request, "Already enrolled.")
    return redirect("curriculum_studio_cohort_detail", cohort_id=cohort.pk)


@staff_required
@require_POST
def enrollment_delete(request, enrollment_id):
    enrollment = get_object_or_404(Enrollment, pk=enrollment_id)
    cohort_id = enrollment.cohort_id
    enrollment.delete()
    _audit(request, "curriculum.enrollment.deleted", type("Target", (), {"pk": enrollment_id})())
    messages.success(request, "Enrollment removed.")
    return redirect("curriculum_studio_cohort_detail", cohort_id=cohort_id)


@staff_required
@require_POST
def certificate_issue(request, enrollment_id):
    enrollment = get_object_or_404(Enrollment, pk=enrollment_id)
    certificate, created = Certificate.objects.get_or_create(enrollment=enrollment)
    certificate.url = request.POST.get("url", "").strip()
    certificate.save(update_fields=["url"])
    _audit(request, "curriculum.certificate.issued", enrollment)
    messages.success(request, "Certificate issued." if created else "Certificate updated.")
    return redirect("curriculum_studio_cohort_detail", cohort_id=enrollment.cohort_id)
