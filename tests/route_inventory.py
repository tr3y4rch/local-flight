from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Iterator


@dataclass(frozen=True)
class RouteRecord:
    """Framework-neutral description of an effective application route."""

    path: str
    methods: tuple[str, ...]
    endpoint: str
    protocol: str


def effective_route_inventory(app_or_router: Any) -> tuple[RouteRecord, ...]:
    """Return every effective route, including routes in included routers and mounts.

    FastAPI 0.139 keeps included routers nested instead of copying their routes into
    the application's top-level route list. This helper deliberately uses feature
    detection rather than importing FastAPI's private nested-router classes, and it
    retains registration order and duplicate routes.
    """

    router = getattr(app_or_router, "router", app_or_router)
    routes = getattr(router, "routes", ())
    return tuple(_iter_routes(routes, prefix=""))


def _iter_routes(routes: Iterable[Any], *, prefix: str) -> Iterator[RouteRecord]:
    for route in routes:
        effective_contexts = getattr(route, "effective_route_contexts", None)
        if callable(effective_contexts):
            for context in effective_contexts():
                materialized = getattr(context, "starlette_route", None) or context
                yield from _iter_materialized_route(materialized, prefix=prefix)
            continue

        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        if original_router is not None and include_context is not None:
            include_prefix = str(getattr(include_context, "prefix", "") or "")
            yield from _iter_routes(
                getattr(original_router, "routes", ()),
                prefix=_join_paths(prefix, include_prefix),
            )
            continue

        yield from _iter_materialized_route(route, prefix=prefix)


def _iter_materialized_route(route: Any, *, prefix: str) -> Iterator[RouteRecord]:
    path = str(getattr(route, "path", "") or "")
    if not path:
        original_route = getattr(route, "original_route", None)
        path = str(getattr(original_route, "path", "") or "")
    full_path = _join_paths(prefix, path)

    mounted_routes = _route_children(route)
    methods = _route_methods(route)
    protocol = _route_protocol(route, methods=methods, mounted_routes=mounted_routes)
    yield RouteRecord(
        path=full_path,
        methods=methods,
        endpoint=_route_endpoint(route),
        protocol=protocol,
    )

    if mounted_routes is not None:
        yield from _iter_routes(mounted_routes, prefix=full_path)


def _route_children(route: Any) -> Iterable[Any] | None:
    try:
        routes = getattr(route, "routes", None)
    except (AssertionError, RuntimeError):
        return None
    if routes is None:
        return None
    return routes


def _route_methods(route: Any) -> tuple[str, ...]:
    methods = getattr(route, "methods", None)
    if methods is None:
        original_route = getattr(route, "original_route", None)
        methods = getattr(original_route, "methods", None)
    return tuple(sorted(str(method).upper() for method in (methods or ())))


def _route_protocol(
    route: Any,
    *,
    methods: tuple[str, ...],
    mounted_routes: Iterable[Any] | None,
) -> str:
    if mounted_routes is not None:
        return "mount"
    if methods:
        return "http"

    original_route = getattr(route, "original_route", None)
    route_names = {
        type(route).__name__.lower(),
        type(original_route).__name__.lower() if original_route is not None else "",
    }
    if any("websocket" in name for name in route_names):
        return "websocket"
    return "asgi"


def _route_endpoint(route: Any) -> str:
    endpoint = getattr(route, "endpoint", None)
    if endpoint is None:
        original_route = getattr(route, "original_route", None)
        endpoint = getattr(original_route, "endpoint", None)

    if endpoint is not None:
        module = str(getattr(endpoint, "__module__", "") or "")
        qualified_name = str(
            getattr(endpoint, "__qualname__", "")
            or getattr(endpoint, "__name__", "")
            or type(endpoint).__qualname__
        )
        return f"{module}.{qualified_name}" if module else qualified_name

    return str(getattr(route, "name", "") or "")


def _join_paths(prefix: str, path: str) -> str:
    if not prefix:
        return path or "/"
    if not path:
        return prefix or "/"
    if path == "/":
        return f"{prefix.rstrip('/')}/"
    return f"{prefix.rstrip('/')}/{path.lstrip('/')}"
