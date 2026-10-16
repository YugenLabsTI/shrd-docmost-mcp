"""Entry point and end-to-end wiring with the real client (HTTP mocked)."""

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from mcp import Client

from docmost_client import DocmostSettings
from yugen_docmost_mcp import __version__
from yugen_docmost_mcp.__main__ import create_server, main

BASE = "https://wiki.example.com"
API = f"{BASE}/api"
PASSWORD = "s3cr3t-Pa55word!"
FIXTURES = Path(__file__).parents[2] / "docmost-client" / "tests" / "fixtures" / "v0_96_0"


def wrapped(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "success": True, "status": 200})


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def settings(**extra: str) -> DocmostSettings:
    return DocmostSettings.from_env(
        {
            "DOCMOST_BASE_URL": BASE,
            "DOCMOST_EMAIL": "bot@example.com",
            "DOCMOST_PASSWORD": PASSWORD,
            **extra,
        }
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def api(respx_mock: respx.MockRouter) -> respx.MockRouter:
    respx_mock.post(f"{API}/auth/login").mock(
        return_value=httpx.Response(200, headers={"set-cookie": "authToken=tok; Path=/"}, json={})
    )
    respx_mock.post(f"{API}/auth/logout", name="logout").mock(
        return_value=httpx.Response(200, json={})
    )
    respx_mock.post(f"{API}/version").mock(return_value=wrapped(fixture("version")))
    return respx_mock


def test_missing_configuration_exits_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("DOCMOST_BASE_URL", "DOCMOST_EMAIL", "DOCMOST_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SystemExit) as exc:
        main([])

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "DOCMOST_BASE_URL is required" in err
    assert "Traceback" not in err


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"yugen-docmost-mcp {__version__}"


@pytest.mark.anyio
@pytest.mark.parametrize(("read_only", "has_writes"), [("1", False), ("0", True)])
async def test_write_tools_follow_read_only_setting(read_only: str, has_writes: bool) -> None:
    async with Client(create_server(settings(DOCMOST_READ_ONLY=read_only))) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}

    assert ("update_page" in names) is has_writes
    assert ("create_page" in names) is has_writes


@pytest.mark.anyio
@pytest.mark.respx(assert_all_called=False)
async def test_search_end_to_end_through_the_real_client(api: respx.MockRouter) -> None:
    search = api.post(f"{API}/search").mock(return_value=wrapped(fixture("search")))

    async with Client(create_server(settings())) as client:
        result = await client.call_tool("search", {"query": "worker"})

    assert result.is_error is False
    assert result.structured_content["hits"][0]["title"] == "Runbook"
    assert json.loads(search.calls[0].request.read())["query"] == "worker"


@pytest.mark.anyio
@pytest.mark.respx(assert_all_called=False)
async def test_failures_never_log_credentials_or_content(
    api: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    page = fixture("page_info_markdown") | {
        "content": "TOP SECRET BODY",
        "spaceId": "0192b7a4-0000-7000-8000-0000000000b2",
        "space": {"id": "0192b7a4-0000-7000-8000-0000000000b2", "name": "Ops", "slug": "ops"},
    }
    api.post(f"{API}/pages/info").mock(return_value=wrapped(page))
    caplog.set_level(logging.DEBUG)

    server = create_server(settings(DOCMOST_ALLOWED_SPACES="engineering"))
    async with Client(server) as client:
        result = await client.call_tool("get_page", {"page_id": "abc123xyz0"})

    assert result.structured_content["error"]["code"] == "SPACE_NOT_ALLOWED"
    for text in (caplog.text, json.dumps(result.structured_content)):
        assert PASSWORD not in text
        assert "TOP SECRET BODY" not in text
        assert "tok" not in text.replace("token", "")


@pytest.mark.anyio
@pytest.mark.respx(assert_all_called=False)
async def test_shutdown_logs_out_to_revoke_the_session(api: respx.MockRouter) -> None:
    api.post(f"{API}/search").mock(return_value=wrapped(fixture("search")))

    async with Client(create_server(settings())) as client:
        await client.call_tool("search", {"query": "worker"})

    assert api.routes["logout"].call_count == 1
