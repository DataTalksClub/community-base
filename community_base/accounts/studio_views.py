from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render

from community_base.accounts.models import EmailChangeRequest, ImportBatch, PrivacyRequestLog
from community_base.accounts.services.import_users import rows_from_csv, run_import_batch
from community_base.accounts.services.merge import MergeError, merge_accounts
from community_base.accounts.studio_forms import (
    StaffImportForm,
    StaffMergeForm,
    StaffUserCreateForm,
)
from community_base.kernel.decorators import staff_required


def _operations_context(**extra):
    return {
        "import_batches": ImportBatch.objects.select_related("actor")[:20],
        "privacy_requests": PrivacyRequestLog.objects.all()[:20],
        "email_changes": EmailChangeRequest.objects.select_related("user")[:20],
        **extra,
    }


@staff_required
def account_operations(request):
    return render(
        request,
        "community_base/accounts/studio/operations.html",
        _operations_context(),
    )


@staff_required
def user_create(request):
    form = StaffUserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, "Account created.")
        return redirect("studio_user_detail", user_id=user.pk)
    return render(
        request,
        "community_base/accounts/studio/user_create.html",
        {"form": form},
        status=400 if request.method == "POST" else 200,
    )


@staff_required
def user_import(request):
    result = None
    form = StaffImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            result = run_import_batch(
                form.cleaned_data["source"],
                rows_from_csv(form.cleaned_data["csv_file"]),
                actor=request.user,
                dry_run=form.cleaned_data["dry_run"],
                send_welcome=form.cleaned_data["send_welcome"],
                default_tags=form.parsed_tags(),
                params={"filename": request.FILES["csv_file"].name},
            )
        except (TypeError, ValueError) as error:
            form.add_error("csv_file", str(error))
        else:
            if result.batch is not None:
                messages.success(request, "Import completed.")
                return redirect("accounts_studio_import_detail", batch_id=result.batch.pk)
    return render(
        request,
        "community_base/accounts/studio/user_import.html",
        {"form": form, "result": result},
        status=400 if request.method == "POST" and result is None else 200,
    )


@staff_required
def import_detail(request, batch_id):
    batch = get_object_or_404(ImportBatch.objects.select_related("actor"), pk=batch_id)
    return render(
        request,
        "community_base/accounts/studio/import_detail.html",
        {"batch": batch},
    )


@staff_required
def user_merge(request):
    result = None
    form = StaffMergeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        canonical = get_object_or_404(get_user_model(), pk=form.cleaned_data["canonical_user_id"])
        secondary = get_object_or_404(get_user_model(), pk=form.cleaned_data["secondary_user_id"])
        try:
            result = merge_accounts(
                canonical,
                secondary,
                actor=request.user,
                dry_run=form.cleaned_data["dry_run"],
                force=request.user.is_superuser,
            )
        except MergeError as error:
            form.add_error(None, str(error))
        else:
            if not result.dry_run:
                messages.success(request, "Accounts merged.")
                return redirect("studio_user_detail", user_id=canonical.pk)
    return render(
        request,
        "community_base/accounts/studio/user_merge.html",
        {"form": form, "result": result},
        status=400 if request.method == "POST" and result is None else 200,
    )


@staff_required
def privacy_request_detail(request, request_id):
    privacy_request = get_object_or_404(PrivacyRequestLog, pk=request_id)
    return render(
        request,
        "community_base/accounts/studio/privacy_request_detail.html",
        {"privacy_request": privacy_request},
    )


@staff_required
def email_change_detail(request, change_id):
    change = get_object_or_404(EmailChangeRequest.objects.select_related("user"), pk=change_id)
    return render(
        request,
        "community_base/accounts/studio/email_change_detail.html",
        {"change": change},
    )
