from community_base.studio.registry import Destination, Section, register

KNOWLEDGE_BASE_STUDIO_ROUTES = (
    "knowledge_base_studio_page_list",
    "knowledge_base_studio_page_detail",
)


def register_studio():
    register(
        Section(
            slug="knowledge-base",
            title="Knowledge base",
            order=38,
            icon="book-open",
            destinations=(
                Destination(
                    key="knowledge-base-pages",
                    title="Pages",
                    url_name="knowledge_base_studio_page_list",
                    route_names=KNOWLEDGE_BASE_STUDIO_ROUTES,
                    order=10,
                ),
            ),
        )
    )
