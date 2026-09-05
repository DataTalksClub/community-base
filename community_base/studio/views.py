from django.http import JsonResponse
from django.shortcuts import render

from community_base.kernel.decorators import staff_required
from community_base.studio.providers import dashboard_cards, search_results
from community_base.studio.registry import active_state


def _navigation_results(request, query):
    matches = []
    query = query.casefold()
    for section in active_state(request)["sections"]:
        for row in section["destinations"]:
            destination = row["destination"]
            if row["url"] and query in destination.title.casefold():
                matches.append(
                    {
                        "label": destination.title,
                        "url": row["url"],
                        "type": "Page",
                        "summary": section["section"].title or "Studio",
                    }
                )
    return matches


@staff_required
def dashboard(request):
    return render(
        request,
        "community_base/studio/dashboard.html",
        {"cards": dashboard_cards(request), "studio_state": active_state(request)},
    )


@staff_required
def global_search(request):
    query = request.GET.get("q", "").strip()
    results = search_results(request, query) if len(query) >= 2 else {}
    if query:
        pages = _navigation_results(request, query)
        if pages:
            results = {**results, "pages": pages + results.get("pages", [])}
    return JsonResponse({"query": query, "results": results})
