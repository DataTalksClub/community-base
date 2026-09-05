"""Generic list pagination helpers for Studio views."""

from django.core.paginator import Paginator

STUDIO_LIST_PAGE_SIZE = 25


def coerce_page_number(raw, num_pages):
    try:
        page_number = int(raw)
    except (TypeError, ValueError):
        return 1
    return min(max(page_number, 1), max(int(num_pages), 1))


def studio_pager_querystring(request, page_number, *, page_param="page"):
    params = request.GET.copy()
    params[page_param] = str(page_number)
    return "?" + params.urlencode()


def studio_pagination_context(
    request, queryset, *, per_page=STUDIO_LIST_PAGE_SIZE, page_param="page"
):
    paginator = Paginator(queryset, per_page)
    page = paginator.page(coerce_page_number(request.GET.get(page_param), paginator.num_pages))
    return {
        "page": page,
        "paginator": paginator,
        "show_pager": paginator.num_pages > 1,
        "pager_first_url": (
            studio_pager_querystring(request, 1, page_param=page_param)
            if page.has_previous()
            else None
        ),
        "pager_prev_url": (
            studio_pager_querystring(request, page.previous_page_number(), page_param=page_param)
            if page.has_previous()
            else None
        ),
        "pager_next_url": (
            studio_pager_querystring(request, page.next_page_number(), page_param=page_param)
            if page.has_next()
            else None
        ),
        "pager_last_url": (
            studio_pager_querystring(request, paginator.num_pages, page_param=page_param)
            if page.has_next()
            else None
        ),
        "page_start_index": page.start_index(),
        "page_end_index": page.end_index(),
        "filtered_total": paginator.count,
    }
