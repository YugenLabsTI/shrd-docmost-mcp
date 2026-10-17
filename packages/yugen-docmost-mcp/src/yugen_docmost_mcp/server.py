"""MCP server wiring: tool registration, error mapping, and the compatibility gate."""

import functools
import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal, ParamSpec, TypeVar, cast

import anyio
from mcp.server.elicitation import AcceptedElicitation, ElicitationResult
from mcp.server.mcpserver import Context, Elicit, MCPServer, Resolve
from mcp_types import ClientCapabilities, ElicitationCapability, ToolAnnotations
from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field

from docmost_client import (
    DocmostError,
    InvalidRequestError,
    PageBusyError,
    UnsupportedVersionError,
)
from yugen_docmost_mcp._version import __version__
from yugen_docmost_mcp.errors import ConfirmationDeclinedError, ConfirmationUnavailableError
from yugen_docmost_mcp.ports import WikiCommenter, WikiReader, WikiWriter
from yugen_docmost_mcp.prompts import BUILTIN_PROMPTS, PromptSpec, register_prompts
from yugen_docmost_mcp.resources import register_resources
from yugen_docmost_mcp.results import (
    ChildItem,
    ChildrenResult,
    CommentItem,
    CommentsResult,
    OutlineResult,
    PageContent,
    PageInfo,
    RecentPageItem,
    RecentPagesResult,
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


def _null_to_empty(value: object) -> object:
    return "" if value is None else value


# Optional text argument: "" means "not given", and an explicit JSON null is accepted as
# "". The annotation must stay plain `str` for the SDK not to JSON-decode the value
# (see _decode), so null handling lives in a validator instead of `str | None`.
OptionalText = Annotated[str, BeforeValidator(_null_to_empty)]
Operation = Literal["append", "prepend", "replace"]

_READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_CREATE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)
# Same values as _CREATE today; kept separate because comments are a distinct permission
# (DOCMOST_ALLOW_COMMENTS) whose hints may diverge from page creation.
_COMMENT = ToolAnnotations(
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
1. Find pages with `search` (full text), browse with `list_spaces` then `list_children`, or
   see what changed lately with `list_recent_pages`.
2. Read a page with `get_page` before quoting or changing it; its `updated_at` identifies
   the version you read. Use the `id` values returned by these tools; slugs also work
   where noted.
3. {write_hint}
4. {comment_hint}

Formats: read as markdown to understand a page. Write markdown for new prose. To rewrite a
rich page (tables, comments, mentions, diagrams, colors), read it as html and replace it
with edited html: markdown would drop those elements.

Results only cover the spaces this server is allowed to access. Errors carry a stable
`code`; when `retryable` is true, wait or re-read and try again."""

_WRITE_HINT = (
    "Writes: `create_page` adds a page; to change one section, use `get_page_outline` then "
    "`edit_section`; `update_page` changes a whole page and requires the "
    "`updated_at` you read, so concurrent edits are not overwritten. Prefer append or "
    "prepend; use replace only when asked to rewrite the page."
)
_COMMENT_HINT = (
    "Comments: `list_comments` reads a page's discussion; `add_comment` adds a comment or a "
    "reply. Prefer a comment over editing when proposing a change someone should review."
)
_NO_COMMENT_HINT = (
    "Comments: `list_comments` reads a page's discussion; this server cannot add comments."
)
_CONFIRM_HINT = " A `replace` asks the user to confirm first; if they decline, nothing is written."
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
    commenter: WikiCommenter | None = None,
    confirm_replace: bool = True,
    prompts: Sequence[PromptSpec] = BUILTIN_PROMPTS,
    on_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> MCPServer:
    """Build the MCP server.

    Page write tools are registered only with ``writer``, and ``add_comment`` only with
    ``commenter``. With ``confirm_replace``, a replace asks the user to confirm first.
    """
    write_hint = _READ_ONLY_HINT
    if writer is not None:
        write_hint = _WRITE_HINT + (_CONFIRM_HINT if confirm_replace else "")
    instructions = INSTRUCTIONS.format(
        write_hint=write_hint,
        comment_hint=_NO_COMMENT_HINT if commenter is None else _COMMENT_HINT,
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
    register_resources(server, reader, gate.ensure)
    register_prompts(server, prompts)
    if commenter is not None:
        _register_comment_tool(server, commenter, gate)
    if writer is not None:
        _register_write_tools(server, writer, reader, gate, confirm_replace)
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
        space: Annotated[OptionalText, Field(description="Limit to one space (slug or id).")] = "",
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
        query: Annotated[
            OptionalText, Field(description="Filter by space name or description.")
        ] = "",
        limit: Annotated[int, Field(ge=1, le=100, description="Page size (1-100).")] = 20,
        cursor: Annotated[
            OptionalText, Field(description="next_cursor from a previous call.")
        ] = "",
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
            OptionalText, Field(description="Space slug or id: list its top-level pages.")
        ] = "",
        parent_page_id: Annotated[
            OptionalText, Field(description="Page id or slug id: list its child pages.")
        ] = "",
        limit: Annotated[int, Field(ge=1, le=100, description="Page size (1-100).")] = 20,
        cursor: Annotated[
            OptionalText, Field(description="next_cursor from a previous call.")
        ] = "",
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

    async def get_page_outline(
        page_id: Annotated[str, Field(description="Page id or slug id.")],
    ) -> OutlineResult:
        return OutlineResult.of(await reader.get_page_outline(page_id))

    async def list_recent_pages(
        space: Annotated[
            OptionalText, Field(description="Limit to one space (slug or id); empty for all.")
        ] = "",
        limit: Annotated[int, Field(ge=1, le=100, description="Page size (1-100).")] = 20,
        cursor: Annotated[
            OptionalText, Field(description="next_cursor from a previous call.")
        ] = "",
    ) -> RecentPagesResult:
        page = await reader.list_recent_pages(
            space=space or None, limit=limit, cursor=cursor or None
        )
        return RecentPagesResult(
            pages=[RecentPageItem.of(item) for item in page.items], next_cursor=page.next_cursor
        )

    async def list_comments(
        page_id: Annotated[str, Field(description="Page id or slug id.")],
        limit: Annotated[int, Field(ge=1, le=100, description="Page size (1-100).")] = 20,
        cursor: Annotated[
            OptionalText, Field(description="next_cursor from a previous call.")
        ] = "",
    ) -> CommentsResult:
        page = await reader.list_comments(page_id, limit=limit, cursor=cursor or None)
        return CommentsResult(
            comments=[CommentItem.of(comment) for comment in page.items],
            next_cursor=page.next_cursor,
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

    server.add_tool(
        _guarded(gate, get_page_outline),
        name="get_page_outline",
        title="Read a page outline",
        description=(
            "List a page's top-level headings in order, with each heading's id, level and "
            "text, plus the page's updated_at. Use it before edit_section to find the "
            "section to change (headings nested inside other blocks are not listed). "
            + _ERRORS
            + "NOT_FOUND (missing or in trash), FORBIDDEN, SPACE_NOT_ALLOWED, INVALID_INPUT, "
            "AUTH_FAILED, RATE_LIMITED, UPSTREAM_ERROR, UNSUPPORTED_VERSION."
        ),
        annotations=_READ,
        structured_output=True,
    )
    server.add_tool(
        _guarded(gate, list_recent_pages),
        name="list_recent_pages",
        title="List recently updated pages",
        description=(
            "List pages by most recent update, across the accessible spaces or in one space. "
            "Use it to answer 'what changed lately?' or to find a page someone just edited. "
            "Returns id, title, space, parent_page_id and updated_at (no content). Page "
            "with next_cursor; a page can come back short or empty when recent changes are "
            "in spaces this server cannot access, so keep paging while next_cursor is set. "
            + _ERRORS
            + "SPACE_NOT_ALLOWED, FORBIDDEN, NOT_FOUND, INVALID_INPUT, AUTH_FAILED, "
            "RATE_LIMITED, UPSTREAM_ERROR, UNSUPPORTED_VERSION."
        ),
        annotations=_READ,
        structured_output=True,
    )
    server.add_tool(
        _guarded(gate, list_comments),
        name="list_comments",
        title="Read page comments",
        description=(
            "Read a page's comments, oldest first, as plain text (mentions appear as "
            "@name). Each comment has its author, created_at, whether it is resolved, its "
            "type (page or inline) and, for inline comments, the page text it refers to "
            "(selection). Replies have parent_comment_id. Use it before editing a page to see "
            "open discussions. Page with next_cursor. "
            + _ERRORS
            + "NOT_FOUND (missing or in trash), FORBIDDEN, SPACE_NOT_ALLOWED, INVALID_INPUT, "
            "AUTH_FAILED, RATE_LIMITED, UPSTREAM_ERROR, UNSUPPORTED_VERSION."
        ),
        annotations=_READ,
        structured_output=True,
    )


class ReplaceConfirmation(BaseModel):
    # Defaults to False: an accepted answer without a value counts as "not confirmed".
    confirm: bool = Field(default=False, description="Replace the whole page content")


Need = Literal["not_needed", "unavailable", "ask"]


class ConfirmationGate(BaseModel):
    status: Literal["not_needed", "unavailable", "accepted", "declined"]


_ELICITATION = ClientCapabilities(elicitation=ElicitationCapability())
_NOT_NEEDED = ConfirmationGate(status="not_needed")


def _confirmation_resolvers(
    confirm_replace: bool,
) -> Callable[..., ConfirmationGate]:
    """Resolver chain asking the user before a replace (elicitation).

    ``ask`` only produces a question when one is needed and the host can show it;
    ``decide`` turns every outcome (accept, decline, cancel, not asked) into a gate status,
    so the tool always reports a typed result instead of an aborted call.
    """

    def need(operation: str | None, content: str, ctx: Context) -> Need:
        # Without content there is nothing to replace: the client rejects the call anyway.
        if not confirm_replace or operation != "replace" or not content:
            return "not_needed"
        return "ask" if ctx.session.check_client_capability(_ELICITATION) else "unavailable"

    def ask(
        page_id: str, operation: str | None, content: str, ctx: Context
    ) -> Elicit[ReplaceConfirmation] | AcceptedElicitation[ReplaceConfirmation]:
        if need(operation, content, ctx) != "ask":
            # Placeholder only: no question was asked. `decide` recomputes `need` and
            # ignores this value unless the status is "ask", so it never counts as a
            # user confirmation.
            return AcceptedElicitation(data=ReplaceConfirmation(confirm=True))
        return Elicit(
            f"Replace the entire content of Docmost page {_quoted(page_id)}? Everything "
            "currently on "
            "the page is deleted, including recent edits by other people.",
            ReplaceConfirmation,
        )

    def decide(
        operation: str | None,
        content: str,
        ctx: Context,
        answer: Annotated[ElicitationResult[ReplaceConfirmation], Resolve(ask)],
    ) -> ConfirmationGate:
        status = need(operation, content, ctx)
        if status != "ask":
            return ConfirmationGate(status=status)
        confirmed = isinstance(answer, AcceptedElicitation) and answer.data.confirm
        return ConfirmationGate(status="accepted" if confirmed else "declined")

    return decide


def _quoted(value: str, limit: int = 60) -> str:
    """Show agent-supplied text safely inside a question to the user: one line, bounded."""
    flat = " ".join("".join(ch if ch.isprintable() else " " for ch in value).split())
    return f'"{flat if len(flat) <= limit else flat[: limit - 1] + "…"}"'


def _register_comment_tool(
    server: MCPServer[Any], commenter: WikiCommenter, gate: CompatibilityGate
) -> None:
    async def add_comment(
        page_id: Annotated[str, Field(description="Page id or slug id.")],
        text: Annotated[str, Field(min_length=1, description="Comment text (plain text).")],
        parent_comment_id: Annotated[
            OptionalText, Field(description="Reply to this top-level comment id.")
        ] = "",
    ) -> CommentItem:
        comment = await commenter.create_comment(
            page_id, text, parent_comment_id=parent_comment_id or None
        )
        return CommentItem.of(comment)

    server.add_tool(
        _guarded(gate, add_comment),
        name="add_comment",
        title="Comment on a page",
        description=(
            "Add a page comment, or a reply to an existing top-level comment, in plain text "
            "(new lines become paragraphs; formatting and mentions are not supported). Use "
            "it to propose a change or ask a question instead of editing the page. The page "
            "watchers are notified. Returns the stored comment. "
            + _ERRORS
            + "COMMENTS_DISABLED, FORBIDDEN (the account needs edit access to the page), "
            "NOT_FOUND, SPACE_NOT_ALLOWED, INVALID_INPUT, "
            "AUTH_FAILED, RATE_LIMITED, UPSTREAM_ERROR, UNSUPPORTED_VERSION."
        ),
        annotations=_COMMENT,
        structured_output=True,
    )


class SectionCheck(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: Literal["ask", "not_needed", "unavailable", "busy", "precheck_failed"]
    retry_after: int | None = None
    error: DocmostError | None = None


class SectionGate(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: Literal["not_needed", "unavailable", "busy", "precheck_failed", "accepted", "declined"]
    retry_after: int | None = None
    error: DocmostError | None = None


_SECTION_NOT_NEEDED = SectionGate(status="not_needed")


def _section_resolvers(reader: WikiReader, confirm_replace: bool) -> Callable[..., SectionGate]:
    """Resolver chain for edit_section: refuse busy pages first, then ask the user.

    ``check`` reads the outline (cheap) so a page saved too recently is refused
    before any question. If that read fails, the edit reports its typed error and writes
    nothing: a transient failure must not skip the question.
    """

    async def check(page_id: str, ctx: Context) -> SectionCheck:
        try:
            outline = await reader.get_page_outline(page_id)
            wait = reader.busy_retry_after(outline.updated_at)
        except DocmostError as exc:
            return SectionCheck(status="precheck_failed", error=exc)
        if wait is not None:
            return SectionCheck(status="busy", retry_after=wait)
        if not confirm_replace:
            return SectionCheck(status="not_needed")
        if not ctx.session.check_client_capability(_ELICITATION):
            return SectionCheck(status="unavailable")
        return SectionCheck(status="ask")

    def ask(
        page_id: str, heading_id: str, state: Annotated[SectionCheck, Resolve(check)]
    ) -> Elicit[ReplaceConfirmation] | AcceptedElicitation[ReplaceConfirmation]:
        if state.status != "ask":
            # Placeholder only: no question was asked; `decide` ignores it.
            return AcceptedElicitation(data=ReplaceConfirmation(confirm=True))
        return Elicit(
            f"Rewrite the section {_quoted(heading_id)} of Docmost page {_quoted(page_id)}? "
            "Docmost rewrites the whole page to do it, so unsaved edits someone is making "
            "elsewhere on the page could be lost.",
            ReplaceConfirmation,
        )

    def decide(
        state: Annotated[SectionCheck, Resolve(check)],
        answer: Annotated[ElicitationResult[ReplaceConfirmation], Resolve(ask)],
    ) -> SectionGate:
        if state.status != "ask":
            return SectionGate(
                status=state.status, retry_after=state.retry_after, error=state.error
            )
        confirmed = isinstance(answer, AcceptedElicitation) and answer.data.confirm
        return SectionGate(status="accepted" if confirmed else "declined")

    return decide


def _register_write_tools(
    server: MCPServer[Any],
    writer: WikiWriter,
    reader: WikiReader,
    gate: CompatibilityGate,
    confirm_replace: bool,
) -> None:
    decide = _confirmation_resolvers(confirm_replace)
    decide_section = _section_resolvers(reader, confirm_replace)

    async def edit_section(
        page_id: Annotated[str, Field(description="Page id or slug id.")],
        heading_id: Annotated[
            str, Field(description="Heading id from get_page_outline that starts the section.")
        ],
        operation: Annotated[
            Literal["replace", "prepend", "append"],
            Field(description="replace the section body, prepend after the heading, or append."),
        ],
        content: Annotated[str, Field(min_length=1, description="New content as HTML.")],
        expected_updated_at: Annotated[
            AwareDatetime,
            Field(description="updated_at from your last get_page_outline or get_page."),
        ],
        # Filled by the resolver chain, never by the caller.
        section_gate: Annotated[SectionGate, Resolve(decide_section)] = _SECTION_NOT_NEEDED,
    ) -> PageContent:
        if section_gate.error is not None:
            raise section_gate.error
        if section_gate.status == "busy":
            wait = section_gate.retry_after or 60
            raise PageBusyError(
                "The page was saved too recently and may be open in someone's "
                f"editor with unsaved changes. Try again in about {wait} seconds.",
                retry_after_seconds=wait,
            )
        if section_gate.status == "unavailable":
            raise ConfirmationUnavailableError(
                "A section edit needs the user's confirmation, but this MCP host cannot ask "
                "for it. Have the operator set DOCMOST_CONFIRM_REPLACE=0 to allow it."
            )
        if section_gate.status == "declined":
            raise ConfirmationDeclinedError(
                "The user did not confirm the section edit; nothing was changed."
            )
        page = await writer.edit_section(
            page_id,
            heading_id=heading_id,
            operation=operation,
            content=content,
            expected_updated_at=expected_updated_at,
        )
        return PageContent.of(page)

    async def create_page(
        space: Annotated[str, Field(description="Space slug or id to create the page in.")],
        title: Annotated[str, Field(min_length=1, description="Page title.")],
        content: Annotated[
            OptionalText,
            Field(description="Initial content in `format`; for json, a JSON-encoded document."),
        ] = "",
        format: Annotated[Format, Field(description="Format of content.")] = "markdown",
        parent_page_id: Annotated[
            OptionalText, Field(description="Create under this page (id or slug id).")
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
            OptionalText,
            Field(description="Content in `format`; for json, a JSON-encoded document."),
        ] = "",
        operation: Annotated[
            Operation | None,
            Field(description="Required with content: append, prepend, or replace."),
        ] = None,
        format: Annotated[Format, Field(description="Format of content.")] = "markdown",
        title: Annotated[
            OptionalText, Field(description="New title; empty keeps the current one.")
        ] = "",
        # Filled by the resolver chain, never by the caller; the default only satisfies
        # Python's ordering of parameters with defaults.
        confirmation: Annotated[ConfirmationGate, Resolve(decide)] = _NOT_NEEDED,
    ) -> PageContent:
        if confirmation.status == "unavailable":
            raise ConfirmationUnavailableError(
                "A replace needs the user's confirmation, but this MCP host cannot ask for "
                "it. Use append or prepend, or have the operator set "
                "DOCMOST_CONFIRM_REPLACE=0."
            )
        if confirmation.status == "declined":
            raise ConfirmationDeclinedError(
                "The user did not confirm the replace; nothing was changed."
            )
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
        _guarded(gate, edit_section),
        name="edit_section",
        title="Edit one section of a page",
        description=(
            "Change one section of a page instead of rewriting it: call get_page_outline, "
            "pick the heading whose section you want to change, and pass its id with the "
            "outline's updated_at. operation: replace swaps the section body (subsections "
            "included, the heading stays), prepend inserts right after the heading, append "
            "inserts at the end of the section. content is HTML (e.g. <p>, <ul>, <table>); "
            "it must be well-formed and may keep mentions already on the page but not add "
            "new ones (they notify people). Docmost can only save whole "
            "pages, so if the page was saved very recently (DOCMOST_BUSY_WINDOW_SECONDS, 60 "
            "by default) the call fails with "
            "PAGE_BUSY (wait retry_after_seconds and retry), and otherwise the user may be "
            "asked to confirm. Returns the page as stored (html). "
            + _ERRORS
            + "PAGE_BUSY (retryable), STALE_PAGE (retryable after re-reading), CLOCK_SKEW "
            "(Docmost's and the local clock disagree; an operator must fix them), "
            "CONFIRMATION_DECLINED, CONFIRMATION_UNAVAILABLE, NOT_FOUND (page or heading), "
            "READ_ONLY, FORBIDDEN, SPACE_NOT_ALLOWED, INVALID_INPUT, AUTH_FAILED, "
            "RATE_LIMITED, UPSTREAM_ERROR, UNSUPPORTED_VERSION."
        ),
        annotations=_UPDATE,
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
            "comments, mentions, colors and diagrams. Content may keep mentions already on "
            "the page but not add new ones (they notify people). A replace may ask the user "
            "to confirm first. Returns the page as stored. "
            + _ERRORS
            + "STALE_PAGE (retryable after re-reading), CONFIRMATION_DECLINED, "
            "CONFIRMATION_UNAVAILABLE, READ_ONLY, FORBIDDEN (locked or not "
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
