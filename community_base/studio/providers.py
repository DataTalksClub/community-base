"""Extension registries for Studio search and dashboard content."""

from collections.abc import Callable, Iterable, Mapping

SearchProvider = Callable[[object, str], Mapping[str, Iterable[dict]]]
CardProvider = Callable[[object], Iterable[dict] | dict | None]

_search_providers: dict[str, SearchProvider] = {}
_card_providers: dict[str, CardProvider] = {}


def _register(registry: dict, kind: str, name: str, provider: Callable) -> Callable:
    if not name:
        raise ValueError(f"Studio {kind} provider name cannot be empty")
    if name in registry:
        raise ValueError(f"Studio {kind} provider already registered: {name}")
    if not callable(provider):
        raise TypeError(f"Studio {kind} provider must be callable")
    registry[name] = provider
    return provider


def register_search_provider(name: str, provider: SearchProvider) -> SearchProvider:
    return _register(_search_providers, "search", name, provider)


def register_card_provider(name: str, provider: CardProvider) -> CardProvider:
    return _register(_card_providers, "card", name, provider)


def search_results(request, query: str) -> dict[str, list[dict]]:
    merged: dict[str, list[dict]] = {}
    for provider in _search_providers.values():
        for group, items in provider(request, query).items():
            merged.setdefault(group, []).extend(list(items))
    return merged


def dashboard_cards(request) -> list[dict]:
    cards = []
    for provider in _card_providers.values():
        provided = provider(request)
        if provided is None:
            continue
        if isinstance(provided, dict):
            cards.append(provided)
        else:
            cards.extend(provided)
    return cards


def _clear() -> None:
    _search_providers.clear()
    _card_providers.clear()
