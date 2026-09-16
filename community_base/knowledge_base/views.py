"""Default public knowledge base views.

Sites may mount these routes as-is or serve the same rows from their own
routes and templates: per decision D18 the templates shipped here are
overridable defaults (a site wins by placing a file at the same path in its
own templates directory), and the markup uses only the shared ``cb-`` hooks
so the site's stylesheet styles them.
"""

from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from community_base.knowledge_base import hierarchy
from community_base.knowledge_base.models import SECTION_DOCS, SECTION_WIKI, KnowledgeBasePage

MAX_DOCS_DEPTH = 20


@require_GET
def wiki_home(request):
    return render(request, "knowledge_base/wiki_home.html", {"pages": hierarchy.wiki_pages()})


@require_GET
def docs_home(request):
    return render(request, "knowledge_base/docs_home.html", {"tree": hierarchy.navigation_tree()})


@require_GET
def wiki_page(request, slug: str):
    page = get_object_or_404(hierarchy.published_pages(SECTION_WIKI), slug=slug)
    return _render_page(request, page, sequential=False)


@require_GET
def docs_page(request, page_path: str):
    segments = [segment for segment in page_path.split("/") if segment]
    if len(segments) > MAX_DOCS_DEPTH:
        raise Http404("Documentation path is too deep.")
    page: KnowledgeBasePage | None = None
    for segment in segments:
        queryset = hierarchy.published_pages(SECTION_DOCS)
        queryset = (
            queryset.filter(parent__isnull=True) if page is None else queryset.filter(parent=page)
        )
        page = get_object_or_404(queryset, slug=segment)
    return _render_page(request, page, sequential=True)


def _render_page(request, page: KnowledgeBasePage, *, sequential: bool):
    previous = following = None
    if sequential:
        previous, following = hierarchy.sequential_navigation(page)
    return render(
        request,
        "knowledge_base/page_detail.html",
        {
            "page": page,
            "ancestors": hierarchy.breadcrumbs(page),
            "children": hierarchy.children_of(page),
            "previous": previous,
            "next": following,
        },
    )
