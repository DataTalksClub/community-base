from dataclasses import dataclass


@dataclass(frozen=True)
class UserColumn:
    key: str
    label: str
    renderer: object


@dataclass(frozen=True)
class UserPanel:
    title: str
    template: str
    context_provider: object


_columns: dict[str, UserColumn] = {}
_badges: list[object] = []
_panels: list[UserPanel] = []


def register_user_column(key, label, renderer):
    if key in _columns:
        raise ValueError(f"Studio user column already registered: {key}")
    _columns[key] = UserColumn(key, label, renderer)
    return renderer


def register_user_badge(renderer):
    if renderer in _badges:
        raise ValueError("Studio user badge renderer already registered")
    _badges.append(renderer)
    return renderer


def register_user_panel(title, template, context_provider):
    if any(panel.title == title for panel in _panels):
        raise ValueError(f"Studio user panel already registered: {title}")
    panel = UserPanel(title, template, context_provider)
    _panels.append(panel)
    return panel


def user_columns():
    return tuple(_columns.values())


def user_badges():
    return tuple(_badges)


def user_panels():
    return tuple(_panels)


def _clear():
    _columns.clear()
    _badges.clear()
    _panels.clear()
