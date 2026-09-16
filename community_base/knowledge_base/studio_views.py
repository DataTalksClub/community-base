"""Studio screens for the knowledge base app (section: Knowledge base).

The screens are read-only inspection surfaces: pages are source-managed
whenever they carry provenance, and even Studio-authored pages are edited
through the site's own tooling. Studio exists so staff can see what is
published, where a page sits in the documentation tree, and where a row
came from.
"""

from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from community_base.kernel.decorators import staff_required
from community_base.knowledge_base.models import SECTION_CHOICES, KnowledgeBasePage

MAX_ANCESTORS = 20


def ancestors_of(page: KnowledgeBasePage) -> list[KnowledgeBasePage]:
    """Return the page's ancestors from the root down to its direct parent."""

    chain: list[KnowledgeBasePage] = []
    current = page
    seen = {page.pk}
    while current.parent_id is not None and len(chain) < MAX_ANCESTORS:
        current = current.parent
        if current.pk in seen:
            break
        seen.add(current.pk)
        chain.append(current)
    chain.reverse()
    return chain


@staff_required
def page_list(request):
    pages = KnowledgeBasePage.objects.select_related("parent").order_by("section", "slug")
    query = request.GET.get("q", "").strip()
    section = request.GET.get("section", "").strip()
    if query:
        pages = pages.filter(Q(title__icontains=query) | Q(slug__icontains=query))
    if section:
        pages = pages.filter(section=section)
    return render(
        request,
        "community_base/knowledge_base/studio/page_list.html",
        {"pages": pages, "q": query, "section": section, "section_choices": SECTION_CHOICES},
    )


@staff_required
def page_detail(request, page_id):
    page = get_object_or_404(KnowledgeBasePage, pk=page_id)
    return render(
        request,
        "community_base/knowledge_base/studio/page_detail.html",
        {
            "page": page,
            "children": page.children.order_by("nav_order", "title", "slug"),
            "ancestors": ancestors_of(page),
        },
    )
