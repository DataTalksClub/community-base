import pytest
from django.core.exceptions import ImproperlyConfigured

from community_base.knowledge_base import hierarchy
from community_base.knowledge_base.models import (
    SECTION_WIKI,
    STATUS_DRAFT,
    KnowledgeBasePage,
)

pytestmark = pytest.mark.django_db


def make_page(*, section="docs", slug="page", title="Page", parent=None, nav_order=0, **fields):
    page = KnowledgeBasePage(
        section=section, slug=slug, title=title, parent=parent, nav_order=nav_order, **fields
    )
    page.full_clean()
    page.save()
    return page


def make_tree():
    index = make_page(slug="index", title="Documentation", nav_order=1)
    setup = make_page(slug="setup", title="Setup", parent=index, nav_order=10)
    advanced = make_page(slug="advanced", title="Advanced usage", parent=index, nav_order=20)
    return index, setup, advanced


def test_two_level_documentation_tree_orders_siblings_by_nav_order():
    index, setup, advanced = make_tree()
    tree = hierarchy.navigation_tree()
    assert [item.slug for item in tree.roots] == ["index"]
    assert [child.slug for child in tree.roots[0].children] == ["setup", "advanced"]
    assert tree.by_slug["setup"].page.pk == setup.pk
    assert [item.slug for item in tree.preorder] == ["index", "setup", "advanced"]


def test_nav_order_ties_break_by_title():
    index = make_page(slug="index", title="Documentation")
    make_page(slug="beta", title="Beta", parent=index, nav_order=5)
    make_page(slug="alpha", title="Alpha", parent=index, nav_order=5)
    tree = hierarchy.navigation_tree()
    assert [child.slug for child in tree.roots[0].children] == ["alpha", "beta"]


def test_draft_parent_does_not_hide_published_children():
    index, setup, advanced = make_tree()
    KnowledgeBasePage.objects.filter(pk=index.pk).update(status=STATUS_DRAFT)
    tree = hierarchy.navigation_tree()
    assert [item.slug for item in tree.roots] == ["setup", "advanced"]


def test_parent_cycle_raises_instead_of_rendering():
    index, setup, _advanced = make_tree()
    KnowledgeBasePage.objects.filter(pk=index.pk).update(parent_id=setup.pk)
    with pytest.raises(ImproperlyConfigured):
        hierarchy.navigation_tree()


def test_breadcrumbs_run_from_the_root_to_the_direct_parent():
    index, setup, advanced = make_tree()
    assert hierarchy.breadcrumbs(advanced) == (index,)
    assert hierarchy.breadcrumbs(index) == ()


def test_sequential_navigation_follows_the_depth_first_preorder():
    index, setup, advanced = make_tree()
    assert hierarchy.sequential_navigation(index) == (None, setup)
    assert hierarchy.sequential_navigation(setup) == (index, advanced)
    assert hierarchy.sequential_navigation(advanced) == (setup, None)


def test_wiki_pages_form_a_flat_title_ordered_set():
    make_page(section=SECTION_WIKI, slug="billing-faq", title="Billing FAQ")
    make_page(section=SECTION_WIKI, slug="getting-started", title="A getting started guide")
    assert [page.slug for page in hierarchy.wiki_pages()] == ["getting-started", "billing-faq"]


def test_children_of_a_wiki_page_is_always_empty():
    page = make_page(section=SECTION_WIKI, slug="faq", title="FAQ")
    assert hierarchy.children_of(page) == ()
