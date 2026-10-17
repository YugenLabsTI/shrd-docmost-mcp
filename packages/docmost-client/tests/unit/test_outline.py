"""get_page_outline: the top-level headings an agent can target for section edits."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from docmost_client import AsyncDocmostClient, DocmostClient, DocmostSettings, NotFoundError

BASE = "https://wiki.example.com"
API = f"{BASE}/api"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "v0_96_0"
PAGE_ID = "0192b7a4-0000-7000-8000-0000000000c1"

DOCUMENT = {
    "type": "doc",
    "content": [
        {
            "type": "heading",
            "attrs": {"id": "h-guide", "level": 1},
            "content": [{"type": "text", "text": "Guide"}],
        },
        {"type": "paragraph", "content": [{"type": "text", "text": "Intro"}]},
        {
            "type": "heading",
            "attrs": {"id": "h-install", "level": 2},
            "content": [
                {"type": "text", "text": "Install "},
                {"type": "text", "text": "now", "marks": [{"type": "bold"}]},
            ],
        },
        {
            "type": "details",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"id": "h-nested", "level": 3},
                    "content": [{"type": "text", "text": "Nested"}],
                }
            ],
        },
        {"type": "heading", "attrs": {"id": "h-empty", "level": 2}},
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "No id"}]},
    ],
}


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def wrapped(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "success": True, "status": 200})


def settings() -> DocmostSettings:
    return DocmostSettings.from_env(
        {"DOCMOST_BASE_URL": BASE, "DOCMOST_EMAIL": "bot@example.com", "DOCMOST_PASSWORD": "pw"}
    )


@pytest.fixture
def api(respx_mock: respx.MockRouter) -> respx.MockRouter:
    respx_mock.post(f"{API}/auth/login").mock(
        return_value=httpx.Response(200, headers={"set-cookie": "authToken=t; Path=/"}, json={})
    )
    respx_mock.post(f"{API}/auth/logout").mock(return_value=httpx.Response(200, json={}))
    respx_mock.post(f"{API}/pages/info", name="page").mock(
        return_value=wrapped(fixture("page_info_markdown") | {"content": DOCUMENT})
    )
    return respx_mock


pytestmark = pytest.mark.respx(assert_all_called=False)


def test_outline_lists_top_level_headings(api: respx.MockRouter) -> None:
    with DocmostClient(settings()) as client:
        outline = client.get_page_outline("abc123xyz0")

    request = json.loads(api.routes["page"].calls[-1].request.read())
    assert request == {"pageId": "abc123xyz0", "format": "json"}
    assert outline.page_id == PAGE_ID
    assert outline.title == "Runbook"
    assert outline.updated_at.isoformat() == "2026-10-16T10:00:00+00:00"
    assert [(h.id, h.level, h.text) for h in outline.headings] == [
        ("h-guide", 1, "Guide"),
        ("h-install", 2, "Install now"),
        ("h-empty", 2, ""),
    ]


def test_outline_of_a_page_without_content_is_empty(api: respx.MockRouter) -> None:
    api.routes["page"].mock(return_value=wrapped(fixture("page_info_markdown") | {"content": None}))

    with DocmostClient(settings()) as client:
        assert client.get_page_outline(PAGE_ID).headings == []


def test_outline_of_a_trashed_page_is_not_found(api: respx.MockRouter) -> None:
    api.routes["page"].mock(
        return_value=wrapped(
            fixture("page_info_markdown")
            | {"content": DOCUMENT, "deletedAt": "2026-10-01T00:00:00Z"}
        )
    )

    with DocmostClient(settings()) as client, pytest.raises(NotFoundError):
        client.get_page_outline(PAGE_ID)


@pytest.mark.anyio
async def test_async_outline(api: respx.MockRouter) -> None:
    async with AsyncDocmostClient(settings()) as client:
        outline = await client.get_page_outline(PAGE_ID)

    assert len(outline.headings) == 3


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
