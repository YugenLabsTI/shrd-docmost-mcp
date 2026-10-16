"""Read operations of DocmostClient / AsyncDocmostClient against v0.96.0 fixtures."""

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
    NotFoundError,
    UnsupportedVersionError,
    UpstreamError,
)

BASE = "https://wiki.example.com"
API = f"{BASE}/api"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "v0_96_0"
SPACE_ID = "0192b7a4-0000-7000-8000-0000000000b1"
PAGE_ID = "0192b7a4-0000-7000-8000-0000000000c1"


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def wrapped(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "success": True, "status": 200})


def body(route: respx.Route, index: int = -1) -> Any:
    return json.loads(route.calls[index].request.read())


def settings(**extra: str) -> DocmostSettings:
    return DocmostSettings.from_env(
        {
            "DOCMOST_BASE_URL": BASE,
            "DOCMOST_EMAIL": "bot@example.com",
            "DOCMOST_PASSWORD": "pw",
            **extra,
        }
    )


@pytest.fixture
def api(respx_mock: respx.MockRouter) -> respx.MockRouter:
    respx_mock.post(f"{API}/auth/login").mock(
        return_value=httpx.Response(
            200, json={"success": True}, headers={"set-cookie": "authToken=t0k; Path=/"}
        )
    )
    respx_mock.post(f"{API}/auth/logout").mock(return_value=httpx.Response(200, json={}))
    return respx_mock


@pytest.fixture
def client(api: respx.MockRouter) -> Iterator[DocmostClient]:
    del api
    with DocmostClient(settings()) as instance:
        yield instance


pytestmark = pytest.mark.respx(assert_all_called=False)


def test_me_returns_the_current_user(client: DocmostClient, api: respx.MockRouter) -> None:
    api.post(f"{API}/users/me").mock(return_value=wrapped(fixture("users_me")))

    user = client.me()

    assert user.id == "0192b7a4-0000-7000-8000-000000000001"
    assert user.email == "bot@example.com"
    assert user.name == "Wiki Bot"
    assert user.role == "member"
    assert user.workspace_id == "0192b7a4-0000-7000-8000-0000000000aa"


def test_list_spaces_returns_a_page_of_spaces(client: DocmostClient, api: respx.MockRouter) -> None:
    route = api.post(f"{API}/spaces").mock(return_value=wrapped(fixture("spaces_list")))

    result = client.list_spaces(limit=2, cursor="abc", query="eng")

    assert body(route) == {"limit": 2, "cursor": "abc", "query": "eng"}
    assert [space.slug for space in result.items] == ["engineering", "ops"]
    first = result.items[0]
    assert first.id == SPACE_ID
    assert first.name == "Engineering"
    assert first.description == "Runbooks and design docs"
    assert first.role == "writer"
    assert result.has_next_page is True
    assert result.next_cursor == "Y3Vyc29yLTE"


def test_list_spaces_omits_unset_optional_fields(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    route = api.post(f"{API}/spaces").mock(return_value=wrapped(fixture("spaces_list")))

    client.list_spaces()

    assert body(route) == {"limit": 20}


@pytest.mark.parametrize("limit", [0, 101])
def test_page_size_outside_docmost_bounds_is_rejected_locally(
    client: DocmostClient, api: respx.MockRouter, limit: int
) -> None:
    route = api.post(f"{API}/spaces").mock(return_value=wrapped(fixture("spaces_list")))

    with pytest.raises(InvalidRequestError, match="limit"):
        client.list_spaces(limit=limit)

    assert route.call_count == 0


def test_get_space_accepts_a_slug(client: DocmostClient, api: respx.MockRouter) -> None:
    route = api.post(f"{API}/spaces/info").mock(return_value=wrapped(fixture("space_info")))

    space = client.get_space("engineering")

    assert body(route) == {"spaceId": "engineering"}
    assert space.id == SPACE_ID
    assert space.slug == "engineering"
    assert space.role == "writer"


def test_get_page_reads_markdown_by_default(client: DocmostClient, api: respx.MockRouter) -> None:
    route = api.post(f"{API}/pages/info").mock(return_value=wrapped(fixture("page_info_markdown")))

    page = client.get_page(PAGE_ID)

    assert body(route) == {"pageId": PAGE_ID, "format": "markdown"}
    assert page.id == PAGE_ID
    assert page.slug_id == "abc123xyz0"
    assert page.title == "Runbook"
    assert page.format == "markdown"
    assert page.content == "# Runbook\n\nRestart the worker pool.\n"
    assert page.space_id == SPACE_ID
    assert page.space is not None
    assert page.space.slug == "engineering"
    assert page.parent_page_id is None
    assert page.updated_at == datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
    assert page.is_locked is False
    assert page.can_edit is True


@pytest.mark.parametrize(
    ("fmt", "content"),
    [("html", "<h1>Runbook</h1>"), ("json", {"type": "doc", "content": []})],
)
def test_get_page_supports_every_docmost_format(
    client: DocmostClient, api: respx.MockRouter, fmt: str, content: object
) -> None:
    data = fixture("page_info_markdown") | {"content": content}
    route = api.post(f"{API}/pages/info").mock(return_value=wrapped(data))

    page = client.get_page(PAGE_ID, format=fmt)  # type: ignore[arg-type]

    assert body(route)["format"] == fmt
    assert page.format == fmt
    assert page.content == content


def test_get_page_rejects_unknown_formats(client: DocmostClient, api: respx.MockRouter) -> None:
    route = api.post(f"{API}/pages/info")

    with pytest.raises(InvalidRequestError, match="format"):
        client.get_page(PAGE_ID, format="pdf")  # type: ignore[arg-type]

    assert route.call_count == 0


def test_page_without_content_has_none(client: DocmostClient, api: respx.MockRouter) -> None:
    api.post(f"{API}/pages/info").mock(
        return_value=wrapped(fixture("page_info_markdown") | {"content": None})
    )

    assert client.get_page(PAGE_ID).content is None


def test_trashed_pages_are_reported_as_not_found(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    api.post(f"{API}/pages/info").mock(
        return_value=wrapped(fixture("page_info_markdown") | {"deletedAt": "2026-10-01T00:00:00Z"})
    )

    with pytest.raises(NotFoundError, match="trash"):
        client.get_page(PAGE_ID)


def test_list_children_of_a_page_by_uuid(client: DocmostClient, api: respx.MockRouter) -> None:
    route = api.post(f"{API}/pages/sidebar-pages").mock(
        return_value=wrapped(fixture("sidebar_pages"))
    )

    result = client.list_children(parent_page_id=PAGE_ID)

    assert body(route) == {"pageId": PAGE_ID, "limit": 20}
    child = result.items[0]
    assert child.id == "0192b7a4-0000-7000-8000-0000000000c2"
    assert child.slug_id == "def456uvw1"
    assert child.title == "Restart procedure"
    assert child.parent_page_id == PAGE_ID
    assert child.space_id == SPACE_ID
    assert child.has_children is True
    assert child.can_edit is True
    assert result.has_next_page is False
    assert result.next_cursor is None


def test_list_children_resolves_a_page_slug_to_its_uuid(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    info = api.post(f"{API}/pages/info").mock(return_value=wrapped(fixture("page_info_markdown")))
    sidebar = api.post(f"{API}/pages/sidebar-pages").mock(
        return_value=wrapped(fixture("sidebar_pages"))
    )

    client.list_children(parent_page_id="abc123xyz0")

    assert body(info)["pageId"] == "abc123xyz0"
    assert body(sidebar)["pageId"] == PAGE_ID


def test_list_root_pages_of_a_space_by_slug(client: DocmostClient, api: respx.MockRouter) -> None:
    api.post(f"{API}/spaces/info").mock(return_value=wrapped(fixture("space_info")))
    sidebar = api.post(f"{API}/pages/sidebar-pages").mock(
        return_value=wrapped(fixture("sidebar_pages"))
    )

    client.list_children(space="engineering", limit=5, cursor="c1")

    assert body(sidebar) == {"spaceId": SPACE_ID, "limit": 5, "cursor": "c1"}


def test_list_root_pages_by_space_uuid_skips_resolution(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    info = api.post(f"{API}/spaces/info")
    sidebar = api.post(f"{API}/pages/sidebar-pages").mock(
        return_value=wrapped(fixture("sidebar_pages"))
    )

    client.list_children(space=SPACE_ID)

    assert info.call_count == 0
    assert body(sidebar) == {"spaceId": SPACE_ID, "limit": 20}


def test_list_children_needs_a_space_or_parent(client: DocmostClient) -> None:
    with pytest.raises(InvalidRequestError, match="space or parent_page_id"):
        client.list_children()


def test_search_returns_hits(client: DocmostClient, api: respx.MockRouter) -> None:
    route = api.post(f"{API}/search").mock(return_value=wrapped(fixture("search")))

    hits = client.search("worker")

    assert body(route) == {"query": "worker", "limit": 10, "offset": 0}
    hit = hits[0]
    assert hit.id == PAGE_ID
    assert hit.slug_id == "abc123xyz0"
    assert hit.title == "Runbook"
    assert hit.space.id == SPACE_ID
    assert hit.space.slug == "engineering"
    assert hit.highlight == "... restart the <b>worker</b> pool ..."
    assert hit.rank == pytest.approx(0.0759)
    assert hit.updated_at == datetime(2026, 10, 16, 10, 0, tzinfo=UTC)


def test_search_within_a_space_slug_resolves_it(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    api.post(f"{API}/spaces/info").mock(return_value=wrapped(fixture("space_info")))
    route = api.post(f"{API}/search").mock(return_value=wrapped(fixture("search")))

    client.search("worker", space="engineering", limit=3, offset=6, title_only=True)

    assert body(route) == {
        "query": "worker",
        "limit": 3,
        "offset": 6,
        "spaceId": SPACE_ID,
        "titleOnly": True,
    }


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"query": "  "}, "query"),
        ({"query": "x", "limit": 0}, "limit"),
        ({"query": "x", "limit": 51}, "limit"),
        ({"query": "x", "offset": -1}, "offset"),
    ],
)
def test_search_validates_input_locally(
    client: DocmostClient, api: respx.MockRouter, kwargs: dict[str, Any], match: str
) -> None:
    route = api.post(f"{API}/search")

    with pytest.raises(InvalidRequestError, match=match):
        client.search(**kwargs)

    assert route.call_count == 0


def test_server_version_is_fetched_once(client: DocmostClient, api: respx.MockRouter) -> None:
    route = api.post(f"{API}/version").mock(return_value=wrapped(fixture("version")))

    assert client.server_version() == "0.96.0"
    assert client.server_version() == "0.96.0"
    assert route.call_count == 1


def test_server_version_is_none_when_docmost_cannot_tell(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    api.post(f"{API}/version").mock(
        return_value=httpx.Response(200, json={"success": True, "status": 200})
    )

    assert client.server_version() is None


def test_compatibility_of_a_supported_version(client: DocmostClient, api: respx.MockRouter) -> None:
    api.post(f"{API}/version").mock(return_value=wrapped(fixture("version")))

    report = client.check_compatibility()

    assert report.status == "supported"
    assert report.docmost_version == "0.96.0"


def test_compatibility_of_an_unknown_version_is_a_warning(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    api.post(f"{API}/version").mock(return_value=httpx.Response(200, json={"success": True}))

    report = client.check_compatibility()

    assert report.status == "unknown"
    assert report.docmost_version is None


def test_untested_version_is_refused(client: DocmostClient, api: respx.MockRouter) -> None:
    api.post(f"{API}/version").mock(return_value=wrapped({"currentVersion": "0.97.0"}))

    with pytest.raises(UnsupportedVersionError, match="DOCMOST_ALLOW_UNTESTED_VERSION") as exc:
        client.check_compatibility()

    assert exc.value.code == "UNSUPPORTED_VERSION"


def test_untested_version_can_be_explicitly_allowed(api: respx.MockRouter) -> None:
    api.post(f"{API}/version").mock(return_value=wrapped({"currentVersion": "0.97.0"}))

    with DocmostClient(settings(DOCMOST_ALLOW_UNTESTED_VERSION="1")) as client:
        report = client.check_compatibility()

    assert report.status == "untested"
    assert report.docmost_version == "0.97.0"


@pytest.mark.anyio
async def test_async_client_has_the_same_reads(api: respx.MockRouter) -> None:
    api.post(f"{API}/pages/info").mock(return_value=wrapped(fixture("page_info_markdown")))
    sidebar = api.post(f"{API}/pages/sidebar-pages").mock(
        return_value=wrapped(fixture("sidebar_pages"))
    )
    api.post(f"{API}/search").mock(return_value=wrapped(fixture("search")))
    api.post(f"{API}/spaces").mock(return_value=wrapped(fixture("spaces_list")))

    async with AsyncDocmostClient(settings()) as client:
        page = await client.get_page(PAGE_ID)
        children = await client.list_children(parent_page_id="abc123xyz0")
        hits = await client.search("worker")
        spaces = await client.list_spaces()

    assert page.title == "Runbook"
    assert body(sidebar)["pageId"] == PAGE_ID
    assert children.items[0].title == "Restart procedure"
    assert hits[0].title == "Runbook"
    assert spaces.items[0].slug == "engineering"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_unparseable_responses_never_echo_page_content(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    broken = fixture("page_info_markdown") | {"content": "TOP SECRET BODY", "updatedAt": "nope"}
    api.post(f"{API}/pages/info").mock(return_value=wrapped(broken))

    with pytest.raises(UpstreamError) as exc:
        client.get_page(PAGE_ID)

    assert "TOP SECRET BODY" not in str(exc.value)
    assert exc.value.__cause__ is None
