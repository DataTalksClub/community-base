import csv
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from community_base.kernel.decorators import staff_required
from community_base.studio.models import MemberNote
from community_base.studio.user_registry import user_badges, user_columns, user_panels
from community_base.studio.user_tags import get_tags, normalize_tag, normalize_tags, set_tags
from community_base.studio.utils import studio_pagination_context

PAGE_SIZE = 25
SEARCH_FIELDS = ("username", "email", "first_name", "last_name")
STATUS_FILTERS = {"active", "staff", "inactive"}


def _model_fields():
    return {field.name for field in get_user_model()._meta.get_fields()}


def _display_name(user):
    full_name = user.get_full_name().strip() if hasattr(user, "get_full_name") else ""
    return full_name or getattr(user, "email", "") or user.get_username()


def _status(user):
    if not user.is_active:
        return "inactive"
    return "staff" if user.is_staff else "active"


def _choice(value, choices, default):
    allowed = {item.value for item in choices}
    return value if value in allowed else default


def _filtered_users(request):
    fields = _model_fields()
    queryset = get_user_model()._default_manager.all()
    query = request.GET.get("q", "").strip()
    if query:
        predicate = Q()
        for field in SEARCH_FIELDS:
            if field in fields:
                predicate |= Q(**{f"{field}__icontains": query})
        queryset = queryset.filter(predicate)

    status = request.GET.get("status", "")
    if status == "active":
        queryset = queryset.filter(is_active=True, is_staff=False)
    elif status == "staff":
        queryset = queryset.filter(is_staff=True)
    elif status == "inactive":
        queryset = queryset.filter(is_active=False)

    ordering = "-date_joined" if "date_joined" in fields else "-pk"
    users = list(queryset.order_by(ordering, "-pk" if ordering != "-pk" else "pk"))
    tag = normalize_tag(request.GET.get("tag", ""))
    if tag:
        users = [user for user in users if tag in get_tags(user)]
    return users, query, status if status in STATUS_FILTERS else "", tag


def _row(user):
    return {
        "user": user,
        "display_name": _display_name(user),
        "status": _status(user),
        "tags": get_tags(user),
        "columns": [
            {"definition": column, "value": column.renderer(user)} for column in user_columns()
        ],
    }


def _known_tags(users):
    return sorted({tag for user in users for tag in get_tags(user)})


@staff_required
def user_list(request):
    users, query, status, tag = _filtered_users(request)
    pager = studio_pagination_context(request, users, per_page=PAGE_SIZE)
    rows = [_row(user) for user in pager["page"].object_list]
    return render(
        request,
        "community_base/studio/users/list.html",
        {
            **pager,
            "rows": rows,
            "columns": user_columns(),
            "query": query,
            "status": status,
            "tag": tag,
            "known_tags": _known_tags(users),
            "export_query": urlencode(request.GET, doseq=True),
        },
    )


@staff_required
def user_export(request):
    users, _, _, _ = _filtered_users(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="community-users.csv"'
    writer = csv.writer(response)
    columns = user_columns()
    writer.writerow(["id", "username", "email", "status", "tags", *[c.key for c in columns]])
    for user in users:
        writer.writerow(
            [
                user.pk,
                user.get_username(),
                getattr(user, "email", ""),
                _status(user),
                ",".join(get_tags(user)),
                *[column.renderer(user) for column in columns],
            ]
        )
    return response


@staff_required
def user_detail(request, user_id):
    detail_user = get_object_or_404(get_user_model(), pk=user_id)
    panels = []
    for panel in user_panels():
        context = panel.context_provider(request, detail_user) or {}
        panels.append(
            {
                "title": panel.title,
                "html": render_to_string(
                    panel.template,
                    {**context, "detail_user": detail_user},
                    request=request,
                ),
            }
        )
    return render(
        request,
        "community_base/studio/users/detail.html",
        {
            "detail_user": detail_user,
            "display_name": _display_name(detail_user),
            "status": _status(detail_user),
            "tags": get_tags(detail_user),
            "badges": [renderer(detail_user) for renderer in user_badges()],
            "panels": panels,
            "notes": MemberNote.objects.filter(member=detail_user).select_related("created_by"),
            "note_kinds": MemberNote.Kind.choices,
            "note_visibilities": MemberNote.Visibility.choices,
        },
    )


@staff_required
@require_POST
def user_tag_add(request, user_id):
    user = get_object_or_404(get_user_model(), pk=user_id)
    tag = normalize_tag(request.POST.get("tag"))
    if tag:
        set_tags(user, [*get_tags(user), tag])
        messages.success(request, f'Added tag "{tag}".')
    else:
        messages.error(request, "Enter a tag.")
    return redirect("studio_user_detail", user_id=user.pk)


@staff_required
@require_POST
def user_tag_remove(request, user_id, tag):
    user = get_object_or_404(get_user_model(), pk=user_id)
    normalized = normalize_tag(tag)
    set_tags(user, [item for item in get_tags(user) if item != normalized])
    messages.success(request, f'Removed tag "{normalized}".')
    return redirect("studio_user_detail", user_id=user.pk)


@staff_required
@require_POST
def note_create(request, user_id):
    member = get_object_or_404(get_user_model(), pk=user_id)
    body = request.POST.get("body", "").strip()
    if not body:
        messages.error(request, "Note body is required.")
    else:
        MemberNote.objects.create(
            member=member,
            created_by=request.user,
            body=body,
            kind=_choice(request.POST.get("kind"), MemberNote.Kind, MemberNote.Kind.GENERAL),
            visibility=_choice(
                request.POST.get("visibility"),
                MemberNote.Visibility,
                MemberNote.Visibility.INTERNAL,
            ),
            tags=normalize_tags(request.POST.get("tags", "").split(",")),
        )
        messages.success(request, "Member note added.")
    return redirect("studio_user_detail", user_id=member.pk)


@staff_required
def note_edit(request, user_id, note_id):
    member = get_object_or_404(get_user_model(), pk=user_id)
    note = get_object_or_404(MemberNote, pk=note_id, member=member)
    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        if not body:
            messages.error(request, "Note body is required.")
        else:
            note.body = body
            note.kind = _choice(request.POST.get("kind"), MemberNote.Kind, note.kind)
            note.visibility = _choice(
                request.POST.get("visibility"), MemberNote.Visibility, note.visibility
            )
            note.tags = normalize_tags(request.POST.get("tags", "").split(","))
            note.save()
            messages.success(request, "Member note updated.")
            return redirect("studio_user_detail", user_id=member.pk)
    return render(
        request,
        "community_base/studio/users/note_form.html",
        {
            "detail_user": member,
            "note": note,
            "note_kinds": MemberNote.Kind.choices,
            "note_visibilities": MemberNote.Visibility.choices,
        },
        status=400 if request.method == "POST" else 200,
    )


@staff_required
@require_POST
def note_delete(request, user_id, note_id):
    member = get_object_or_404(get_user_model(), pk=user_id)
    note = get_object_or_404(MemberNote, pk=note_id, member=member)
    note.delete()
    messages.success(request, "Member note deleted.")
    return redirect("studio_user_detail", user_id=member.pk)
