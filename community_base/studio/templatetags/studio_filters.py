"""Generic presentation vocabulary for shared Studio templates."""

from django import template
from django.contrib.auth import get_user_model
from django.template.defaultfilters import date as django_date
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from community_base.kernel.conf import get
from community_base.studio.impersonation import SESSION_KEY
from community_base.studio.registry import active_state

register = template.Library()

LIST_CLASSES = {
    "wrapper": "studio-responsive-table bg-card border border-border rounded-lg overflow-x-auto",
    "table": "w-full",
    "thead": "bg-secondary",
    "th": "text-left px-6 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider",
    "th_right": (
        "text-right px-6 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider"
    ),
    "tbody": "divide-y divide-border",
    "row": "hover:bg-secondary/50 transition-colors",
    "action_cell": "studio-actions-cell text-right",
    "action_group": "studio-action-group inline-flex flex-nowrap items-center justify-end gap-2",
    "action_form": "inline-flex",
}
ACTION_BASE = (
    "studio-action inline-flex items-center justify-center whitespace-nowrap rounded-md border "
    "px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none "
    "focus-visible:ring-2 focus-visible:ring-accent"
)
ACTION_KINDS = {
    "primary": "border-accent bg-accent text-accent-foreground hover:opacity-90",
    "secondary": "border-border bg-secondary text-foreground hover:bg-muted",
    "destructive": "border-red-500/40 text-red-400 hover:bg-red-500/10",
    "async": "border-blue-500/40 bg-blue-500/10 text-blue-200 hover:bg-blue-500/20",
}
STATUS_CLASSES = {
    "published": "bg-green-500/20 text-green-700 dark:text-green-300",
    "active": "bg-green-500/20 text-green-700 dark:text-green-300",
    "delivered": "bg-green-500/20 text-green-700 dark:text-green-300",
    "sent": "bg-green-500/20 text-green-700 dark:text-green-300",
    "draft": "bg-yellow-500/20 text-yellow-700 dark:text-yellow-300",
    "pending": "bg-yellow-500/20 text-yellow-700 dark:text-yellow-300",
    "running": "bg-blue-500/20 text-blue-700 dark:text-blue-300",
    "failed": "bg-red-500/20 text-red-700 dark:text-red-300",
    "cancelled": "bg-red-500/20 text-red-700 dark:text-red-300",
}
STATUS_OPTIONS = {
    "publication": (("draft", "Draft"), ("published", "Published")),
    "event": (
        ("draft", "Draft"),
        ("upcoming", "Upcoming"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ),
    "campaign": (("draft", "Draft"), ("sending", "Sending"), ("sent", "Sent")),
    "project": (("pending_review", "Pending Review"), ("published", "Published")),
}


@register.filter
def dict_get(dictionary, key):
    return dictionary.get(key) if isinstance(dictionary, dict) else None


@register.filter
def model_name(obj):
    return getattr(getattr(obj, "_meta", None), "model_name", "") or ""


def _format(value, fmt):
    return "" if value in (None, "") else django_date(value, fmt)


@register.filter
def operator_date(value):
    return _format(value, "Y-m-d")


@register.filter
def operator_datetime(value):
    return _format(value, "Y-m-d H:i")


@register.filter
def operator_datetime_seconds(value):
    return _format(value, "Y-m-d H:i:s")


@register.filter
def operator_datetime_tz(value):
    return _format(value, "Y-m-d H:i:s T")


@register.simple_tag
def studio_list_class(part="wrapper", align="left"):
    return LIST_CLASSES.get("th_right" if part == "th" and align == "right" else part, "")


@register.simple_tag
def studio_action_class(kind="secondary"):
    return f"{ACTION_BASE} {ACTION_KINDS.get(kind, ACTION_KINDS['secondary'])}"


@register.simple_block_tag(takes_context=True)
def studio_header_actions(context, content, title, **kwargs):
    return render_to_string(
        "community_base/studio/includes/header_actions.html",
        {**context.flatten(), **kwargs, "title": title, "actions": mark_safe(content.strip())},
    )


@register.simple_block_tag(takes_context=True)
def studio_overflow_menu(context, content):
    return render_to_string(
        "community_base/studio/includes/overflow_menu.html",
        {**context.flatten(), "items": mark_safe(content.strip())},
    )


@register.inclusion_tag("community_base/studio/includes/empty_state.html")
def studio_empty_state(kind, entity_label="", entity_label_plural="", **kwargs):
    return {
        "kind": kind,
        "entity_label": entity_label,
        "entity_label_plural": entity_label_plural or (f"{entity_label}s" if entity_label else ""),
        **kwargs,
    }


@register.inclusion_tag("community_base/studio/includes/list_filter_form.html")
def studio_list_filter(
    search="",
    status_filter="",
    placeholder="Search...",
    status_kind="publication",
    auto_submit=True,
):
    return {
        "search": search,
        "status_filter": status_filter,
        "placeholder": placeholder,
        "status_options": STATUS_OPTIONS.get(status_kind) if status_kind else None,
        "auto_submit": auto_submit,
    }


@register.inclusion_tag("community_base/studio/includes/status_badge.html")
def studio_status_badge(status, label=""):
    return {
        "label": label or str(status).replace("_", " ").title(),
        "classes": STATUS_CLASSES.get(status, "bg-secondary text-muted-foreground"),
    }


@register.inclusion_tag("community_base/studio/includes/list_action.html")
def studio_list_action(href, label, kind="secondary", new_tab=False, rel=""):
    return {
        "href": href,
        "label": label,
        "class_name": studio_action_class(kind),
        "new_tab": new_tab,
        "rel": rel,
    }


@register.simple_tag
def studio_sidebar_state(request):
    return active_state(request)


@register.simple_tag
def studio_title():
    return get("STUDIO_TITLE")


@register.inclusion_tag(
    "community_base/studio/includes/impersonation_banner.html", takes_context=True
)
def studio_impersonation_banner(context):
    request = context.get("request")
    actor_id = request.session.get(SESSION_KEY) if request else None
    actor = (
        get_user_model().objects.filter(pk=actor_id, is_superuser=True).first()
        if actor_id
        else None
    )
    return {"request": request, "impersonator": actor}
