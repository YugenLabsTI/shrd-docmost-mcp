"""MCP surface: tool registration, structured results, and typed errors (fake ports)."""

import json
from datetime import UTC, datetime
from typing import Any

import mcp_types
import pytest
from mcp import Client

from docmost_client import (
    Comment,
    CompatibilityReport,
    ContentFormat,
    ContentOperation,
    Page,
    PageSummary,
    Paginated,
    RecentPage,
    SearchHit,
    SearchResults,
    Space,
    SpaceNotAllowedError,
    SpaceRef,
    StalePageError,
    UnsupportedVersionError,
)
from yugen_docmost_mcp.server import build_server

pytestmark = pytest.mark.anyio

ENG = SpaceRef(id="s1", name="Engineering", slug="engineering")
UPDATED_AT = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
READ_TOOLS = {
    "search",
    "list_spaces",
    "get_page",
    "list_children",
    "list_recent_pages",
    "list_comments",
}
WRITE_TOOLS = {"create_page", "update_page"}


def make_page(fmt: ContentFormat = "markdown", content: Any = "# Runbook\n") -> Page:
    return Page(
        id="p1",
        slug_id="abc123xyz0",
        title="Runbook",
        parent_page_id=None,
        space_id="s1",
        space=ENG,
        created_at=UPDATED_AT,
        updated_at=UPDATED_AT,
        format=fmt,
        content=content,
        can_edit=True,
    )


class FakeWiki:
    """In-memory implementation of the reader and writer ports."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_with: Exception | None = None
        self.compatibility: CompatibilityReport | Exception = CompatibilityReport(
            status="supported", docmost_version="0.96.0", supported_versions=("0.96.0",)
        )

    def _record(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))
        if self.fail_with is not None:
            raise self.fail_with

    async def check_compatibility(self) -> CompatibilityReport:
        self.calls.append(("check_compatibility", {}))
        if isinstance(self.compatibility, Exception):
            raise self.compatibility
        return self.compatibility

    async def list_spaces(
        self, *, limit: int, cursor: str | None, query: str | None
    ) -> Paginated[Space]:
        self._record("list_spaces", limit=limit, cursor=cursor, query=query)
        space = Space(id="s1", name="Engineering", slug="engineering", role="writer")
        return Paginated[Space](items=[space], has_next_page=True, next_cursor="c2")

    async def search(
        self, query: str, *, space: str | None, limit: int, offset: int, title_only: bool
    ) -> SearchResults:
        self._record(
            "search", query=query, space=space, limit=limit, offset=offset, title_only=title_only
        )
        hit = SearchHit(
            id="p1",
            slug_id="abc123xyz0",
            title="Runbook",
            space=ENG,
            updated_at=UPDATED_AT,
            rank=0.5,
            highlight="restart the <b>worker</b> pool",
        )
        # One visible hit even for a full upstream page, as when the allowlist filters.
        return SearchResults(hits=[hit], next_offset=offset + limit)

    async def get_page(self, page_id: str, *, format: ContentFormat) -> Page:
        self._record("get_page", page_id=page_id, format=format)
        content: Any = {"type": "doc", "content": []} if format == "json" else "# Runbook\n"
        return make_page(format, content)

    async def list_children(
        self, *, space: str | None, parent_page_id: str | None, limit: int, cursor: str | None
    ) -> Paginated[PageSummary]:
        self._record(
            "list_children", space=space, parent_page_id=parent_page_id, limit=limit, cursor=cursor
        )
        child = PageSummary(
            id="p2", slug_id="def456uvw1", title="Child", space_id="s1", has_children=False
        )
        return Paginated[PageSummary](items=[child], has_next_page=False, next_cursor=None)

    async def create_page(
        self,
        *,
        space: str,
        title: str | None,
        content: str | dict[str, Any] | None,
        format: ContentFormat,
        parent_page_id: str | None,
        icon: str | None,
    ) -> Page:
        self._record(
            "create_page",
            space=space,
            title=title,
            content=content,
            format=format,
            parent_page_id=parent_page_id,
            icon=icon,
        )
        return make_page(format, None)

    async def list_recent_pages(
        self, *, space: str | None, limit: int, cursor: str | None
    ) -> Paginated[RecentPage]:
        self._record("list_recent_pages", space=space, limit=limit, cursor=cursor)
        page = RecentPage(
            id="p1", slug_id="abc123xyz0", title="Runbook", space=ENG, updated_at=UPDATED_AT
        )
        return Paginated[RecentPage](items=[page], has_next_page=True, next_cursor="r2")

    async def list_comments(
        self, page_id: str, *, limit: int, cursor: str | None
    ) -> Paginated[Comment]:
        self._record("list_comments", page_id=page_id, limit=limit, cursor=cursor)
        comment = Comment(
            id="c1",
            page_id="p1",
            space_id="s1",
            type="page",
            text="Should we drain first?",
            creator_name="Ana",
            created_at=UPDATED_AT,
        )
        return Paginated[Comment](items=[comment], has_next_page=False, next_cursor=None)

    async def create_comment(
        self, page_id: str, text: str, *, parent_comment_id: str | None
    ) -> Comment:
        self._record(
            "create_comment", page_id=page_id, text=text, parent_comment_id=parent_comment_id
        )
        return Comment(
            id="c9",
            page_id="p1",
            space_id="s1",
            parent_comment_id=parent_comment_id,
            type="page",
            text=text,
            creator_name="Wiki Bot",
            created_at=UPDATED_AT,
        )

    async def update_page(
        self,
        page_id: str,
        *,
        content: str | dict[str, Any] | None,
        operation: ContentOperation | None,
        format: ContentFormat,
        title: str | None,
        icon: str | None,
        expected_updated_at: datetime | None,
    ) -> Page:
        self._record(
            "update_page",
            page_id=page_id,
            content=content,
            operation=operation,
            format=format,
            title=title,
            icon=icon,
            expected_updated_at=expected_updated_at,
        )
        return make_page(format, "# Runbook\n\nMore\n")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def wiki() -> FakeWiki:
    return FakeWiki()


async def call(server: Any, name: str, **arguments: Any) -> Any:
    async with Client(server) as client:
        return await client.call_tool(name, arguments)


async def test_read_only_server_exposes_only_read_tools(wiki: FakeWiki) -> None:
    async with Client(build_server(wiki, writer=None)) as client:
        tools = (await client.list_tools()).tools

    assert {tool.name for tool in tools} == READ_TOOLS
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert len(tool.description or "") > 80
        assert tool.output_schema is not None


async def test_writable_server_adds_write_tools(wiki: FakeWiki) -> None:
    async with Client(build_server(wiki, writer=wiki)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    assert set(tools) == READ_TOOLS | WRITE_TOOLS
    assert tools["create_page"].annotations is not None
    assert tools["create_page"].annotations.read_only_hint is False
    assert tools["create_page"].annotations.destructive_hint is False
    assert tools["update_page"].annotations is not None
    assert tools["update_page"].annotations.destructive_hint is True


async def test_server_instructions_explain_the_workflow(wiki: FakeWiki) -> None:
    async with Client(build_server(wiki, writer=None)) as client:
        instructions = client.instructions or ""

    assert "read-only" in instructions
    assert "updated_at" in instructions


async def test_list_spaces_returns_structured_spaces(wiki: FakeWiki) -> None:
    result = await call(build_server(wiki, writer=None), "list_spaces", query="eng", limit=5)

    assert result.is_error is False
    assert result.structured_content == {
        "spaces": [
            {
                "id": "s1",
                "slug": "engineering",
                "name": "Engineering",
                "description": None,
                "role": "writer",
            }
        ],
        "next_cursor": "c2",
    }
    assert ("list_spaces", {"limit": 5, "cursor": None, "query": "eng"}) in wiki.calls


@pytest.mark.parametrize("text", ["[1, 2]", "null", "true", '{"a": 1}'])
async def test_free_text_that_looks_like_json_stays_text(wiki: FakeWiki, text: str) -> None:
    result = await call(
        build_server(wiki, writer=wiki),
        "update_page",
        page_id="p1",
        expected_updated_at="2026-10-16T10:00:00Z",
        content=text,
        operation="append",
        title=text,
    )

    assert result.is_error is False
    _, kwargs = wiki.calls[-1]
    assert kwargs["content"] == text
    assert kwargs["title"] == text
    assert json.loads(result.content[0].text) == result.structured_content


async def test_search_returns_hits_with_plain_snippets(wiki: FakeWiki) -> None:
    result = await call(build_server(wiki, writer=None), "search", query="worker", limit=2)

    hits = result.structured_content["hits"]
    assert len(hits) == 1
    assert hits[0] == {
        "page_id": "p1",
        "slug_id": "abc123xyz0",
        "title": "Runbook",
        "space": {"id": "s1", "slug": "engineering", "name": "Engineering"},
        "updated_at": "2026-10-16T10:00:00Z",
        "snippet": "restart the **worker** pool",
    }
    assert result.structured_content["next_offset"] == 2
    assert (
        "search",
        {"query": "worker", "space": None, "limit": 2, "offset": 0, "title_only": False},
    ) in wiki.calls


async def test_get_page_defaults_to_markdown(wiki: FakeWiki) -> None:
    result = await call(build_server(wiki, writer=None), "get_page", page_id="abc123xyz0")

    page = result.structured_content
    assert page["id"] == "p1"
    assert page["format"] == "markdown"
    assert page["content"] == "# Runbook\n"
    assert page["updated_at"] == "2026-10-16T10:00:00Z"
    assert page["space"] == {"id": "s1", "slug": "engineering", "name": "Engineering"}
    assert page["can_edit"] is True
    assert ("get_page", {"page_id": "abc123xyz0", "format": "markdown"}) in wiki.calls


async def test_get_page_as_json_returns_the_document_object(wiki: FakeWiki) -> None:
    result = await call(build_server(wiki, writer=None), "get_page", page_id="p1", format="json")

    assert result.structured_content["content"] == {"type": "doc", "content": []}


async def test_list_children_returns_summaries(wiki: FakeWiki) -> None:
    result = await call(build_server(wiki, writer=None), "list_children", parent_page_id="p1")

    assert result.structured_content == {
        "pages": [
            {
                "id": "p2",
                "slug_id": "def456uvw1",
                "title": "Child",
                "parent_page_id": None,
                "has_children": False,
            }
        ],
        "next_cursor": None,
    }


async def test_client_errors_become_typed_error_results(wiki: FakeWiki) -> None:
    wiki.fail_with = SpaceNotAllowedError("The space is not in DOCMOST_ALLOWED_SPACES.")

    result = await call(build_server(wiki, writer=None), "get_page", page_id="p1")

    assert result.is_error is True
    error = {
        "error": {
            "code": "SPACE_NOT_ALLOWED",
            "message": "The space is not in DOCMOST_ALLOWED_SPACES.",
            "retryable": False,
        }
    }
    assert result.structured_content == error
    assert json.loads(result.content[0].text) == error


async def test_stale_page_errors_tell_the_agent_to_reread(wiki: FakeWiki) -> None:
    wiki.fail_with = StalePageError("changed", current_updated_at=UPDATED_AT)

    result = await call(
        build_server(wiki, writer=wiki),
        "update_page",
        page_id="p1",
        expected_updated_at="2026-10-16T09:00:00Z",
        content="x",
        operation="append",
    )

    assert result.structured_content["error"]["code"] == "STALE_PAGE"
    assert result.structured_content["error"]["retryable"] is True
    assert result.structured_content["error"]["current_updated_at"] == "2026-10-16T10:00:00Z"


async def test_compatibility_is_checked_once_before_the_first_tool(wiki: FakeWiki) -> None:
    server = build_server(wiki, writer=None)
    async with Client(server) as client:
        await client.call_tool("list_spaces", {})
        await client.call_tool("list_spaces", {})

    assert [name for name, _ in wiki.calls].count("check_compatibility") == 1
    assert wiki.calls[0][0] == "check_compatibility"


async def test_unsupported_versions_fail_every_tool(wiki: FakeWiki) -> None:
    wiki.compatibility = UnsupportedVersionError("Docmost 0.97.0 is not a tested version.")

    result = await call(build_server(wiki, writer=None), "search", query="x")

    assert result.structured_content["error"]["code"] == "UNSUPPORTED_VERSION"
    assert [name for name, _ in wiki.calls] == ["check_compatibility"]


async def test_create_page_passes_content_and_format(wiki: FakeWiki) -> None:
    result = await call(
        build_server(wiki, writer=wiki),
        "create_page",
        space="engineering",
        title="New",
        content="<p>Hi</p>",
        format="html",
    )

    assert result.is_error is False
    assert result.structured_content["id"] == "p1"
    assert "content" not in result.structured_content
    assert (
        "create_page",
        {
            "space": "engineering",
            "title": "New",
            "content": "<p>Hi</p>",
            "format": "html",
            "parent_page_id": None,
            "icon": None,
        },
    ) in wiki.calls


async def test_update_page_requires_the_updated_at_the_agent_read(wiki: FakeWiki) -> None:
    result = await call(
        build_server(wiki, writer=wiki),
        "update_page",
        page_id="p1",
        content="x",
        operation="append",
    )

    assert result.is_error is True
    assert not any(name == "update_page" for name, _ in wiki.calls)


async def test_update_page_parses_timestamps_and_json_content(wiki: FakeWiki) -> None:
    result = await call(
        build_server(wiki, writer=wiki, confirm_replace=False),
        "update_page",
        page_id="p1",
        expected_updated_at="2026-10-16T05:00:00-05:00",
        content='{"type": "doc", "content": []}',
        operation="replace",
        format="json",
    )

    assert result.is_error is False
    name, kwargs = wiki.calls[-1]
    assert name == "update_page"
    assert kwargs["expected_updated_at"] == UPDATED_AT
    assert kwargs["content"] == {"type": "doc", "content": []}
    assert result.structured_content["updated_at"] == "2026-10-16T10:00:00Z"


async def test_update_page_rejects_malformed_json_content(wiki: FakeWiki) -> None:
    result = await call(
        build_server(wiki, writer=wiki, confirm_replace=False),
        "update_page",
        page_id="p1",
        expected_updated_at="2026-10-16T10:00:00Z",
        content="{not json",
        operation="replace",
        format="json",
    )

    assert result.structured_content["error"]["code"] == "INVALID_INPUT"
    assert not any(name == "update_page" for name, _ in wiki.calls)


@pytest.mark.parametrize("value", ["null", "123", "[1]"])
async def test_identifier_arguments_are_never_json_decoded(wiki: FakeWiki, value: str) -> None:
    result = await call(build_server(wiki, writer=None), "search", query="x", space=value)

    assert result.is_error is False
    _, kwargs = wiki.calls[-1]
    assert kwargs["space"] == value


async def test_empty_optional_identifiers_mean_not_given(wiki: FakeWiki) -> None:
    await call(build_server(wiki, writer=None), "list_children", space="engineering", cursor="")

    _, kwargs = wiki.calls[-1]
    assert kwargs == {"space": "engineering", "parent_page_id": None, "limit": 20, "cursor": None}


async def test_failed_compatibility_lookups_are_retried(wiki: FakeWiki) -> None:
    from docmost_client import UpstreamError

    wiki.compatibility = UpstreamError("down")
    server = build_server(wiki, writer=None)
    async with Client(server) as client:
        first = await client.call_tool("list_spaces", {})
        wiki.compatibility = CompatibilityReport(
            status="supported", docmost_version="0.96.0", supported_versions=("0.96.0",)
        )
        second = await client.call_tool("list_spaces", {})

    assert first.structured_content["error"]["code"] == "UPSTREAM_ERROR"
    assert second.is_error is False


async def test_explicit_nulls_for_optional_arguments_mean_not_given(wiki: FakeWiki) -> None:
    server = build_server(wiki, writer=wiki)
    async with Client(server) as client:
        listed = await client.call_tool(
            "list_children", {"space": "engineering", "parent_page_id": None, "cursor": None}
        )
        searched = await client.call_tool("search", {"query": "x", "space": None})
        updated = await client.call_tool(
            "update_page",
            {
                "page_id": "p1",
                "expected_updated_at": "2026-10-16T10:00:00Z",
                "title": "Renamed",
                "content": None,
            },
        )

    assert not listed.is_error
    assert not searched.is_error
    assert not updated.is_error
    calls = {name: kwargs for name, kwargs in wiki.calls}
    assert calls["list_children"]["parent_page_id"] is None
    assert calls["search"]["space"] is None
    assert calls["update_page"]["content"] is None


# --- block 1: recent pages, comments, replace confirmation --------------------


async def test_list_recent_pages(wiki: FakeWiki) -> None:
    result = await call(build_server(wiki, writer=None), "list_recent_pages", space="", limit=5)

    assert result.structured_content == {
        "pages": [
            {
                "id": "p1",
                "slug_id": "abc123xyz0",
                "title": "Runbook",
                "parent_page_id": None,
                "space": {"id": "s1", "slug": "engineering", "name": "Engineering"},
                "updated_at": "2026-10-16T10:00:00Z",
            }
        ],
        "next_cursor": "r2",
    }
    assert ("list_recent_pages", {"space": None, "limit": 5, "cursor": None}) in wiki.calls


async def test_list_comments(wiki: FakeWiki) -> None:
    result = await call(build_server(wiki, writer=None), "list_comments", page_id="p1")

    assert result.structured_content == {
        "comments": [
            {
                "id": "c1",
                "parent_comment_id": None,
                "type": "page",
                "selection": None,
                "text": "Should we drain first?",
                "author": "Ana",
                "created_at": "2026-10-16T10:00:00Z",
                "resolved": False,
            }
        ],
        "next_cursor": None,
    }


async def test_add_comment_exists_only_when_comments_are_allowed(wiki: FakeWiki) -> None:
    async with Client(build_server(wiki, writer=None)) as client:
        plain = {tool.name for tool in (await client.list_tools()).tools}
    async with Client(build_server(wiki, writer=None, commenter=wiki)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    assert "add_comment" not in plain
    assert set(tools) == READ_TOOLS | {"add_comment"}
    annotations = tools["add_comment"].annotations
    assert annotations is not None
    assert annotations.read_only_hint is False
    assert annotations.destructive_hint is False


async def test_add_comment_passes_plain_text(wiki: FakeWiki) -> None:
    server = build_server(wiki, writer=None, commenter=wiki)

    top = await call(server, "add_comment", page_id="p1", text="Looks good.")
    reply = await call(server, "add_comment", page_id="p1", text="+1", parent_comment_id="c1")

    assert top.structured_content["text"] == "Looks good."
    assert (
        "create_comment",
        {"page_id": "p1", "text": "Looks good.", "parent_comment_id": None},
    ) in wiki.calls
    assert reply.structured_content["parent_comment_id"] == "c1"


REPLACE = {
    "page_id": "p1",
    "expected_updated_at": "2026-10-16T10:00:00Z",
    "content": "New body",
    "operation": "replace",
}


async def _replace(server: Any, callback: Any) -> Any:
    async with Client(server, elicitation_callback=callback) as client:
        return await client.call_tool("update_page", REPLACE)


async def accept(context: Any, params: Any) -> Any:
    accept.asked.append(params.message)  # type: ignore[attr-defined]
    return mcp_types.ElicitResult(action="accept", content={"confirm": True})


accept.asked = []  # type: ignore[attr-defined]


async def decline(context: Any, params: Any) -> Any:
    return mcp_types.ElicitResult(action="decline")


async def test_replace_asks_the_user_and_proceeds_when_confirmed(wiki: FakeWiki) -> None:
    accept.asked.clear()  # type: ignore[attr-defined]

    result = await _replace(build_server(wiki, writer=wiki), accept)

    assert result.is_error is False
    assert any(name == "update_page" for name, _ in wiki.calls)
    assert len(accept.asked) == 1  # type: ignore[attr-defined]
    assert "p1" in accept.asked[0]  # type: ignore[attr-defined]


async def test_declined_replace_writes_nothing(wiki: FakeWiki) -> None:
    result = await _replace(build_server(wiki, writer=wiki), decline)

    assert result.structured_content["error"]["code"] == "CONFIRMATION_DECLINED"
    assert not any(name == "update_page" for name, _ in wiki.calls)


async def test_replace_is_blocked_when_the_host_cannot_ask(wiki: FakeWiki) -> None:
    result = await _replace(build_server(wiki, writer=wiki), None)

    assert result.structured_content["error"]["code"] == "CONFIRMATION_UNAVAILABLE"
    assert "DOCMOST_CONFIRM_REPLACE" in result.structured_content["error"]["message"]
    assert not any(name == "update_page" for name, _ in wiki.calls)


async def test_replace_without_confirmation_when_disabled(wiki: FakeWiki) -> None:
    accept.asked.clear()  # type: ignore[attr-defined]

    result = await _replace(build_server(wiki, writer=wiki, confirm_replace=False), accept)

    assert result.is_error is False
    assert accept.asked == []  # type: ignore[attr-defined]


async def test_append_never_asks(wiki: FakeWiki) -> None:
    accept.asked.clear()  # type: ignore[attr-defined]
    async with Client(build_server(wiki, writer=wiki), elicitation_callback=accept) as client:
        result = await client.call_tool("update_page", REPLACE | {"operation": "append"})

    assert result.is_error is False
    assert accept.asked == []  # type: ignore[attr-defined]


async def test_replace_without_content_never_asks(wiki: FakeWiki) -> None:
    accept.asked.clear()  # type: ignore[attr-defined]
    title_only = {k: v for k, v in REPLACE.items() if k != "content"} | {"title": "Renamed"}

    async with Client(build_server(wiki, writer=wiki), elicitation_callback=accept) as client:
        await client.call_tool("update_page", title_only)
    async with Client(build_server(wiki, writer=wiki)) as client:
        no_host = await client.call_tool("update_page", title_only)

    assert accept.asked == []  # type: ignore[attr-defined]
    assert no_host.structured_content.get("error", {}).get("code") != "CONFIRMATION_UNAVAILABLE"


@pytest.mark.parametrize(
    "answer",
    [
        mcp_types.ElicitResult(action="accept", content={"confirm": False}),
        mcp_types.ElicitResult(action="cancel"),
    ],
)
async def test_unconfirmed_replace_fails_closed(wiki: FakeWiki, answer: Any) -> None:
    async def respond(context: Any, params: Any) -> Any:
        return answer

    result = await _replace(build_server(wiki, writer=wiki), respond)

    assert result.structured_content["error"]["code"] == "CONFIRMATION_DECLINED"
    assert not any(name == "update_page" for name, _ in wiki.calls)
