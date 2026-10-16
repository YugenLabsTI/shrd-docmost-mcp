"""Write operations: read-only default, allowlist, precheck, and content guards."""

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
    PermissionDeniedError,
    ReadOnlyError,
    SpaceNotAllowedError,
    StalePageError,
    UpstreamError,
)

BASE = "https://wiki.example.com"
API = f"{BASE}/api"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "v0_96_0"
ENG_ID = "0192b7a4-0000-7000-8000-0000000000b1"
OPS_ID = "0192b7a4-0000-7000-8000-0000000000b2"
PAGE_ID = "0192b7a4-0000-7000-8000-0000000000c1"
UPDATED_AT = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)


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
            "DOCMOST_READ_ONLY": "0",
            **extra,
        }
    )


def page(**overrides: Any) -> dict[str, Any]:
    return fixture("page_info_markdown") | overrides


def updated(content: Any = "# Runbook\n\nRestart the worker pool.\n\nNew line\n") -> Any:
    return page(content=content, updatedAt="2026-10-16T10:05:00.000Z")


def created() -> dict[str, Any]:
    data = page(id="0192b7a4-0000-7000-8000-0000000000c9", slugId="new0000001", title="New")
    for key in ("content", "space", "creator", "lastUpdatedBy", "contributors", "deletedBy"):
        data.pop(key)
    return data


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


# --- read-only ---------------------------------------------------------------


def test_writes_are_blocked_by_default_without_any_request(api: respx.MockRouter) -> None:
    default = DocmostSettings.from_env(
        {"DOCMOST_BASE_URL": BASE, "DOCMOST_EMAIL": "bot@example.com", "DOCMOST_PASSWORD": "pw"}
    )
    with DocmostClient(default) as client:
        with pytest.raises(ReadOnlyError, match="DOCMOST_READ_ONLY") as exc:
            client.update_page(PAGE_ID, content="x", operation="append")
        with pytest.raises(ReadOnlyError):
            client.create_page(space="engineering", title="New")

    assert exc.value.code == "READ_ONLY"
    assert all(call.request.url.path == "/api/auth/logout" for call in api.calls)


# --- create ------------------------------------------------------------------


def test_create_page_in_a_space_by_slug(client: DocmostClient, api: respx.MockRouter) -> None:
    route = api.post(f"{API}/pages/create").mock(return_value=wrapped(created()))

    result = client.create_page(space="engineering", title="New", content="# Hi\n")

    assert body(route) == {
        "spaceId": ENG_ID,
        "title": "New",
        "content": "# Hi\n",
        "format": "markdown",
    }
    assert result.id == "0192b7a4-0000-7000-8000-0000000000c9"
    assert result.title == "New"
    assert result.space_id == ENG_ID
    assert result.content is None


def test_create_page_under_a_parent_with_html(client: DocmostClient, api: respx.MockRouter) -> None:
    api.post(f"{API}/pages/info").mock(return_value=wrapped(page()))
    route = api.post(f"{API}/pages/create").mock(return_value=wrapped(created()))

    client.create_page(
        space=ENG_ID,
        title="Child",
        content="<p>Hi</p>",
        format="html",
        parent_page_id=PAGE_ID,
        icon="📄",
    )

    assert body(route) == {
        "spaceId": ENG_ID,
        "title": "Child",
        "icon": "📄",
        "parentPageId": PAGE_ID,
        "content": "<p>Hi</p>",
        "format": "html",
    }


def test_create_empty_page_sends_no_content(client: DocmostClient, api: respx.MockRouter) -> None:
    route = api.post(f"{API}/pages/create").mock(return_value=wrapped(created()))

    client.create_page(space=ENG_ID, title="Empty")

    assert body(route) == {"spaceId": ENG_ID, "title": "Empty"}


def test_create_in_a_disallowed_space_is_refused_before_writing(api: respx.MockRouter) -> None:
    api.post(f"{API}/spaces/info").mock(
        return_value=wrapped(fixture("space_info") | {"id": OPS_ID, "slug": "ops"})
    )
    route = api.post(f"{API}/pages/create")

    with (
        DocmostClient(settings(DOCMOST_ALLOWED_SPACES="engineering")) as client,
        pytest.raises(SpaceNotAllowedError),
    ):
        client.create_page(space="ops", title="New")

    assert route.call_count == 0


# --- update ------------------------------------------------------------------


def test_update_prechecks_then_writes_without_space_or_parent(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    info = api.post(f"{API}/pages/info").mock(return_value=wrapped(page()))
    update = api.post(f"{API}/pages/update").mock(return_value=wrapped(updated()))

    result = client.update_page(
        "abc123xyz0", content="New line\n", operation="append", expected_updated_at=UPDATED_AT
    )

    assert body(info) == {"pageId": "abc123xyz0", "format": "markdown"}
    assert body(update) == {
        "pageId": PAGE_ID,
        "content": "New line\n",
        "operation": "append",
        "format": "markdown",
    }
    assert result.updated_at == datetime(2026, 10, 16, 10, 5, tzinfo=UTC)
    assert result.content == "# Runbook\n\nRestart the worker pool.\n\nNew line\n"


def test_stale_page_is_refused_before_writing(client: DocmostClient, api: respx.MockRouter) -> None:
    api.post(f"{API}/pages/info").mock(return_value=wrapped(page()))
    update = api.post(f"{API}/pages/update")

    with pytest.raises(StalePageError, match="2026-10-16T10:00:00") as exc:
        client.update_page(
            PAGE_ID,
            content="x",
            operation="replace",
            expected_updated_at=datetime(2026, 10, 16, 9, 0, tzinfo=UTC),
        )

    assert exc.value.code == "STALE_PAGE"
    assert exc.value.current_updated_at == UPDATED_AT
    assert update.call_count == 0


def test_title_only_update_sends_title_and_format(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    api.post(f"{API}/pages/info").mock(return_value=wrapped(page()))
    update = api.post(f"{API}/pages/update").mock(
        return_value=wrapped(page(title="Renamed", updatedAt="2026-10-16T10:05:00.000Z"))
    )

    result = client.update_page(PAGE_ID, title="Renamed", format="html")

    assert body(update) == {"pageId": PAGE_ID, "title": "Renamed", "format": "html"}
    assert result.title == "Renamed"
    assert result.format == "html"


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"content": "x"}, "operation"),
        ({"operation": "append"}, "content"),
        ({}, "Nothing to update"),
        ({"content": "", "operation": "append"}, "empty"),
        ({"content": {"type": "doc"}, "operation": "append"}, "string"),
        ({"content": "<p>x</p>", "operation": "append", "format": "json"}, "object"),
        ({"content": "x", "operation": "merge"}, "operation"),
    ],
)
def test_invalid_updates_are_rejected_locally(
    client: DocmostClient, api: respx.MockRouter, kwargs: dict[str, Any], match: str
) -> None:
    info = api.post(f"{API}/pages/info")

    with pytest.raises(InvalidRequestError, match=match):
        client.update_page(PAGE_ID, **kwargs)

    assert info.call_count == 0


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
    api.post(f"{API}/pages/info").mock(return_value=wrapped(page(**overrides)))
    update = api.post(f"{API}/pages/update")

    with (
        DocmostClient(settings(DOCMOST_ALLOWED_SPACES="engineering")) as client,
        pytest.raises(error or SpaceNotAllowedError),
    ):
        client.update_page(PAGE_ID, content="x", operation="append")

    assert update.call_count == 0


def test_silently_dropped_content_changes_are_detected(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    api.post(f"{API}/pages/info").mock(return_value=wrapped(page()))
    api.post(f"{API}/pages/update").mock(
        return_value=wrapped(page(updatedAt="2026-10-16T10:05:00.000Z"))
    )

    with pytest.raises(UpstreamError, match="COLLAB_DISABLE_REDIS"):
        client.update_page(PAGE_ID, content="New line\n", operation="append")


def test_replacing_with_identical_content_is_not_an_error(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    current = page()["content"]
    api.post(f"{API}/pages/info").mock(return_value=wrapped(page()))
    api.post(f"{API}/pages/update").mock(return_value=wrapped(page()))

    result = client.update_page(PAGE_ID, content=current, operation="replace")

    assert result.content == current


# --- content guards ----------------------------------------------------------


def test_content_over_the_size_limit_is_rejected(api: respx.MockRouter) -> None:
    info = api.post(f"{API}/pages/info")

    with DocmostClient(settings(DOCMOST_MAX_CONTENT_BYTES="10")) as client:
        with pytest.raises(InvalidRequestError, match="DOCMOST_MAX_CONTENT_BYTES"):
            client.update_page(PAGE_ID, content="ñ" * 6, operation="append")
        with pytest.raises(InvalidRequestError, match="DOCMOST_MAX_CONTENT_BYTES"):
            client.update_page(
                PAGE_ID, content={"type": "doc", "content": []}, operation="append", format="json"
            )

    assert info.call_count == 0


def test_markdown_that_docmost_would_strip_as_front_matter_is_rejected(
    client: DocmostClient,
) -> None:
    with pytest.raises(InvalidRequestError, match="front matter"):
        client.update_page(PAGE_ID, content="\n---\nIntro\n---\nBody", operation="replace")


def test_markdown_starting_with_a_lone_rule_is_allowed(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    api.post(f"{API}/pages/info").mock(return_value=wrapped(page()))
    api.post(f"{API}/pages/update").mock(return_value=wrapped(updated("---\nBody\n")))

    client.update_page(PAGE_ID, content="---\nBody\n", operation="replace")


@pytest.mark.parametrize(
    ("content", "fmt"),
    [
        ('<p>Hi <span data-type="mention" data-id="u1">@Ana</span></p>', "html"),
        ("Hi <span data-type='mention' data-id='u1'>@Ana</span>", "markdown"),
        (
            {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "mention", "attrs": {"id": "u1"}}]}
                ],
            },
            "json",
        ),
    ],
)
def test_mentions_are_rejected_because_they_notify_users(
    client: DocmostClient, content: Any, fmt: str
) -> None:
    with pytest.raises(InvalidRequestError, match="mention"):
        client.create_page(space=ENG_ID, title="x", content=content, format=fmt)  # type: ignore[arg-type]


# --- async parity ------------------------------------------------------------


@pytest.mark.anyio
async def test_async_client_writes(api: respx.MockRouter) -> None:
    api.post(f"{API}/pages/info").mock(return_value=wrapped(page()))
    update = api.post(f"{API}/pages/update").mock(return_value=wrapped(updated()))
    create = api.post(f"{API}/pages/create").mock(return_value=wrapped(created()))

    async with AsyncDocmostClient(settings()) as client:
        await client.update_page(PAGE_ID, content="New line\n", operation="append")
        await client.create_page(space="engineering", title="New")

    assert body(update)["operation"] == "append"
    assert body(create) == {"spaceId": ENG_ID, "title": "New"}


@pytest.mark.anyio
async def test_async_client_is_read_only_by_default(api: respx.MockRouter) -> None:
    default = DocmostSettings.from_env(
        {"DOCMOST_BASE_URL": BASE, "DOCMOST_EMAIL": "bot@example.com", "DOCMOST_PASSWORD": "pw"}
    )
    async with AsyncDocmostClient(default) as client:
        with pytest.raises(ReadOnlyError):
            await client.create_page(space=ENG_ID, title="New")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# --- verifier regressions (T6) -------------------------------------------------


def test_replace_that_docmost_normalizes_is_not_reported_as_dropped(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    current = page()["content"]
    api.post(f"{API}/pages/info").mock(return_value=wrapped(page()))
    api.post(f"{API}/pages/update").mock(
        return_value=wrapped(page(updatedAt="2026-10-16T10:05:00.000Z"))
    )

    result = client.update_page(PAGE_ID, content=current + "\n", operation="replace")

    assert result.content == current


@pytest.mark.parametrize(
    ("content", "fmt"),
    [
        ('<span data-type="&#109;ention" data-id="u1">@Bob</span>', "html"),
        ('<span data-type="&#x6D;ention" data-id="u1">@Bob</span>', "html"),
        ('Hi <span data-type="m&#101;ntion" data-id="u1">@Bob</span>', "markdown"),
        ("<span DATA-TYPE=MENTION data-id=u1>@Bob</span>", "html"),
    ],
)
def test_entity_encoded_mentions_are_rejected(
    client: DocmostClient, content: str, fmt: str
) -> None:
    with pytest.raises(InvalidRequestError, match="mention"):
        client.create_page(space=ENG_ID, title="x", content=content, format=fmt)  # type: ignore[arg-type]


def test_front_matter_after_a_byte_order_mark_is_rejected(client: DocmostClient) -> None:
    with pytest.raises(InvalidRequestError, match="front matter"):
        client.update_page(PAGE_ID, content="﻿---\ntitle: x\n---\nbody", operation="replace")


def test_size_limit_counts_the_encoded_request_content(api: respx.MockRouter) -> None:
    with (
        DocmostClient(settings(DOCMOST_MAX_CONTENT_BYTES="11")) as client,
        pytest.raises(InvalidRequestError, match="DOCMOST_MAX_CONTENT_BYTES"),
    ):
        client.update_page(PAGE_ID, content='"""""', operation="append")


def test_naive_expected_updated_at_is_rejected(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    info = api.post(f"{API}/pages/info")

    with pytest.raises(InvalidRequestError, match="timezone"):
        client.update_page(PAGE_ID, title="x", expected_updated_at=datetime(2026, 10, 16, 10, 0))

    assert info.call_count == 0


def test_unserializable_json_content_is_a_typed_error(client: DocmostClient) -> None:
    with pytest.raises(InvalidRequestError, match="JSON"):
        client.update_page(
            PAGE_ID, content={"type": "doc", "x": {1, 2}}, operation="append", format="json"
        )


def test_create_under_a_parent_from_another_space_is_refused(api: respx.MockRouter) -> None:
    other = page(spaceId=OPS_ID, space={"id": OPS_ID, "name": "Ops", "slug": "ops"})
    api.post(f"{API}/pages/info").mock(return_value=wrapped(other))
    create = api.post(f"{API}/pages/create")

    with (
        DocmostClient(settings(DOCMOST_ALLOWED_SPACES="engineering")) as client,
        pytest.raises(SpaceNotAllowedError),
    ):
        client.create_page(space="engineering", title="x", parent_page_id=PAGE_ID)

    assert create.call_count == 0


def test_create_under_a_parent_in_a_different_allowed_space_is_invalid(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    other = page(spaceId=OPS_ID, space={"id": OPS_ID, "name": "Ops", "slug": "ops"})
    api.post(f"{API}/pages/info").mock(return_value=wrapped(other))
    create = api.post(f"{API}/pages/create")

    with pytest.raises(InvalidRequestError, match="parent"):
        client.create_page(space="engineering", title="x", parent_page_id=PAGE_ID)

    assert create.call_count == 0
