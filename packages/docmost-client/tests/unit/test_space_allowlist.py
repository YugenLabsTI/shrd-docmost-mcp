"""DOCMOST_ALLOWED_SPACES is enforced inside the client, for every read path."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from docmost_client import AsyncDocmostClient, DocmostClient, DocmostSettings, SpaceNotAllowedError

BASE = "https://wiki.example.com"
API = f"{BASE}/api"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "v0_96_0"
ENG_ID = "0192b7a4-0000-7000-8000-0000000000b1"
OPS_ID = "0192b7a4-0000-7000-8000-0000000000b2"
PAGE_ID = "0192b7a4-0000-7000-8000-0000000000c1"
OPS_SPACE = {"id": OPS_ID, "name": "Operations", "slug": "ops"}


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def wrapped(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "success": True, "status": 200})


def body(route: respx.Route, index: int = -1) -> Any:
    return json.loads(route.calls[index].request.read())


def settings(allowed: str | None) -> DocmostSettings:
    env = {"DOCMOST_BASE_URL": BASE, "DOCMOST_EMAIL": "bot@example.com", "DOCMOST_PASSWORD": "pw"}
    if allowed is not None:
        env["DOCMOST_ALLOWED_SPACES"] = allowed
    return DocmostSettings.from_env(env)


def ops_page() -> dict[str, Any]:
    return fixture("page_info_markdown") | {
        "spaceId": OPS_ID,
        "space": OPS_SPACE,
        "content": "OPS SECRET",
    }


@pytest.fixture
def api(respx_mock: respx.MockRouter) -> respx.MockRouter:
    respx_mock.post(f"{API}/auth/login").mock(
        return_value=httpx.Response(200, headers={"set-cookie": "authToken=t; Path=/"}, json={})
    )
    respx_mock.post(f"{API}/auth/logout").mock(return_value=httpx.Response(200, json={}))
    return respx_mock


@pytest.fixture
def client(api: respx.MockRouter) -> Iterator[DocmostClient]:
    del api
    with DocmostClient(settings("Engineering")) as instance:
        yield instance


def space_info_route(api: respx.MockRouter) -> respx.Route:
    def info(request: httpx.Request) -> httpx.Response:
        requested = json.loads(request.read())["spaceId"].lower()
        if requested in ("engineering", ENG_ID):
            return wrapped(fixture("space_info"))
        if requested in ("ops", OPS_ID):
            return wrapped(fixture("space_info") | OPS_SPACE)
        return httpx.Response(404, json={"message": "Space not found", "statusCode": 404})

    return api.post(f"{API}/spaces/info").mock(side_effect=info)


pytestmark = pytest.mark.respx(assert_all_called=False)


def test_list_spaces_hides_spaces_outside_the_allowlist(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    api.post(f"{API}/spaces").mock(return_value=wrapped(fixture("spaces_list")))

    result = client.list_spaces()

    assert [space.slug for space in result.items] == ["engineering"]


def test_get_space_outside_the_allowlist_is_refused(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    space_info_route(api)

    with pytest.raises(SpaceNotAllowedError) as exc:
        client.get_space("ops")

    assert exc.value.code == "SPACE_NOT_ALLOWED"


def test_get_page_in_an_allowed_space_needs_no_extra_request(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    info = space_info_route(api)
    api.post(f"{API}/pages/info").mock(return_value=wrapped(fixture("page_info_markdown")))

    assert client.get_page(PAGE_ID).title == "Runbook"
    assert info.call_count == 0


def test_get_page_outside_the_allowlist_never_returns_content(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    space_info_route(api)
    api.post(f"{API}/pages/info").mock(return_value=wrapped(ops_page()))

    with pytest.raises(SpaceNotAllowedError) as exc:
        client.get_page(PAGE_ID)

    assert "OPS SECRET" not in str(exc.value)


def test_root_pages_of_a_disallowed_space_are_refused_before_listing(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    space_info_route(api)
    sidebar = api.post(f"{API}/pages/sidebar-pages")

    with pytest.raises(SpaceNotAllowedError):
        client.list_children(space="ops")

    assert sidebar.call_count == 0


def test_root_pages_of_a_disallowed_space_uuid_are_refused_before_listing(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    space_info_route(api)
    sidebar = api.post(f"{API}/pages/sidebar-pages")

    with pytest.raises(SpaceNotAllowedError):
        client.list_children(space=OPS_ID)

    assert sidebar.call_count == 0


def test_children_of_an_allowed_parent_resolve_the_allowlist_once(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    info = space_info_route(api)
    api.post(f"{API}/pages/sidebar-pages").mock(return_value=wrapped(fixture("sidebar_pages")))

    client.list_children(parent_page_id=PAGE_ID)
    client.list_children(parent_page_id=PAGE_ID)

    assert info.call_count == 1
    assert body(info) == {"spaceId": "engineering"}


def test_children_of_a_disallowed_parent_are_refused(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    space_info_route(api)
    children = fixture("sidebar_pages")
    children["items"][0]["spaceId"] = OPS_ID
    api.post(f"{API}/pages/sidebar-pages").mock(return_value=wrapped(children))

    with pytest.raises(SpaceNotAllowedError):
        client.list_children(parent_page_id=PAGE_ID)


def test_search_drops_hits_from_disallowed_spaces(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    results = fixture("search")
    results["items"].append(results["items"][0] | {"id": "other", "space": OPS_SPACE})
    api.post(f"{API}/search").mock(return_value=wrapped(results))

    results = client.search("worker", limit=2)

    assert [hit.space.slug for hit in results.hits] == ["engineering"]
    # Paging follows what Docmost returned, not what survived the allowlist.
    assert results.next_offset == 2


def test_search_within_a_disallowed_space_is_refused_before_searching(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    space_info_route(api)
    search = api.post(f"{API}/search")

    with pytest.raises(SpaceNotAllowedError):
        client.search("worker", space="ops")

    assert search.call_count == 0


def test_uuid_entries_need_no_resolution(api: respx.MockRouter) -> None:
    info = space_info_route(api)
    api.post(f"{API}/pages/sidebar-pages").mock(return_value=wrapped(fixture("sidebar_pages")))

    with DocmostClient(settings(ENG_ID.upper())) as client:
        client.list_children(parent_page_id=PAGE_ID)

    assert info.call_count == 0


def test_unresolvable_entries_grant_nothing(api: respx.MockRouter) -> None:
    space_info_route(api)
    api.post(f"{API}/pages/sidebar-pages").mock(return_value=wrapped(fixture("sidebar_pages")))

    with DocmostClient(settings("deleted-space")) as client, pytest.raises(SpaceNotAllowedError):
        client.list_children(parent_page_id=PAGE_ID)


def test_without_an_allowlist_nothing_is_filtered(api: respx.MockRouter) -> None:
    info = space_info_route(api)
    api.post(f"{API}/spaces").mock(return_value=wrapped(fixture("spaces_list")))
    api.post(f"{API}/pages/info").mock(return_value=wrapped(ops_page()))

    with DocmostClient(settings(None)) as client:
        assert len(client.list_spaces().items) == 2
        assert client.get_page(PAGE_ID).content == "OPS SECRET"

    assert info.call_count == 0


@pytest.mark.anyio
async def test_async_client_enforces_the_allowlist(api: respx.MockRouter) -> None:
    space_info_route(api)
    api.post(f"{API}/pages/info").mock(return_value=wrapped(ops_page()))

    async with AsyncDocmostClient(settings("engineering")) as client:
        with pytest.raises(SpaceNotAllowedError):
            await client.get_page(PAGE_ID)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
