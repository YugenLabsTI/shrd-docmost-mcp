"""move_page: reparent and place a page among its siblings, behind DOCMOST_ALLOW_MOVE."""

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
    MoveDisabledError,
    NotFoundError,
    PermissionDeniedError,
    ReadOnlyError,
    SpaceNotAllowedError,
    StalePageError,
)

BASE = "https://wiki.example.com"
API = f"{BASE}/api"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "v0_96_0"
ENG = "0192b7a4-0000-7000-8000-0000000000b1"
OPS = "0192b7a4-0000-7000-8000-0000000000b2"
PAGE = "0192b7a4-0000-7000-8000-0000000000c1"
GUIDE = "0192b7a4-0000-7000-8000-0000000000d1"
UPDATED_AT = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def wrapped(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "success": True, "status": 200})


def page(page_id: str = PAGE, **overrides: Any) -> dict[str, Any]:
    return fixture("page_info_markdown") | {"id": page_id} | overrides


def child(page_id: str, position: str, title: str = "Child") -> dict[str, Any]:
    return {
        "id": page_id,
        "slugId": f"{page_id[-4:]}slug00",
        "title": title,
        "position": position,
        "parentPageId": GUIDE,
        "spaceId": ENG,
        "hasChildren": False,
        "canEdit": True,
    }


def listing(*items: dict[str, Any], next_cursor: str | None = None) -> httpx.Response:
    meta = {"limit": 100, "hasNextPage": next_cursor is not None, "nextCursor": next_cursor}
    return wrapped({"items": list(items), "meta": meta})


def body(route: respx.Route, index: int = -1) -> Any:
    return json.loads(route.calls[index].request.read())


def settings(**extra: str) -> DocmostSettings:
    return DocmostSettings.from_env(
        {
            "DOCMOST_BASE_URL": BASE,
            "DOCMOST_EMAIL": "bot@example.com",
            "DOCMOST_PASSWORD": "pw",
            "DOCMOST_READ_ONLY": "0",
            "DOCMOST_ALLOW_MOVE": "1",
        }
        | extra
    )


@pytest.fixture
def api(respx_mock: respx.MockRouter) -> respx.MockRouter:
    respx_mock.post(f"{API}/auth/login").mock(
        return_value=httpx.Response(200, headers={"set-cookie": "authToken=t; Path=/"}, json={})
    )
    respx_mock.post(f"{API}/auth/logout").mock(return_value=httpx.Response(200, json={}))

    def info(request: httpx.Request) -> httpx.Response:
        wanted = json.loads(request.read())["pageId"]
        if wanted == GUIDE:
            return wrapped(page(GUIDE, slugId="guide00001", title="Guide"))
        return wrapped(page())

    respx_mock.post(f"{API}/pages/info", name="info").mock(side_effect=info)
    respx_mock.post(f"{API}/pages/sidebar-pages", name="children").mock(
        return_value=listing(child("c-1", "a07gp"), child("c-2", "a0AHy"))
    )
    respx_mock.post(f"{API}/pages/move", name="move").mock(
        return_value=httpx.Response(200, json={"success": True, "status": 200})
    )
    return respx_mock


@pytest.fixture
def client(api: respx.MockRouter) -> Iterator[DocmostClient]:
    del api
    with DocmostClient(settings()) as instance:
        yield instance


pytestmark = pytest.mark.respx(assert_all_called=False)


def move(client: DocmostClient, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "parent_page_id": GUIDE,
        "expected_updated_at": UPDATED_AT,
    } | overrides
    return client.move_page("abc123xyz0", **arguments)


def test_moves_under_a_parent_after_its_last_child(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    moved = move(client)

    assert body(api.routes["children"]) == {"pageId": GUIDE, "limit": 100}
    assert body(api.routes["move"]) == {"pageId": PAGE, "position": "a1000", "parentPageId": GUIDE}
    assert moved.id == PAGE
    # The page is read again after the move to return its new state.
    assert api.routes["info"].call_count == 3


def test_moves_to_the_space_root_sending_a_null_parent(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    move(client, parent_page_id=None)

    assert body(api.routes["children"]) == {"spaceId": ENG, "limit": 100}
    assert body(api.routes["move"])["parentPageId"] is None


def test_placement_after_a_sibling_lands_between_it_and_the_next(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    move(client, after_page_id="c-1")

    position = body(api.routes["move"])["position"]
    assert "a07gp" < position < "a0AHy"
    assert 5 <= len(position) <= 12


def test_placement_at_the_start(client: DocmostClient, api: respx.MockRouter) -> None:
    move(client, placement="start")

    position = body(api.routes["move"])["position"]
    assert position < "a07gp"
    assert 5 <= len(position) <= 12


def test_the_moved_page_is_not_its_own_neighbour(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    api.routes["children"].mock(return_value=listing(child("c-1", "a07gp"), child(PAGE, "a0AHy")))

    move(client)

    assert body(api.routes["move"])["position"] == "a1000"


def test_siblings_are_read_across_pages(client: DocmostClient, api: respx.MockRouter) -> None:
    api.routes["children"].side_effect = [
        listing(child("c-1", "a07gp"), next_cursor="n2"),
        listing(child("c-2", "a3xyz")),
    ]

    move(client)

    assert body(api.routes["children"], 1)["cursor"] == "n2"
    assert body(api.routes["move"])["position"] == "a4000"


@pytest.mark.parametrize(
    ("overrides", "error", "match"),
    [
        ({"after_page_id": "c-9"}, InvalidRequestError, "after_page_id"),
        ({"after_page_id": "c-1", "placement": "start"}, InvalidRequestError, "after_page_id"),
        ({"placement": "middle"}, InvalidRequestError, "placement"),
        ({"parent_page_id": "abc123xyz0"}, InvalidRequestError, "own parent"),
        ({"expected_updated_at": UPDATED_AT - timedelta(minutes=1)}, StalePageError, "changed"),
        ({"expected_updated_at": datetime(2026, 10, 16, 10, 0)}, InvalidRequestError, "timezone"),
    ],
)
def test_invalid_moves_send_nothing(
    client: DocmostClient,
    api: respx.MockRouter,
    overrides: dict[str, Any],
    error: type[Exception],
    match: str,
) -> None:
    with pytest.raises(error, match=match):
        move(client, **overrides)

    assert api.routes["move"].call_count == 0


@pytest.mark.parametrize(
    ("page_overrides", "parent_overrides", "error"),
    [
        ({"isLocked": True}, {}, PermissionDeniedError),
        ({"permissions": {"canEdit": False, "hasRestriction": True}}, {}, PermissionDeniedError),
        ({"deletedAt": "2026-10-01T00:00:00.000Z"}, {}, NotFoundError),
        ({}, {"permissions": {"canEdit": False, "hasRestriction": True}}, PermissionDeniedError),
        ({}, {"spaceId": OPS, "space": {"id": OPS, "name": "Ops", "slug": "ops"}}, None),
    ],
)
def test_pages_that_cannot_move_there_are_refused_before_moving(
    api: respx.MockRouter,
    page_overrides: dict[str, Any],
    parent_overrides: dict[str, Any],
    error: type[Exception] | None,
) -> None:
    def info(request: httpx.Request) -> httpx.Response:
        if json.loads(request.read())["pageId"] == GUIDE:
            return wrapped(page(GUIDE, **parent_overrides))
        return wrapped(page(**page_overrides))

    api.routes["info"].side_effect = info

    with DocmostClient(settings()) as client:
        if error is None:
            # A parent in another space: allowed by the allowlist but not by Docmost.
            with pytest.raises(InvalidRequestError, match="same space"):
                move(client)
        else:
            with pytest.raises(error):
                move(client)

    assert api.routes["move"].call_count == 0


def test_a_parent_outside_the_allowlist_is_refused(api: respx.MockRouter) -> None:
    def info(request: httpx.Request) -> httpx.Response:
        if json.loads(request.read())["pageId"] == GUIDE:
            return wrapped(
                page(GUIDE, spaceId=OPS, space={"id": OPS, "name": "Ops", "slug": "ops"})
            )
        return wrapped(page())

    api.routes["info"].side_effect = info
    with (
        DocmostClient(settings(DOCMOST_ALLOWED_SPACES="engineering")) as client,
        pytest.raises(SpaceNotAllowedError),
    ):
        move(client)

    assert api.routes["move"].call_count == 0


@pytest.mark.parametrize(
    ("extra", "error"),
    [({"DOCMOST_READ_ONLY": "1"}, ReadOnlyError), ({"DOCMOST_ALLOW_MOVE": "0"}, MoveDisabledError)],
)
def test_moves_need_writes_and_the_move_flag(
    api: respx.MockRouter, extra: dict[str, str], error: type[Exception]
) -> None:
    with DocmostClient(settings(**extra)) as client, pytest.raises(error):
        move(client)

    assert api.routes["info"].call_count == 0
    assert api.routes["move"].call_count == 0


def test_the_move_flag_is_off_by_default() -> None:
    env = {"DOCMOST_BASE_URL": BASE, "DOCMOST_EMAIL": "e@example.com", "DOCMOST_PASSWORD": "p"}

    assert DocmostSettings.from_env(env).allow_move is False


def test_pages_expose_their_position(client: DocmostClient) -> None:
    assert client.get_page("abc123xyz0").position == "a0"
    children = client.list_children(parent_page_id=GUIDE)
    assert [c.position for c in children.items] == ["a07gp", "a0AHy"]


@pytest.mark.anyio
async def test_async_client_moves_pages(api: respx.MockRouter) -> None:
    async with AsyncDocmostClient(settings()) as client:
        await client.move_page(
            "abc123xyz0", parent_page_id=GUIDE, after_page_id=None, expected_updated_at=UPDATED_AT
        )

    assert body(api.routes["move"])["parentPageId"] == GUIDE


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
