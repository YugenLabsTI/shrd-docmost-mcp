"""I/O-free operations shared by the sync and async clients.

Each operation is a generator that yields ``(path, payload)`` requests, receives the
unwrapped ``data`` of each response, and returns its result. Errors raised by the
transport are thrown into the generator, so an operation can handle them. ``drive`` and
``drive_async`` run an operation against a session.
"""

import json
import re
from collections.abc import Awaitable, Callable, Generator
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar, cast

from pydantic import BaseModel, ValidationError

from docmost_client._content import (
    check_content,
    check_mentions,
    check_size,
    comment_document,
    mention_keys,
    page_mentions,
    top_level_headings,
)
from docmost_client._sections import SECTION_OPERATIONS, SectionOperation, splice_section
from docmost_client.errors import (
    CommentsDisabledError,
    DocmostError,
    InvalidRequestError,
    NotFoundError,
    PageBusyError,
    PermissionDeniedError,
    ReadOnlyError,
    SpaceNotAllowedError,
    StalePageError,
    UpstreamError,
)
from docmost_client.models import (
    CONTENT_FORMATS,
    CONTENT_OPERATIONS,
    Comment,
    ContentFormat,
    ContentOperation,
    CurrentUser,
    Heading,
    Page,
    PageOutline,
    PageSummary,
    Paginated,
    RecentPage,
    SearchHit,
    SearchResults,
    Space,
)
from docmost_client.policy import SpaceAllowlist
from docmost_client.settings import DocmostSettings

T = TypeVar("T")
M = TypeVar("M", Space, PageSummary, RecentPage, Comment)
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


def get_page_outline(allowlist: SpaceAllowlist, page_id: str) -> Op[PageOutline]:
    page = yield from get_page(allowlist, page_id, "json")
    headings = [
        Heading(id=heading_id, level=level, text=text)
        for heading_id, level, text in top_level_headings(page.content)
    ]
    return PageOutline(
        page_id=page.id, title=page.title, updated_at=page.updated_at, headings=headings
    )


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


def list_recent_pages(
    allowlist: SpaceAllowlist, space: str | None, limit: int, cursor: str | None
) -> Op[Paginated[RecentPage]]:
    payload = _pagination(limit, cursor)
    # With a single allowed space, ask Docmost for that space directly: filtering a
    # workspace-wide feed would return short or empty pages.
    space = space or allowlist.single_entry
    if space:
        payload["spaceId"] = yield from resolve_space_id(allowlist, space)
    data = yield ("/pages/recent", payload)
    page = _paginated(RecentPage, data)
    visible = [item for item in page.items if allowlist.allows(item.space.id, item.space.slug)]
    return page.model_copy(update={"items": visible})


def list_comments(
    allowlist: SpaceAllowlist, page_id: str, limit: int, cursor: str | None
) -> Op[Paginated[Comment]]:
    payload = _pagination(limit, cursor)
    page = yield from _checked_page(allowlist, page_id)
    data = yield ("/comments", {"pageId": page.id, **payload})
    comments = _paginated(Comment, data)
    visible = [comment for comment in comments.items if comment.deleted_at is None]
    return comments.model_copy(update={"items": visible})


def create_comment(
    settings: DocmostSettings,
    allowlist: SpaceAllowlist,
    page_id: str,
    text: str,
    parent_comment_id: str | None,
) -> Op[Comment]:
    if not settings.allow_comments:
        raise CommentsDisabledError(
            "Adding comments is disabled; set DOCMOST_ALLOW_COMMENTS=1 to enable it."
        )
    if not text.strip():
        raise InvalidRequestError("text must not be empty.")
    if parent_comment_id is not None and not is_uuid(parent_comment_id):
        raise InvalidRequestError("parent_comment_id must be a comment ID.")
    document = json.dumps(comment_document(text), ensure_ascii=False, separators=(",", ":"))
    check_size(document, settings.max_content_bytes)

    page = yield from _checked_page(allowlist, page_id)
    payload: dict[str, Any] = {"pageId": page.id, "content": document, "type": "page"}
    if parent_comment_id is not None:
        payload["parentCommentId"] = parent_comment_id
    try:
        data = yield ("/comments/create", payload)
    except PermissionDeniedError as exc:
        raise PermissionDeniedError(
            f"{exc} The account cannot comment on this page: it needs edit access there "
            "(letting readers comment is a Docmost Enterprise feature).",
            status_code=exc.status_code,
        ) from None
    return _parse(Comment, _object(data))


def _checked_page(allowlist: SpaceAllowlist, page_id: str) -> Op[Page]:
    """Precheck a page (allowlist, trash, UUID) before acting on its comments.

    Docmost always returns the page content; the json format is the cheapest because the
    server returns the stored document without converting it.
    """
    page = yield from get_page(allowlist, page_id, "json")
    return page


def search(
    allowlist: SpaceAllowlist,
    query: str,
    space: str | None,
    limit: int,
    offset: int,
    title_only: bool,
) -> Op[SearchResults]:
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
    return SearchResults(
        hits=[hit for hit in hits if allowlist.allows(hit.space.id, hit.space.slug)],
        next_offset=offset + limit if len(hits) == limit else None,
    )


def create_page(
    settings: DocmostSettings,
    allowlist: SpaceAllowlist,
    *,
    space: str,
    title: str | None,
    content: str | dict[str, Any] | None,
    format: ContentFormat,
    parent_page_id: str | None,
    icon: str | None,
) -> Op[Page]:
    _require_writable(settings)
    check_format(format)
    if content is not None:
        check_content(content, format, settings.max_content_bytes)
    space_id = yield from resolve_space_id(allowlist, space)
    payload: dict[str, Any] = {"spaceId": space_id}
    if parent_page_id is not None:
        # Docmost checks this too; checking here keeps the allowlist enforced client-side.
        parent = yield from get_page(allowlist, parent_page_id, "markdown")
        if parent.space_id != space_id:
            raise InvalidRequestError("The parent page belongs to a different space.")
        parent_page_id = parent.id
    if title is not None:
        payload["title"] = title
    if icon is not None:
        payload["icon"] = icon
    if parent_page_id is not None:
        payload["parentPageId"] = parent_page_id
    if content is not None:
        payload["content"] = content
        payload["format"] = format
    data = yield ("/pages/create", payload)
    # Docmost returns the new page without its content.
    return _parse(Page, {**_object(data), "content": None, "format": format})


def update_page(
    settings: DocmostSettings,
    allowlist: SpaceAllowlist,
    page_id: str,
    *,
    content: str | dict[str, Any] | None,
    operation: ContentOperation | None,
    format: ContentFormat,
    title: str | None,
    icon: str | None,
    expected_updated_at: datetime | None,
) -> Op[Page]:
    _require_writable(settings)
    check_format(format)
    if operation is not None and operation not in CONTENT_OPERATIONS:
        raise InvalidRequestError(f"operation must be one of: {', '.join(CONTENT_OPERATIONS)}.")
    if content is not None and operation is None:
        raise InvalidRequestError("content requires an operation (append, prepend, or replace).")
    if operation is not None and content is None:
        raise InvalidRequestError("operation requires content.")
    if content is None and title is None and icon is None:
        raise InvalidRequestError("Nothing to update: provide content, title, or icon.")
    if content is not None:
        check_content(content, format, settings.max_content_bytes, mentions="defer")
    if expected_updated_at is not None and expected_updated_at.utcoffset() is None:
        raise InvalidRequestError(
            "expected_updated_at must include a timezone (use the updated_at returned by get_page)."
        )

    current = yield from get_page(allowlist, page_id, format)
    if current.is_locked:
        raise PermissionDeniedError("The page is locked; unlock it in Docmost before editing.")
    if current.can_edit is False:
        raise PermissionDeniedError("The account cannot edit this page.")
    if expected_updated_at is not None and current.updated_at != expected_updated_at:
        raise StalePageError(
            "The page changed since it was read: it was updated at "
            f"{current.updated_at.isoformat()}, not {expected_updated_at.isoformat()}. "
            "Read it again and reapply the change.",
            current_updated_at=current.updated_at,
        )
    if content is not None and mention_keys(content, format):
        # Docmost's markdown output may drop mention markup: compare against the JSON.
        if format == "markdown":
            snapshot = yield from get_page(allowlist, current.id, "json")
            existing = page_mentions(snapshot.content, "json")
        else:
            existing = page_mentions(current.content, format)
        check_mentions(content, format, existing)

    # Never send spaceId or parentPageId: v0.96.0 ignores them, a later version may not.
    payload: dict[str, Any] = {"pageId": current.id}
    if title is not None:
        payload["title"] = title
    if icon is not None:
        payload["icon"] = icon
    if content is not None:
        payload["content"] = content
        payload["operation"] = operation
    payload["format"] = format
    data = yield ("/pages/update", payload)
    result = _parse(Page, {**_object(data), "format": format})
    # append/prepend always add blocks, so unchanged content means the write was dropped.
    # A replace can legitimately store the same content (Docmost normalizes input).
    if operation in ("append", "prepend") and result.content == current.content:
        raise UpstreamError(
            "Docmost accepted the update but the page content did not change. Content writes "
            "are a silent no-op when the server runs with COLLAB_DISABLE_REDIS=true, or when "
            "the server failed to persist the document; check the Docmost logs."
        )
    return result


# Docmost persists editor changes up to ~45 s late; a page saved within this window may
# be open in someone's editor with unsaved edits that a whole-page rewrite would discard.
# The default of DOCMOST_BUSY_WINDOW_SECONDS.
BUSY_WINDOW = timedelta(seconds=60)
# Docmost's clock is trusted only this close to the local one; beyond that, one of them
# is wrong (a misconfigured host or proxy) and the local clock is used.
MAX_CLOCK_SKEW = timedelta(minutes=5)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def busy_retry_after(
    updated_at: datetime, now: datetime | None = None, window: timedelta = BUSY_WINDOW
) -> int | None:
    """Seconds to wait before a whole-page rewrite, or None when the page is quiet.

    ``now`` should be Docmost's clock (``updated_at`` is stamped by it). Within
    MAX_CLOCK_SKEW of the local clock the earlier of the two is used, so a small skew on
    either side only lengthens the window; beyond it the local clock is used.
    """
    local = _utcnow()
    skewed = now is None or abs(now - local) > MAX_CLOCK_SKEW
    current = local if skewed or now is None else min(now, local)
    age = current - updated_at
    if age >= window:
        return None
    return int((window - age).total_seconds()) + 1


def edit_section(
    settings: DocmostSettings,
    allowlist: SpaceAllowlist,
    page_id: str,
    *,
    heading_id: str,
    operation: SectionOperation,
    content: str,
    expected_updated_at: datetime,
    clock: Callable[[], datetime | None] = lambda: None,
) -> Op[Page]:
    _require_writable(settings)
    if operation not in SECTION_OPERATIONS:
        raise InvalidRequestError(f"operation must be one of: {', '.join(SECTION_OPERATIONS)}.")
    if expected_updated_at.utcoffset() is None:
        raise InvalidRequestError(
            "expected_updated_at must include a timezone (use the updated_at returned by "
            "get_page_outline or get_page)."
        )
    # Guards apply to the new fragment; it may keep mentions already on the page.
    check_content(content, "html", settings.max_content_bytes, mentions="defer")

    current = yield from get_page(allowlist, page_id, "html")
    if current.is_locked:
        raise PermissionDeniedError("The page is locked; unlock it in Docmost before editing.")
    if current.can_edit is False:
        raise PermissionDeniedError("The account cannot edit this page.")
    if current.updated_at != expected_updated_at:
        raise StalePageError(
            "The page changed since it was read: it was updated at "
            f"{current.updated_at.isoformat()}, not {expected_updated_at.isoformat()}. "
            "Read the outline again and reapply the change.",
            current_updated_at=current.updated_at,
        )
    # Read the clock after the page read, so it reflects that response's Date header.
    window = timedelta(seconds=settings.busy_window_seconds)
    wait = busy_retry_after(current.updated_at, clock(), window)
    if wait is not None:
        raise page_busy(wait)

    html = current.content if isinstance(current.content, str) else ""
    check_mentions(content, "html", page_mentions(html, "html"))
    new_html = splice_section(html, heading_id, operation, content)
    check_size(new_html, settings.max_content_bytes)
    data = yield (
        "/pages/update",
        {"pageId": current.id, "content": new_html, "operation": "replace", "format": "html"},
    )
    return _parse(Page, {**_object(data), "format": "html"})


def page_busy(wait: int) -> PageBusyError:
    return PageBusyError(
        "The page was saved too recently and may be open in someone's editor with unsaved "
        f"changes. Try again in about {wait} seconds.",
        retry_after_seconds=wait,
    )


def _require_writable(settings: DocmostSettings) -> None:
    if settings.read_only:
        raise ReadOnlyError("Writes are disabled; set DOCMOST_READ_ONLY=0 to enable them.")


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
