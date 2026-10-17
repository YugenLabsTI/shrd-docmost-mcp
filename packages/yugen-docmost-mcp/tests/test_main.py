"""Entry point and end-to-end wiring with the real client (HTTP mocked)."""

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from mcp import Client

from docmost_client import ConfigError, DocmostSettings
from yugen_docmost_mcp import __version__
from yugen_docmost_mcp.__main__ import confirm_replace_from_env, create_server, main
from yugen_docmost_mcp.prompts import load_prompt_dir

BASE = "https://wiki.example.com"
API = f"{BASE}/api"
PASSWORD = "s3cr3t-Pa55word!"
READ_TOOLS = {
    "search",
    "list_spaces",
    "get_page",
    "list_children",
    "list_recent_pages",
    "list_comments",
    "get_page_outline",
}
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


@pytest.mark.parametrize(
    ("raw", "expected"), [(None, True), ("1", True), ("true", True), ("0", False), ("no", False)]
)
def test_replace_confirmation_flag(raw: str | None, expected: bool) -> None:
    environ = {} if raw is None else {"DOCMOST_CONFIRM_REPLACE": raw}

    assert confirm_replace_from_env(environ) is expected


def test_invalid_replace_confirmation_flag_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="DOCMOST_CONFIRM_REPLACE"):
        confirm_replace_from_env({"DOCMOST_CONFIRM_REPLACE": "maybe"})


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("allow", "read_only", "expected"),
    [
        ("0", "1", set()),
        ("1", "1", {"add_comment"}),
        ("0", "0", {"create_page", "update_page", "edit_section"}),
        ("1", "0", {"add_comment", "create_page", "update_page", "edit_section"}),
    ],
)
async def test_permission_matrix_controls_the_write_tools(
    allow: str, read_only: str, expected: set[str]
) -> None:
    server = create_server(settings(DOCMOST_ALLOW_COMMENTS=allow, DOCMOST_READ_ONLY=read_only))
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}

    assert names - READ_TOOLS == expected


def test_invalid_replace_confirmation_flag_stops_startup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for key, value in {
        "DOCMOST_BASE_URL": BASE,
        "DOCMOST_EMAIL": "bot@example.com",
        "DOCMOST_PASSWORD": PASSWORD,
        "DOCMOST_CONFIRM_REPLACE": "maybe",
    }.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(SystemExit) as exc:
        main([])

    assert exc.value.code == 2
    assert "DOCMOST_CONFIRM_REPLACE" in capsys.readouterr().err


def test_an_invalid_prompts_dir_stops_startup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    (tmp_path / "bad.toml").write_text('name = "x"\ntemplate = "{{who}}"', encoding="utf-8")
    for key, value in {
        "DOCMOST_BASE_URL": BASE,
        "DOCMOST_EMAIL": "bot@example.com",
        "DOCMOST_PASSWORD": PASSWORD,
        "DOCMOST_PROMPTS_DIR": str(tmp_path),
    }.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(SystemExit) as exc:
        main([])

    assert exc.value.code == 2
    assert "bad.toml" in capsys.readouterr().err


def test_the_example_prompts_are_valid() -> None:
    examples = Path(__file__).parents[3] / "examples" / "prompts"

    assert [p.name for p in load_prompt_dir(examples)] == ["weekly_report"]
