"""I/O-free operations shared by the sync and async clients.

Each operation is a generator that yields ``(path, payload)`` requests, receives the
unwrapped ``data`` of each response, and returns its result. Errors raised by the
transport are thrown into the generator, so an operation can handle them. ``drive`` and
``drive_async`` run an operation against a session.
"""

import re
from collections.abc import Awaitable, Callable, Generator
from typing import Any, TypeVar, cast

from pydantic import BaseModel, ValidationError

from docmost_client.errors import (
    DocmostError,
    InvalidRequestError,
    NotFoundError,
    SpaceNotAllowedError,
    UpstreamError,
)
from docmost_client.models import (
    CONTENT_FORMATS,
    ContentFormat,
    CurrentUser,
    Page,
    PageSummary,
    Paginated,
    SearchHit,
    Space,
)
from docmost_client.policy import SpaceAllowlist

T = TypeVar("T")
M = TypeVar("M", Space, PageSummary)
B = TypeVar("B", bound=BaseModel)

Request = tuple[str, dict[str, Any]]
Op = Generator[Request, Any, T]

MAX_PAGE_SIZE = 100
MAX_SEARCH_RESULTS = 50

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def drive(op: Op[T], call: Callable[[str, dict[str, Any]], Any]) -> T:
    """Run ``op`` with a blocking ``call(path, payload)``."""
    try:
        request = next(op)
        while True:
            try:
                data = call(*request)
            except DocmostError as exc:
                request = op.throw(exc)
            else:
                request = op.send(data)
    except StopIteration as stop:
        return cast(T, stop.value)


async def drive_async(op: Op[T], call: Callable[[str, dict[str, Any]], Awaitable[Any]]) -> T:
    """Run ``op`` with an awaitable ``call(path, payload)``."""
    try:
        request = next(op)
        while True:
            try:
                data = await call(*request)
            except DocmostError as exc:
                request = op.throw(exc)
            else:
                request = op.send(data)
    except StopIteration as stop:
        return cast(T, stop.value)


def is_uuid(value: str) -> bool:
    return _UUID.match(value) is not None


def me() -> Op[CurrentUser]:
    data = yield ("/users/me", {})
    return _parse(CurrentUser, _object(data))


def server_version() -> Op[str | None]:
    data = yield ("/version", {})
    if not isinstance(data, dict):
        return None
    version = cast(dict[str, Any], data).get("currentVersion")
    return version if isinstance(version, str) and version else None


def list_spaces(
    allowlist: SpaceAllowlist, limit: int, cursor: str | None, query: str | None
) -> Op[Paginated[Space]]:
    payload = _pagination(limit, cursor)
    if query:
        payload["query"] = query
    data = yield ("/spaces", payload)
    page = _paginated(Space, data)
    visible = [space for space in page.items if allowlist.allows(space.id, space.slug)]
    return page.model_copy(update={"items": visible})


def get_space(allowlist: SpaceAllowlist, space: str) -> Op[Space]:
    resolved = yield from _fetch_space(space)
    yield from require_space(allowlist, resolved.id, resolved.slug)
    return resolved


def resolve_space_id(allowlist: SpaceAllowlist, space: str) -> Op[str]:
    """Return the UUID of an allowed space given its UUID or slug."""
    if is_uuid(space):
        yield from require_space(allowlist, space, None)
        return space
    resolved = yield from get_space(allowlist, space)
    return resolved.id


def require_space(allowlist: SpaceAllowlist, space_id: str, slug: str | None) -> Op[None]:
    """Raise SpaceNotAllowedError unless the space is in the allowlist."""
    decision = allowlist.allows(space_id, slug)
    if decision is None:
        yield from _resolve_allowlist(allowlist)
        decision = allowlist.allows(space_id, None)
    if not decision:
        raise SpaceNotAllowedError(
            "The space is not in DOCMOST_ALLOWED_SPACES; this client cannot access it."
        )


def get_page(allowlist: SpaceAllowlist, page_id: str, format: ContentFormat) -> Op[Page]:
    check_format(format)
    if not page_id.strip():
        raise InvalidRequestError("page_id must be a page ID or slug ID.")
    data = yield ("/pages/info", {"pageId": page_id, "format": format})
    page = _parse(Page, {**_object(data), "format": format})
    slug = page.space.slug if page.space is not None else None
    yield from require_space(allowlist, page.space_id, slug)
    if page.deleted_at is not None:
        raise NotFoundError("The page is in the trash.")
    return page


def list_children(
    allowlist: SpaceAllowlist,
    space: str | None,
    parent_page_id: str | None,
    limit: int,
    cursor: str | None,
) -> Op[Paginated[PageSummary]]:
    payload = _pagination(limit, cursor)
    if parent_page_id:
        if not is_uuid(parent_page_id):
            parent = yield from get_page(allowlist, parent_page_id, "markdown")
            parent_page_id = parent.id
        payload["pageId"] = parent_page_id
    elif space:
        payload["spaceId"] = yield from resolve_space_id(allowlist, space)
    else:
        raise InvalidRequestError("Provide a space or parent_page_id.")
    data = yield ("/pages/sidebar-pages", payload)
    page = _paginated(PageSummary, data)
    for space_id in {item.space_id for item in page.items}:
        yield from require_space(allowlist, space_id, None)
    return page


def search(
    allowlist: SpaceAllowlist,
    query: str,
    space: str | None,
    limit: int,
    offset: int,
    title_only: bool,
) -> Op[list[SearchHit]]:
    query = query.strip()
    if not query:
        raise InvalidRequestError("query must not be empty.")
    if not 1 <= limit <= MAX_SEARCH_RESULTS:
        raise InvalidRequestError(f"limit must be between 1 and {MAX_SEARCH_RESULTS}.")
    if offset < 0:
        raise InvalidRequestError("offset must not be negative.")
    payload: dict[str, Any] = {"query": query, "limit": limit, "offset": offset}
    if space:
        payload["spaceId"] = yield from resolve_space_id(allowlist, space)
    if title_only:
        payload["titleOnly"] = True
    data = yield ("/search", payload)
    hits = [_parse(SearchHit, item) for item in _items(data)]
    return [hit for hit in hits if allowlist.allows(hit.space.id, hit.space.slug)]


def _fetch_space(space: str) -> Op[Space]:
    if not space.strip():
        raise InvalidRequestError("space must be a space slug or ID.")
    data = yield ("/spaces/info", {"spaceId": space})
    return _parse(Space, _object(data))


def _resolve_allowlist(allowlist: SpaceAllowlist) -> Op[None]:
    ids: set[str] = set()
    for entry in sorted(allowlist.entries or ()):
        if is_uuid(entry):
            ids.add(entry)
            continue
        try:
            space = yield from _fetch_space(entry)
        except NotFoundError:
            continue  # Unknown or inaccessible spaces grant nothing.
        ids.add(space.id)
    allowlist.resolved(frozenset(ids))


def check_format(format: str) -> None:
    if format not in CONTENT_FORMATS:
        raise InvalidRequestError(f"format must be one of: {', '.join(CONTENT_FORMATS)}.")


def _pagination(limit: int, cursor: str | None) -> dict[str, Any]:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise InvalidRequestError(f"limit must be between 1 and {MAX_PAGE_SIZE}.")
    payload: dict[str, Any] = {"limit": limit}
    if cursor:
        payload["cursor"] = cursor
    return payload


def _paginated(model: type[M], data: Any) -> Paginated[M]:
    body = _object(data)
    meta = body.get("meta")
    meta_dict = cast(dict[str, Any], meta) if isinstance(meta, dict) else {}
    next_cursor = meta_dict.get("nextCursor")
    return Paginated[model](
        items=[_parse(model, item) for item in _items(body)],
        has_next_page=bool(meta_dict.get("hasNextPage", False)),
        next_cursor=next_cursor if isinstance(next_cursor, str) else None,
    )


def _parse(model: type[B], data: Any) -> B:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        # Never include the validation details: they echo input values (page bodies).
        raise UpstreamError(
            f"Docmost returned a {model.__name__} this client cannot parse "
            f"({exc.error_count()} field errors); the server version may be unsupported."
        ) from None


def _object(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise UpstreamError("Docmost returned an unexpected response shape.")
    return cast(dict[str, Any], data)


def _items(data: Any) -> list[Any]:
    items = _object(data).get("items")
    if not isinstance(items, list):
        raise UpstreamError("Docmost returned an unexpected response shape.")
    return cast(list[Any], items)
