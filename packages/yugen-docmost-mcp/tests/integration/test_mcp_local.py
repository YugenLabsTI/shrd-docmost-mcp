"""End-to-end MCP tests against the local Docmost 0.96.0 from dev/docmost.

Opt-in: DOCMOST_INTEGRATION=1 plus the variables from dev/docmost/.env.test. The agent
writes only to the sandbox space.
"""

import os
import uuid
from typing import Any

import pytest
from mcp import Client

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
    return DocmostSettings.from_env(env)


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

    assert names == {"search", "list_spaces", "get_page", "list_children"}
    assert result.is_error is False
