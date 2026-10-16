"""Page comments: reading is always allowed; adding requires DOCMOST_ALLOW_COMMENTS."""

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
    CommentsDisabledError,
    DocmostClient,
    DocmostSettings,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    SpaceNotAllowedError,
)

BASE = "https://wiki.example.com"
API = f"{BASE}/api"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "v0_96_0"
PAGE_ID = "0192b7a4-0000-7000-8000-0000000000c1"
OPS_ID = "0192b7a4-0000-7000-8000-0000000000b2"
PARENT_ID = "0192b7a4-0000-7000-8000-0000000000e1"


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
    respx_mock.post(f"{API}/pages/info", name="page").mock(
        return_value=wrapped(fixture("page_info_markdown"))
    )
    return respx_mock


@pytest.fixture
def commenter(api: respx.MockRouter) -> Iterator[DocmostClient]:
    del api
    with DocmostClient(settings(DOCMOST_ALLOW_COMMENTS="1")) as client:
        yield client


pytestmark = pytest.mark.respx(assert_all_called=False)


# --- reading -------------------------------------------------------------------


def test_comments_are_listed_as_plain_text(api: respx.MockRouter) -> None:
    route = api.post(f"{API}/comments").mock(return_value=wrapped(fixture("comments_list")))

    with DocmostClient(settings()) as client:  # read-only, comments disabled: still readable
        result = client.list_comments("abc123xyz0")

    assert body(route) == {"pageId": PAGE_ID, "limit": 20}
    first, reply = result.items
    assert first.id == "0192b7a4-0000-7000-8000-0000000000e1"
    assert first.page_id == PAGE_ID
    assert first.parent_comment_id is None
    assert first.type == "page"
    assert first.text == "Should we drain first?\ncc @Ana\nthanks"
    assert first.creator_name == "Ana"
    assert first.created_at == datetime(2026, 10, 16, 11, 0, tzinfo=UTC)
    assert first.resolved_at is None
    assert reply.parent_comment_id == first.id
    assert reply.text == "Yes."
    assert reply.resolved_at == datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    assert result.has_next_page is False


def test_deleted_comments_are_not_returned(api: respx.MockRouter) -> None:
    api.post(f"{API}/comments").mock(return_value=wrapped(fixture("comments_list")))

    with DocmostClient(settings()) as client:
        ids = [comment.id for comment in client.list_comments(PAGE_ID).items]

    assert "0192b7a4-0000-7000-8000-0000000000e3" not in ids


def test_comments_of_a_disallowed_page_are_refused_before_listing(api: respx.MockRouter) -> None:
    api.routes["page"].mock(
        return_value=wrapped(
            fixture("page_info_markdown")
            | {"spaceId": OPS_ID, "space": {"id": OPS_ID, "name": "Ops", "slug": "ops"}}
        )
    )
    route = api.post(f"{API}/comments")

    with (
        DocmostClient(settings(DOCMOST_ALLOWED_SPACES="engineering")) as client,
        pytest.raises(SpaceNotAllowedError),
    ):
        client.list_comments(PAGE_ID)

    assert route.call_count == 0


def test_comments_of_a_trashed_page_are_not_found(api: respx.MockRouter) -> None:
    api.routes["page"].mock(
        return_value=wrapped(fixture("page_info_markdown") | {"deletedAt": "2026-10-01T00:00:00Z"})
    )

    with DocmostClient(settings()) as client, pytest.raises(NotFoundError):
        client.list_comments(PAGE_ID)


# --- adding --------------------------------------------------------------------


@pytest.mark.parametrize("read_only", ["1", "0"])
def test_adding_comments_is_disabled_by_default_in_both_modes(
    api: respx.MockRouter, read_only: str
) -> None:
    with (
        DocmostClient(settings(DOCMOST_READ_ONLY=read_only)) as client,
        pytest.raises(CommentsDisabledError, match="DOCMOST_ALLOW_COMMENTS") as exc,
    ):
        client.create_comment(PAGE_ID, "hello")

    assert exc.value.code == "COMMENTS_DISABLED"
    assert all(call.request.url.path == "/api/auth/logout" for call in api.calls)


def test_a_read_only_account_can_comment_when_allowed(
    commenter: DocmostClient, api: respx.MockRouter
) -> None:
    route = api.post(f"{API}/comments/create").mock(return_value=wrapped(fixture("comment_create")))

    comment = commenter.create_comment("abc123xyz0", "Looks good.\n\nSecond line")

    sent = body(route)
    assert sent["pageId"] == PAGE_ID
    assert sent["type"] == "page"
    assert "parentCommentId" not in sent
    assert json.loads(sent["content"]) == {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Looks good."}]},
            {"type": "paragraph"},
            {"type": "paragraph", "content": [{"type": "text", "text": "Second line"}]},
        ],
    }
    assert comment.id == "0192b7a4-0000-7000-8000-0000000000e9"
    assert comment.text == "Looks good."


def test_replies_reference_their_parent(commenter: DocmostClient, api: respx.MockRouter) -> None:
    route = api.post(f"{API}/comments/create").mock(return_value=wrapped(fixture("comment_create")))

    commenter.create_comment(PAGE_ID, "Agreed", parent_comment_id=PARENT_ID)

    assert body(route)["parentCommentId"] == PARENT_ID


def test_text_cannot_smuggle_mentions(commenter: DocmostClient, api: respx.MockRouter) -> None:
    route = api.post(f"{API}/comments/create").mock(return_value=wrapped(fixture("comment_create")))
    text = '<span data-type="mention" data-id="u1">@Ana</span>'

    commenter.create_comment(PAGE_ID, text)

    nodes = json.loads(body(route)["content"])["content"][0]["content"]
    assert nodes == [{"type": "text", "text": text}]


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"text": "   "}, "empty"),
        ({"text": "x", "parent_comment_id": "not-a-uuid"}, "parent_comment_id"),
    ],
)
def test_invalid_comments_are_rejected_locally(
    commenter: DocmostClient, api: respx.MockRouter, kwargs: dict[str, str], match: str
) -> None:
    with pytest.raises(InvalidRequestError, match=match):
        commenter.create_comment(PAGE_ID, **kwargs)

    assert api.routes["page"].call_count == 0


def test_comment_size_is_capped(api: respx.MockRouter) -> None:
    with (
        DocmostClient(settings(DOCMOST_ALLOW_COMMENTS="1", DOCMOST_MAX_CONTENT_BYTES="50")) as c,
        pytest.raises(InvalidRequestError, match="DOCMOST_MAX_CONTENT_BYTES"),
    ):
        c.create_comment(PAGE_ID, "x" * 60)


def test_permission_errors_explain_viewer_comments(
    commenter: DocmostClient, api: respx.MockRouter
) -> None:
    api.post(f"{API}/comments/create").mock(
        return_value=httpx.Response(403, json={"message": "Forbidden", "statusCode": 403})
    )

    with pytest.raises(PermissionDeniedError, match="edit access"):
        commenter.create_comment(PAGE_ID, "hello")


def test_comments_on_disallowed_pages_are_refused_before_writing(api: respx.MockRouter) -> None:
    api.routes["page"].mock(
        return_value=wrapped(
            fixture("page_info_markdown")
            | {"spaceId": OPS_ID, "space": {"id": OPS_ID, "name": "Ops", "slug": "ops"}}
        )
    )
    route = api.post(f"{API}/comments/create")

    with (
        DocmostClient(
            settings(DOCMOST_ALLOW_COMMENTS="1", DOCMOST_ALLOWED_SPACES="engineering")
        ) as client,
        pytest.raises(SpaceNotAllowedError),
    ):
        client.create_comment(PAGE_ID, "hello")

    assert route.call_count == 0


@pytest.mark.anyio
async def test_async_client_reads_and_adds_comments(api: respx.MockRouter) -> None:
    api.post(f"{API}/comments").mock(return_value=wrapped(fixture("comments_list")))
    api.post(f"{API}/comments/create").mock(return_value=wrapped(fixture("comment_create")))

    async with AsyncDocmostClient(settings(DOCMOST_ALLOW_COMMENTS="1")) as client:
        listed = await client.list_comments(PAGE_ID)
        added = await client.create_comment(PAGE_ID, "Looks good.")

    assert len(listed.items) == 2
    assert added.text == "Looks good."


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
