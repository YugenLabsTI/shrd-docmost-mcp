"""MCP server wiring: tool registration, error mapping, and the compatibility gate."""

import functools
import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal, ParamSpec, TypeVar, cast

import anyio
from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from pydantic import AwareDatetime, Field

from docmost_client import DocmostError, InvalidRequestError, UnsupportedVersionError
from yugen_docmost_mcp._version import __version__
from yugen_docmost_mcp.ports import WikiReader, WikiWriter
from yugen_docmost_mcp.results import (
    ChildItem,
    ChildrenResult,
    PageContent,
    PageInfo,
    SearchHitItem,
    SearchResult,
    SpaceItem,
    SpacesResult,
    error_result,
)

logger = logging.getLogger("yugen_docmost_mcp")

P = ParamSpec("P")
R = TypeVar("R")

Format = Literal["markdown", "html", "json"]
Operation = Literal["append", "prepend", "replace"]

_READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_CREATE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)
_UPDATE = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False
)

_ERRORS = (
    "On failure the result has is_error=true and "
    '{"error": {"code", "message", "retryable"}} (arguments that break the input schema '
    "get a plain error message instead). Codes: "
)

INSTRUCTIONS = """\
Unofficial MCP server for a self-hosted Docmost wiki (Community Edition).

Workflow:
1. Find pages with `search` (full text) or browse with `list_spaces` then `list_children`.
2. Read a page with `get_page` before quoting or changing it; its `updated_at` identifies
   the version you read. Use the `id` values returned by these tools; slugs also work
   where noted.
3. {write_hint}

Formats: read as markdown to understand a page. Write markdown for new prose. To rewrite a
rich page (tables, comments, mentions, diagrams, colors), read it as html and replace it
with edited html: markdown would drop those elements.

Results only cover the spaces this server is allowed to access. Errors carry a stable
`code`; when `retryable` is true, wait or re-read and try again."""

_WRITE_HINT = (
    "Writes: `create_page` adds a page; `update_page` changes one and requires the "
    "`updated_at` you read, so concurrent edits are not overwritten. Prefer append or "
    "prepend; use replace only when asked to rewrite the page."
)
_READ_ONLY_HINT = (
    "This server is read-only: it cannot create or change pages. Tell the user if a change "
    "is needed."
)


class CompatibilityGate:
    """Checks the Docmost version once, before the first tool runs."""

    def __init__(self, reader: WikiReader) -> None:
        self._reader = reader
        self._lock = anyio.Lock()
        self._done = False
        self._failure: UnsupportedVersionError | None = None

    async def ensure(self) -> None:
        """Raise UnsupportedVersionError (cached) or a transient error (retried next call)."""
        async with self._lock:
            if self._failure is not None:
                raise self._failure
            if self._done:
                return
            try:
                report = await self._reader.check_compatibility()
            except UnsupportedVersionError as exc:
                self._failure = exc
                raise
            if report.status != "supported":
                logger.warning(
                    "Docmost version %s is %s; tested versions: %s",
                    report.docmost_version or "unknown",
                    report.status,
                    ", ".join(report.supported_versions),
                )
            self._done = True


def build_server(
    reader: WikiReader,
    writer: WikiWriter | None,
    *,
    on_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> MCPServer:
    """Build the MCP server. Write tools are registered only when ``writer`` is given."""
    instructions = INSTRUCTIONS.format(
        write_hint=_READ_ONLY_HINT if writer is None else _WRITE_HINT
    )

    @asynccontextmanager
    async def lifespan(_: MCPServer[Any]) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            if on_shutdown is not None:
                await on_shutdown()

    server: MCPServer[Any] = MCPServer(
        name="yugen-docmost-mcp",
        title="Docmost (unofficial)",
        version=__version__,
        instructions=instructions,
        lifespan=lifespan,
    )
    gate = CompatibilityGate(reader)
    _register_read_tools(server, reader, gate)
    if writer is not None:
        _register_write_tools(server, writer, gate)
    return server


def _guarded(gate: CompatibilityGate, fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Run the compatibility gate first and turn client errors into typed error results."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            await gate.ensure()
            return await fn(*args, **kwargs)
        except DocmostError as exc:
            # The SDK passes a returned CallToolResult through unchanged.
            return cast(R, error_result(exc))

    return wrapper


def _register_read_tools(
    server: MCPServer[Any], reader: WikiReader, gate: CompatibilityGate
) -> None:
    async def search(
        query: Annotated[str, Field(description="Words to find in page titles and text.")],
        space: Annotated[str, Field(description="Limit to one space (slug or id).")] = "",
        limit: Annotated[int, Field(ge=1, le=50, description="Maximum hits (1-50).")] = 10,
        offset: Annotated[int, Field(ge=0, description="Hits to skip, for paging.")] = 0,
        title_only: Annotated[bool, Field(description="Match titles only.")] = False,
    ) -> SearchResult:
        results = await reader.search(
            query, space=space or None, limit=limit, offset=offset, title_only=title_only
        )
        return SearchResult(
            hits=[SearchHitItem.of(hit) for hit in results.hits],
            next_offset=results.next_offset,
        )

    async def list_spaces(
        query: Annotated[str, Field(description="Filter by space name or description.")] = "",
        limit: Annotated[int, Field(ge=1, le=100, description="Page size (1-100).")] = 20,
        cursor: Annotated[str, Field(description="next_cursor from a previous call.")] = "",
    ) -> SpacesResult:
        page = await reader.list_spaces(limit=limit, cursor=cursor or None, query=query or None)
        return SpacesResult(
            spaces=[SpaceItem.of(space) for space in page.items], next_cursor=page.next_cursor
        )

    async def get_page(
        page_id: Annotated[str, Field(description="Page id or slug id (from search or URLs).")],
        format: Annotated[
            Format, Field(description="markdown (default), html, or json (ProseMirror).")
        ] = "markdown",
    ) -> PageContent:
        return PageContent.of(await reader.get_page(page_id, format=format))

    async def list_children(
        space: Annotated[
            str, Field(description="Space slug or id: list its top-level pages.")
        ] = "",
        parent_page_id: Annotated[
            str, Field(description="Page id or slug id: list its child pages.")
        ] = "",
        limit: Annotated[int, Field(ge=1, le=100, description="Page size (1-100).")] = 20,
        cursor: Annotated[str, Field(description="next_cursor from a previous call.")] = "",
    ) -> ChildrenResult:
        page = await reader.list_children(
            space=space or None,
            parent_page_id=parent_page_id or None,
            limit=limit,
            cursor=cursor or None,
        )
        return ChildrenResult(
            pages=[ChildItem.of(child) for child in page.items], next_cursor=page.next_cursor
        )

    server.add_tool(
        _guarded(gate, search),
        name="search",
        title="Search pages",
        description=(
            "Full-text search over wiki pages. Use it first to find pages about a topic. "
            "Returns hits with page_id, title, space, updated_at and a snippet where "
            "**bold** marks the matched words; the snippet is raw page text. Results are "
            "ranked by relevance; when next_offset is not null, call again with that "
            "offset for more. Then call get_page to read a hit. "
            + _ERRORS
            + "SPACE_NOT_ALLOWED, NOT_FOUND, INVALID_INPUT, AUTH_FAILED, RATE_LIMITED, "
            "UPSTREAM_ERROR, UNSUPPORTED_VERSION."
        ),
        annotations=_READ,
        structured_output=True,
    )
    server.add_tool(
        _guarded(gate, list_spaces),
        name="list_spaces",
        title="List spaces",
        description=(
            "List the wiki spaces this server can access, with id, slug, name, "
            "description and the account's role (admin, writer or reader; only admin and "
            "writer can edit). Use it to discover where content lives before browsing "
            "with list_children. Page with next_cursor. "
            + _ERRORS
            + "INVALID_INPUT, AUTH_FAILED, RATE_LIMITED, UPSTREAM_ERROR, UNSUPPORTED_VERSION."
        ),
        annotations=_READ,
        structured_output=True,
    )
    server.add_tool(
        _guarded(gate, get_page),
        name="get_page",
        title="Read a page",
        description=(
            "Read one page with its content. Returns id, title, space, parent_page_id, "
            "updated_at, is_locked, can_edit, format and content. Keep updated_at: "
            "update_page requires it. Formats: markdown is compact and best for reading "
            "but drops comments, mentions, colors, diagrams and embeds; html keeps nearly "
            "everything (read html before replacing a rich page); json is the exact "
            "editor document and is large. content is null for an empty page. "
            + _ERRORS
            + "NOT_FOUND (missing or in trash), FORBIDDEN, SPACE_NOT_ALLOWED, "
            "INVALID_INPUT, AUTH_FAILED, RATE_LIMITED, UPSTREAM_ERROR, UNSUPPORTED_VERSION."
        ),
        annotations=_READ,
        structured_output=True,
    )
    server.add_tool(
        _guarded(gate, list_children),
        name="list_children",
        title="List child pages",
        description=(
            "Browse the page tree. Give space to list its top-level pages, or "
            "parent_page_id to list a page's children (exactly one is needed). Returns id, "
            "slug_id, title and has_children for each page, in tree order; recurse on pages "
            "with has_children. Page with next_cursor. "
            + _ERRORS
            + "INVALID_INPUT, FORBIDDEN, NOT_FOUND, SPACE_NOT_ALLOWED, AUTH_FAILED, "
            "RATE_LIMITED, UPSTREAM_ERROR, UNSUPPORTED_VERSION."
        ),
        annotations=_READ,
        structured_output=True,
    )


def _register_write_tools(
    server: MCPServer[Any], writer: WikiWriter, gate: CompatibilityGate
) -> None:
    async def create_page(
        space: Annotated[str, Field(description="Space slug or id to create the page in.")],
        title: Annotated[str, Field(min_length=1, description="Page title.")],
        content: Annotated[
            str,
            Field(description="Initial content in `format`; for json, a JSON-encoded document."),
        ] = "",
        format: Annotated[Format, Field(description="Format of content.")] = "markdown",
        parent_page_id: Annotated[
            str, Field(description="Create under this page (id or slug id).")
        ] = "",
    ) -> PageInfo:
        page = await writer.create_page(
            space=space,
            title=title,
            content=_decode(content, format),
            format=format,
            parent_page_id=parent_page_id or None,
            icon=None,
        )
        return PageInfo.of(page)

    async def update_page(
        page_id: Annotated[str, Field(description="Page id or slug id.")],
        expected_updated_at: Annotated[
            AwareDatetime,
            Field(
                description="updated_at from your last get_page; the update fails if it changed."
            ),
        ],
        content: Annotated[
            str,
            Field(description="Content in `format`; for json, a JSON-encoded document."),
        ] = "",
        operation: Annotated[
            Operation | None,
            Field(description="Required with content: append, prepend, or replace."),
        ] = None,
        format: Annotated[Format, Field(description="Format of content.")] = "markdown",
        title: Annotated[str, Field(description="New title; empty keeps the current one.")] = "",
    ) -> PageContent:
        page = await writer.update_page(
            page_id,
            content=_decode(content, format),
            operation=operation,
            format=format,
            title=title or None,
            icon=None,
            expected_updated_at=expected_updated_at,
        )
        return PageContent.of(page)

    server.add_tool(
        _guarded(gate, create_page),
        name="create_page",
        title="Create a page",
        description=(
            "Create a new page in a space, optionally under a parent page, with optional "
            "initial content. Write markdown for prose (each single newline becomes a line "
            "break, so do not hard-wrap paragraphs), html for tables or rich layout, or json "
            "for an exact editor document. Mentions are rejected. Returns the new page's "
            "id, title, space and updated_at (not its content). "
            + _ERRORS
            + "READ_ONLY, SPACE_NOT_ALLOWED, FORBIDDEN, NOT_FOUND (parent), INVALID_INPUT, "
            "AUTH_FAILED, RATE_LIMITED, UPSTREAM_ERROR, UNSUPPORTED_VERSION."
        ),
        annotations=_CREATE,
        structured_output=True,
    )
    server.add_tool(
        _guarded(gate, update_page),
        name="update_page",
        title="Update a page",
        description=(
            "Change a page's content and/or title. Call get_page first and pass its "
            "updated_at as expected_updated_at; if someone changed the page since, the call "
            "fails with STALE_PAGE and nothing is written: read it again and redo the "
            "change. operation: append or prepend add content at the end or start and are "
            "safe with people editing; replace deletes the whole body first, including "
            "recent edits, so use it only when asked to rewrite. To replace a page with "
            "rich content, read it as html and send edited html; markdown would drop "
            "comments, mentions, colors and diagrams. Returns the page as stored. "
            + _ERRORS
            + "STALE_PAGE (retryable after re-reading), READ_ONLY, FORBIDDEN (locked or not "
            "editable), NOT_FOUND, SPACE_NOT_ALLOWED, INVALID_INPUT, AUTH_FAILED, "
            "RATE_LIMITED, UPSTREAM_ERROR, UNSUPPORTED_VERSION."
        ),
        annotations=_UPDATE,
        structured_output=True,
    )


# Every optional string parameter in this module is typed plain `str`, with "" meaning
# "not given": the SDK JSON-decodes string arguments of any other annotation, which would
# turn Markdown such as "[1, 2]" into a list or a space slug such as "null" into None.
def _decode(content: str, format: Format) -> str | dict[str, Any] | None:
    if not content:
        return None
    if format != "json":
        return content
    try:
        document = json.loads(content)
    except ValueError:
        raise InvalidRequestError("content is not valid JSON.") from None
    if not isinstance(document, dict):
        raise InvalidRequestError("content must be a JSON object when format is json.")
    return cast(dict[str, Any], document)
