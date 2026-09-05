from django.test import RequestFactory

from community_base.studio.utils import studio_pagination_context


def test_pager_clamps_page_and_preserves_filters():
    request = RequestFactory().get("/studio/items/", {"q": "needle", "page": "99"})

    context = studio_pagination_context(request, list(range(60)))

    assert context["page"].number == 3
    assert context["page_start_index"] == 51
    assert context["page_end_index"] == 60
    assert context["pager_prev_url"] == "?q=needle&page=2"
    assert context["pager_next_url"] is None
