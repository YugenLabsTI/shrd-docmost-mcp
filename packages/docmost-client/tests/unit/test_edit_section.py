"""edit_section: one section rewritten safely through a whole-page HTML replace."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from docmost_client import (
    AsyncDocmostClient,
    DocmostClient,
    DocmostSettings,
    InvalidRequestError,
    NotFoundError,
    PageBusyError,
    PermissionDeniedError,
    ReadOnlyError,
    SpaceNotAllowedError,
    StalePageError,
    _ops,
)
from docmost_client._sections import splice_section

BASE = "https://wiki.example.com"
API = f"{BASE}/api"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "v0_96_0"
PAGE_ID = "0192b7a4-0000-7000-8000-0000000000c1"
OPS_ID = "0192b7a4-0000-7000-8000-0000000000b2"
UPDATED_AT = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
HTML = (
    '<h2 data-id="install" id="install">Install</h2><p>Run it. Ask '
    '<span data-type="mention" data-id="u1" data-label="Ana">@Ana</span>.</p>'
    '<h2 data-id="configure" id="configure">Configure</h2><p>Old body.</p>'
)
NEW = "<p>New body.</p>"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def wrapped(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "success": True, "status": 200})


def body(route: respx.Route) -> Any:
    return json.loads(route.calls[-1].request.read())


def page(**overrides: Any) -> dict[str, Any]:
    return fixture("page_info_markdown") | {"content": HTML} | overrides


def settings(**extra: str) -> DocmostSettings:
    return DocmostSettings.from_env(
        {
            "DOCMOST_BASE_URL": BASE,
            "DOCMOST_EMAIL": "bot@example.com",
            "DOCMOST_PASSWORD": "pw",
            "DOCMOST_READ_ONLY": "0",
        }
        | extra
    )


@pytest.fixture(autouse=True)
def quiet_page(monkeypatch: pytest.MonkeyPatch) -> None:
    # The page was last saved 10 minutes before "now": outside the busy window.
    monkeypatch.setattr(_ops, "_utcnow", lambda: UPDATED_AT + timedelta(minutes=10))


@pytest.fixture
def api(respx_mock: respx.MockRouter) -> respx.MockRouter:
    respx_mock.post(f"{API}/auth/login").mock(
        return_value=httpx.Response(200, headers={"set-cookie": "authToken=t; Path=/"}, json={})
    )
    respx_mock.post(f"{API}/auth/logout").mock(return_value=httpx.Response(200, json={}))
    respx_mock.post(f"{API}/pages/info", name="info").mock(return_value=wrapped(page()))
    respx_mock.post(f"{API}/pages/update", name="update").mock(
        return_value=wrapped(page(content="<p>stored</p>", updatedAt="2026-10-16T10:20:00.000Z"))
    )
    return respx_mock


@pytest.fixture
def client(api: respx.MockRouter) -> Iterator[DocmostClient]:
    del api
    with DocmostClient(settings()) as instance:
        yield instance


pytestmark = pytest.mark.respx(assert_all_called=False)


def edit(client: DocmostClient, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "heading_id": "configure",
        "operation": "replace",
        "content": NEW,
        "expected_updated_at": UPDATED_AT,
    } | overrides
    return client.edit_section("abc123xyz0", **arguments)


def test_replaces_one_section_through_a_whole_page_html_replace(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    result = edit(client)

    assert body(api.routes["info"]) == {"pageId": "abc123xyz0", "format": "html"}
    assert body(api.routes["update"]) == {
        "pageId": PAGE_ID,
        "content": splice_section(HTML, "configure", "replace", NEW),
        "operation": "replace",
        "format": "html",
    }
    assert result.format == "html"
    assert result.updated_at == datetime(2026, 10, 16, 10, 20, tzinfo=UTC)


def test_existing_mentions_do_not_block_the_edit_but_new_ones_do(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    edit(client, operation="append")
    assert api.routes["update"].call_count == 1

    with pytest.raises(InvalidRequestError, match="mention"):
        edit(client, content='<p><span data-type="mention" data-id="u2">@Bo</span></p>')
    assert api.routes["update"].call_count == 1


def test_writes_are_blocked_by_default(api: respx.MockRouter) -> None:
    default = settings(DOCMOST_READ_ONLY="1")
    with DocmostClient(default) as client, pytest.raises(ReadOnlyError):
        edit(client)

    assert api.routes["info"].call_count == 0


def test_a_recently_saved_page_is_busy(
    client: DocmostClient, api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_ops, "_utcnow", lambda: UPDATED_AT + timedelta(seconds=30))

    with pytest.raises(PageBusyError, match="30") as exc:
        edit(client)

    assert exc.value.code == "PAGE_BUSY"
    assert api.routes["update"].call_count == 0


def test_the_busy_window_ends_after_sixty_seconds(
    client: DocmostClient, api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_ops, "_utcnow", lambda: UPDATED_AT + timedelta(seconds=61))

    edit(client)

    assert api.routes["update"].call_count == 1


def test_a_stale_page_is_refused(client: DocmostClient, api: respx.MockRouter) -> None:
    with pytest.raises(StalePageError):
        edit(client, expected_updated_at=UPDATED_AT - timedelta(minutes=1))

    assert api.routes["update"].call_count == 0


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"isLocked": True}, PermissionDeniedError),
        ({"permissions": {"canEdit": False, "hasRestriction": True}}, PermissionDeniedError),
        ({"deletedAt": "2026-10-01T00:00:00.000Z"}, NotFoundError),
        ({"spaceId": OPS_ID, "space": {"id": OPS_ID, "name": "Ops", "slug": "ops"}}, None),
    ],
)
def test_pages_that_cannot_be_edited_are_refused_before_writing(
    api: respx.MockRouter, overrides: dict[str, Any], error: type[Exception] | None
) -> None:
    api.routes["info"].mock(return_value=wrapped(page(**overrides)))

    with (
        DocmostClient(settings(DOCMOST_ALLOWED_SPACES="engineering")) as client,
        pytest.raises(error or SpaceNotAllowedError),
    ):
        edit(client)

    assert api.routes["update"].call_count == 0


@pytest.mark.parametrize(
    ("overrides", "error", "match"),
    [
        ({"heading_id": "missing"}, NotFoundError, "outline"),
        ({"operation": "delete"}, InvalidRequestError, "operation"),
        ({"content": "  "}, InvalidRequestError, "empty"),
        ({"content": "<div>unclosed"}, InvalidRequestError, "well-formed"),
        ({"expected_updated_at": datetime(2026, 10, 16, 10, 0)}, InvalidRequestError, "timezone"),
    ],
)
def test_invalid_edits_write_nothing(
    client: DocmostClient,
    api: respx.MockRouter,
    overrides: dict[str, Any],
    error: type[Exception],
    match: str,
) -> None:
    with pytest.raises(error, match=match):
        edit(client, **overrides)

    assert api.routes["update"].call_count == 0


def test_the_resulting_page_must_fit_the_size_limit(api: respx.MockRouter) -> None:
    with (
        DocmostClient(settings(DOCMOST_MAX_CONTENT_BYTES="200")) as client,
        pytest.raises(InvalidRequestError, match="DOCMOST_MAX_CONTENT_BYTES"),
    ):
        edit(client, operation="append")

    assert api.routes["update"].call_count == 0


@pytest.mark.anyio
async def test_async_client_edits_sections(api: respx.MockRouter) -> None:
    async with AsyncDocmostClient(settings()) as client:
        await client.edit_section(
            PAGE_ID,
            heading_id="install",
            operation="prepend",
            content=NEW,
            expected_updated_at=UPDATED_AT,
        )

    assert body(api.routes["update"])["content"] == splice_section(HTML, "install", "prepend", NEW)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
