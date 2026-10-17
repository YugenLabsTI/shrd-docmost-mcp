"""End-to-end MCP tests against the local Docmost 0.96.0 from dev/docmost.

Opt-in: DOCMOST_INTEGRATION=1 plus the variables from dev/docmost/.env.test. The agent
writes only to the sandbox space.
"""

import os
import uuid
from typing import Any

import mcp_types
import pytest
from mcp import Client, MCPError

from docmost_client import DocmostSettings
from yugen_docmost_mcp.__main__ import create_server

pytestmark = [
    pytest.mark.integration,
    pytest.mark.anyio,
    pytest.mark.skipif(
        os.environ.get("DOCMOST_INTEGRATION") != "1",
        reason="set DOCMOST_INTEGRATION=1 and load dev/docmost/.env.test",
    ),
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def settings(**overrides: str) -> DocmostSettings:
    env = {key: value for key, value in os.environ.items() if key.startswith("DOCMOST_")}
    env.update(overrides)
    settings = DocmostSettings.from_env(env)
    # Never write to a real instance (S14): these tests only target dev/docmost.
    assert settings.base_url.startswith(("http://localhost", "http://127.0.0.1"))
    return settings


async def test_agent_workflow_over_mcp() -> None:
    server = create_server(
        settings(DOCMOST_READ_ONLY="0", DOCMOST_ALLOWED_SPACES="engineering,sandbox")
    )
    async with Client(server) as client:
        spaces = await client.call_tool("list_spaces", {})
        slugs = {space["slug"] for space in spaces.structured_content["spaces"]}
        assert slugs == {"engineering", "sandbox"}  # "general" hidden by the allowlist

        found = await client.call_tool("search", {"query": "worker", "space": "engineering"})
        runbook = next(hit for hit in found.structured_content["hits"] if hit["title"] == "Runbook")
        page = await client.call_tool("get_page", {"page_id": runbook["page_id"]})
        assert "Restart the worker pool" in page.structured_content["content"]
        assert page.structured_content["can_edit"] is False

        denied = await client.call_tool(
            "update_page",
            {
                "page_id": runbook["page_id"],
                "expected_updated_at": page.structured_content["updated_at"],
                "content": "x",
                "operation": "append",
            },
        )
        assert denied.structured_content["error"]["code"] == "FORBIDDEN"

        created = await client.call_tool(
            "create_page",
            {"space": "sandbox", "title": f"MCP {uuid.uuid4().hex[:8]}", "content": "One."},
        )
        assert created.is_error is False
        new_id = created.structured_content["id"]
        current = await client.call_tool("get_page", {"page_id": new_id})
        stamp: Any = current.structured_content["updated_at"]

        appended = await client.call_tool(
            "update_page",
            {
                "page_id": new_id,
                "expected_updated_at": stamp,
                "content": "Two.",
                "operation": "append",
            },
        )
        assert "Two." in appended.structured_content["content"]

        stale = await client.call_tool(
            "update_page",
            {
                "page_id": new_id,
                "expected_updated_at": stamp,
                "content": "Three.",
                "operation": "append",
            },
        )
        assert stale.structured_content["error"]["code"] == "STALE_PAGE"
        assert stale.structured_content["error"]["retryable"] is True


async def test_read_only_server_has_no_write_tools() -> None:
    async with Client(create_server(settings(DOCMOST_READ_ONLY="1"))) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        result = await client.call_tool("list_spaces", {})

    assert names == {
        "search",
        "list_spaces",
        "get_page",
        "list_children",
        "list_recent_pages",
        "list_comments",
        "get_page_outline",
    }
    assert result.is_error is False


async def test_comments_and_replace_confirmation_over_mcp() -> None:
    async def accept(context: Any, params: Any) -> Any:
        return mcp_types.ElicitResult(action="accept", content={"confirm": True})

    async def decline(context: Any, params: Any) -> Any:
        return mcp_types.ElicitResult(action="decline")

    server_settings = settings(
        DOCMOST_READ_ONLY="0",
        DOCMOST_ALLOW_COMMENTS="1",
        DOCMOST_ALLOWED_SPACES="engineering,sandbox",
    )
    title = f"MCP confirm {uuid.uuid4().hex[:8]}"
    async with Client(create_server(server_settings), elicitation_callback=decline) as client:
        created = await client.call_tool(
            "create_page", {"space": "sandbox", "title": title, "content": "Original."}
        )
        page_id = created.structured_content["id"]
        comment = await client.call_tool("add_comment", {"page_id": page_id, "text": "Via MCP."})
        assert comment.structured_content["text"] == "Via MCP."
        comments = await client.call_tool("list_comments", {"page_id": page_id})
        assert [c["text"] for c in comments.structured_content["comments"]] == ["Via MCP."]

        read = await client.call_tool("get_page", {"page_id": page_id})
        stamp = read.structured_content["updated_at"]
        replace = {
            "page_id": page_id,
            "expected_updated_at": stamp,
            "content": "Replaced.",
            "operation": "replace",
        }
        declined = await client.call_tool("update_page", replace)
        assert declined.structured_content["error"]["code"] == "CONFIRMATION_DECLINED"
        unchanged = await client.call_tool("get_page", {"page_id": page_id})
        assert "Original." in unchanged.structured_content["content"]
        assert unchanged.structured_content["updated_at"] == stamp

    async with Client(create_server(server_settings), elicitation_callback=accept) as client:
        replaced = await client.call_tool("update_page", replace)
        assert replaced.is_error is False
        assert "Replaced." in replaced.structured_content["content"]
        assert "Original." not in replaced.structured_content["content"]


async def test_section_editing_over_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []

    async def accept(context: Any, params: Any) -> Any:
        asked.append(params.message)
        return mcp_types.ElicitResult(action="accept", content={"confirm": True})

    server_settings = settings(DOCMOST_READ_ONLY="0", DOCMOST_ALLOWED_SPACES="sandbox")
    html = "<h2>One</h2><p>First.</p><h2>Two</h2><p>Second.</p>"
    async with Client(create_server(server_settings), elicitation_callback=accept) as client:
        created = await client.call_tool(
            "create_page",
            {
                "space": "sandbox",
                "title": f"MCP sections {uuid.uuid4().hex[:8]}",
                "content": html,
                "format": "html",
            },
        )
        page_id = created.structured_content["id"]
        outline = (
            await client.call_tool("get_page_outline", {"page_id": page_id})
        ).structured_content
        two = next(h for h in outline["headings"] if h["text"] == "Two")
        edit = {
            "page_id": page_id,
            "heading_id": two["id"],
            "operation": "replace",
            "content": "<p>Changed.</p>",
            "expected_updated_at": outline["updated_at"],
        }

        busy = await client.call_tool("edit_section", edit)
        assert busy.structured_content["error"]["code"] == "PAGE_BUSY"
        assert asked == []

        from datetime import UTC, datetime, timedelta

        from docmost_client import _ops
        from docmost_client._protocol import ServerClock

        # Pretend two minutes passed on both clocks, so the busy window does not apply.
        later = lambda *_: datetime.now(UTC) + timedelta(minutes=2)  # noqa: E731
        monkeypatch.setattr(ServerClock, "now", later)
        monkeypatch.setattr(_ops, "_utcnow", later)
        done = await client.call_tool("edit_section", edit)
        assert done.is_error is False
        assert len(asked) == 1
        assert "Changed." in done.structured_content["content"]
        assert "First." in done.structured_content["content"]
        assert "Second." not in done.structured_content["content"]


async def test_resources_and_prompts_over_mcp() -> None:
    title = f"Resources {uuid.uuid4().hex[:8]}"
    writer = settings(DOCMOST_READ_ONLY="0", DOCMOST_ALLOWED_SPACES="sandbox")
    async with Client(create_server(writer)) as client:
        created = await client.call_tool(
            "create_page", {"space": "sandbox", "title": title, "content": "Hello resources."}
        )
        assert created.is_error is False
        slug = created.structured_content["slug_id"]

        page = await client.read_resource(f"docmost://page/{slug}")
        tree = await client.read_resource("docmost://space/sandbox/tree")
        recent = await client.read_resource("docmost://recent")
        with pytest.raises(MCPError, match="SPACE_NOT_ALLOWED"):
            await client.read_resource("docmost://space/engineering/tree")
        prompts = {p.name for p in (await client.list_prompts()).prompts}
        summary = await client.get_prompt("summarize_page", {"page_id": slug})

    page_text = page.contents[0].text  # type: ignore[union-attr]
    assert page_text.startswith(f"# {title}\n")
    assert "Hello resources." in page_text
    assert f"- {title} ({slug})" in tree.contents[0].text  # type: ignore[union-attr]
    assert f"{title} ({slug}) in sandbox" in recent.contents[0].text  # type: ignore[union-attr]
    assert prompts == {"summarize_page", "answer_from_wiki"}
    assert slug in summary.messages[0].content.text  # type: ignore[union-attr]
