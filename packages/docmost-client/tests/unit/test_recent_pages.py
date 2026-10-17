"""list_recent_pages: what changed lately, scoped by the space allowlist."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
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
    SpaceNotAllowedError,
)

BASE = "https://wiki.example.com"
API = f"{BASE}/api"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "v0_96_0"
ENG_ID = "0192b7a4-0000-7000-8000-0000000000b1"
OPS_ID = "0192b7a4-0000-7000-8000-0000000000b2"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def wrapped(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "success": True, "status": 200})


def body(route: respx.Route) -> Any:
    return json.loads(route.calls[-1].request.read())


def settings(**extra: str) -> DocmostSettings:
    return DocmostSettings.from_env(
        {"DOCMOST_BASE_URL": BASE, "DOCMOST_EMAIL": "bot@example.com", "DOCMOST_PASSWORD": "pw"}
        | extra
    )


@pytest.fixture
def api(respx_mock: respx.MockRouter) -> respx.MockRouter:
    respx_mock.post(f"{API}/auth/login").mock(
        return_value=httpx.Response(200, headers={"set-cookie": "authToken=t; Path=/"}, json={})
    )
    respx_mock.post(f"{API}/auth/logout").mock(return_value=httpx.Response(200, json={}))
    respx_mock.post(f"{API}/spaces/info").mock(return_value=wrapped(fixture("space_info")))
    return respx_mock


@pytest.fixture
def client(api: respx.MockRouter) -> Iterator[DocmostClient]:
    del api
    with DocmostClient(settings()) as instance:
        yield instance


pytestmark = pytest.mark.respx(assert_all_called=False)


def test_recent_pages_across_spaces(client: DocmostClient, api: respx.MockRouter) -> None:
    route = api.post(f"{API}/pages/recent").mock(return_value=wrapped(fixture("recent_pages")))

    result = client.list_recent_pages()

    assert body(route) == {"limit": 20}
    first = result.items[0]
    assert first.id == "0192b7a4-0000-7000-8000-0000000000c1"
    assert first.slug_id == "abc123xyz0"
    assert first.title == "Runbook"
    assert first.parent_page_id is None
    assert first.space.slug == "engineering"
    assert first.updated_at == datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
    assert first.last_updated_by_id == "0192b7a4-0000-7000-8000-000000000002"
    assert [page.title for page in result.items] == ["Runbook", "Ops secrets"]
    assert result.has_next_page is True
    assert result.next_cursor == "cmVjZW50LTI"


def test_recent_pages_of_one_space_by_slug(client: DocmostClient, api: respx.MockRouter) -> None:
    route = api.post(f"{API}/pages/recent").mock(return_value=wrapped(fixture("recent_pages")))

    client.list_recent_pages(space="engineering", limit=5, cursor="c1")

    assert body(route) == {"spaceId": ENG_ID, "limit": 5, "cursor": "c1"}


def test_recent_pages_respect_the_allowlist(api: respx.MockRouter) -> None:
    api.post(f"{API}/pages/recent").mock(return_value=wrapped(fixture("recent_pages")))

    with DocmostClient(settings(DOCMOST_ALLOWED_SPACES="engineering,sandbox")) as client:
        result = client.list_recent_pages()

    assert [page.space.slug for page in result.items] == ["engineering"]
    # Paging follows what Docmost returned, not what survived the allowlist.
    assert result.has_next_page is True


def test_recent_pages_of_a_disallowed_space_are_refused_before_listing(
    api: respx.MockRouter,
) -> None:
    route = api.post(f"{API}/pages/recent")

    with (
        DocmostClient(settings(DOCMOST_ALLOWED_SPACES="engineering")) as client,
        pytest.raises(SpaceNotAllowedError),
    ):
        client.list_recent_pages(space=OPS_ID)

    assert route.call_count == 0


def test_recent_pages_validate_the_page_size(client: DocmostClient) -> None:
    with pytest.raises(InvalidRequestError, match="limit"):
        client.list_recent_pages(limit=0)


@pytest.mark.anyio
async def test_async_client_lists_recent_pages(api: respx.MockRouter) -> None:
    api.post(f"{API}/pages/recent").mock(return_value=wrapped(fixture("recent_pages")))

    async with AsyncDocmostClient(settings()) as client:
        result = await client.list_recent_pages()

    assert len(result.items) == 2


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_a_single_allowed_space_scopes_the_request(api: respx.MockRouter) -> None:
    route = api.post(f"{API}/pages/recent").mock(return_value=wrapped(fixture("recent_pages")))

    with DocmostClient(settings(DOCMOST_ALLOWED_SPACES="engineering")) as client:
        client.list_recent_pages()

    # Asking Docmost for that space avoids pages emptied by allowlist filtering.
    assert body(route) == {"spaceId": ENG_ID, "limit": 20}
