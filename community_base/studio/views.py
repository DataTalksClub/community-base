from django.http import JsonResponse
from django.shortcuts import render

from community_base.kernel.decorators import staff_required
from community_base.studio.providers import dashboard_cards, search_results
from community_base.studio.registry import active_state


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
    return JsonResponse({"query": query, "results": results})
