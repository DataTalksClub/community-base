from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from django.http import HttpRequest, JsonResponse
from django.urls import path as django_path

from community_base.api.auth import bearer_required
from community_base.api.errors import (
    APIError,
    error_response,
    method_not_allowed,
    permission_denied,
)


@dataclass(frozen=True, slots=True)
class Route:
    method: str
    path: str
    scope: str | None
    summary: str
    response: dict
    request: dict | None
    handler: Callable


_routes: list[Route] = []


def route(
    method: str,
    path: str,
    scope: str | None,
    summary: str,
    response: dict,
    request: dict | None = None,
) -> Callable:
    normalized_method = method.upper()
    normalized_path = path.strip("/")
    if normalized_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError(f"Unsupported API method: {method}")
    if not normalized_path:
        raise ValueError("API route path cannot be empty")

    def decorator(handler: Callable) -> Callable:
        if any(
            registered.method == normalized_method and registered.path == normalized_path
            for registered in _routes
        ):
            raise ValueError(f"Duplicate API route: {normalized_method} {normalized_path}")
        _routes.append(
            Route(
                method=normalized_method,
                path=normalized_path,
                scope=scope,
                summary=summary,
                response=response,
                request=request,
                handler=handler,
            )
        )
        return handler

    return decorator


def routes() -> tuple[Route, ...]:
    return tuple(_routes)


def clear() -> None:
    """Clear registrations. Intended for isolated registry tests."""
    _routes.clear()


def _dispatcher(entries: tuple[Route, ...]) -> Callable:
    by_method = {entry.method: entry for entry in entries}

    def authenticated_dispatch(request: HttpRequest, *args, **kwargs):
        entry = by_method.get(request.method)
        if entry is None:
            return error_response(request, method_not_allowed())
        if entry.scope and not request.api_key.allows((entry.scope,)):
            return error_response(request, permission_denied())

        try:
            return entry.handler(request, *args, **kwargs)
        except APIError as error:
            return error_response(request, error)

    return bearer_required(scopes=())(authenticated_dispatch)


def urlpatterns(*, namespace_prefix: str = "cb_api") -> list:
    grouped: dict[str, list[Route]] = defaultdict(list)
    for entry in _routes:
        grouped[entry.path].append(entry)
    return [
        django_path(
            route_path,
            _dispatcher(tuple(entries)),
            name=f"{namespace_prefix}_{index}",
        )
        for index, (route_path, entries) in enumerate(grouped.items(), start=1)
    ]


def json_response(payload: dict, *, status: int = 200) -> JsonResponse:
    return JsonResponse(payload, status=status)
