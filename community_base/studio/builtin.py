from community_base.studio.registry import Destination, Section, register, sections


def register_builtin_section() -> None:
    if any(section.slug == "home" for section in sections()):
        return
    register(
        Section(
            slug="home",
            title="",
            order=0,
            icon="layout-dashboard",
            destinations=(
                Destination(
                    key="dashboard",
                    title="Dashboard",
                    url_name="studio_dashboard",
                    route_names=("studio_dashboard",),
                    order=0,
                ),
            ),
        )
    )
