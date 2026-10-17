"""Writes keep mentions already on the page but never add new ones (they notify people)."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from docmost_client import DocmostClient, DocmostSettings, InvalidRequestError, _ops

BASE = "https://wiki.example.com"
API = f"{BASE}/api"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "v0_96_0"
PAGE_ID = "0192b7a4-0000-7000-8000-0000000000c1"
ENG_ID = "0192b7a4-0000-7000-8000-0000000000b1"
ANA = "0192b7a4-0000-7000-8000-00000000a001"
BO = "0192b7a4-0000-7000-8000-00000000a002"
UPDATED_AT = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)


def mention_html(user: str, label: str = "Ana", node: str = "m1") -> str:
    return (
        f'<span data-type="mention" data-id="{node}" data-label="{label}" '
        f'data-entity-type="user" data-entity-id="{user}">@{label}</span>'
    )


def mention_json(user: str, label: str = "Ana") -> dict[str, Any]:
    return {
        "type": "mention",
        "attrs": {"id": "m1", "label": label, "entityType": "user", "entityId": user},
    }


def doc(*inline: dict[str, Any]) -> dict[str, Any]:
    paragraph = {"type": "paragraph", "content": [{"type": "text", "text": "Ask "}, *inline]}
    return {"type": "doc", "content": [paragraph]}


HTML_PAGE = (
    '<h2 data-id="install" id="install">Install</h2>'
    f"<p>Ask {mention_html(ANA)}.</p>"
    '<h2 data-id="configure" id="configure">Configure</h2><p>Old body.</p>'
)


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def wrapped(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "success": True, "status": 200})


def page(content: Any) -> dict[str, Any]:
    return fixture("page_info_markdown") | {"content": content}


def body(route: respx.Route, index: int = -1) -> Any:
    return json.loads(route.calls[index].request.read())


@pytest.fixture(autouse=True)
def quiet_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_ops, "_utcnow", lambda: UPDATED_AT + timedelta(minutes=10))


@pytest.fixture
def api(respx_mock: respx.MockRouter) -> respx.MockRouter:
    respx_mock.post(f"{API}/auth/login").mock(
        return_value=httpx.Response(200, headers={"set-cookie": "authToken=t; Path=/"}, json={})
    )
    respx_mock.post(f"{API}/auth/logout").mock(return_value=httpx.Response(200, json={}))
    respx_mock.post(f"{API}/pages/update", name="update").mock(
        return_value=wrapped(page("<p>stored</p>") | {"updatedAt": "2026-10-16T10:20:00.000Z"})
    )
    return respx_mock


def serve(api: respx.MockRouter, by_format: dict[str, Any]) -> respx.Route:
    """Answer pages/info with the page content in the requested format."""

    def respond(request: httpx.Request) -> httpx.Response:
        return wrapped(page(by_format[json.loads(request.read())["format"]]))

    return api.post(f"{API}/pages/info", name="info").mock(side_effect=respond)


@pytest.fixture
def client(api: respx.MockRouter) -> Iterator[DocmostClient]:
    del api
    settings = DocmostSettings.from_env(
        {
            "DOCMOST_BASE_URL": BASE,
            "DOCMOST_EMAIL": "bot@example.com",
            "DOCMOST_PASSWORD": "pw",
            "DOCMOST_READ_ONLY": "0",
        }
    )
    with DocmostClient(settings) as instance:
        yield instance


pytestmark = pytest.mark.respx(assert_all_called=False)


# --- update_page ---------------------------------------------------------------


def test_an_html_round_trip_keeps_existing_mentions(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    serve(api, {"html": HTML_PAGE})
    content = HTML_PAGE.replace("Old body.", "New body.")

    client.update_page(PAGE_ID, content=content, operation="replace", format="html")

    assert body(api.routes["update"])["content"] == content
    assert api.routes["info"].call_count == 1


def test_a_json_round_trip_keeps_existing_mentions(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    serve(api, {"json": doc(mention_json(ANA))})
    content = doc(mention_json(ANA, label="Ana M."), {"type": "text", "text": " today"})

    client.update_page(PAGE_ID, content=content, operation="replace", format="json")

    assert body(api.routes["update"])["content"] == content


def test_markdown_mentions_are_checked_against_the_page_as_json(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    serve(api, {"markdown": "Ask @Ana.", "json": doc(mention_json(ANA))})

    client.update_page(
        PAGE_ID, content=f"Ask {mention_html(ANA)} again.", operation="append", format="markdown"
    )

    assert [body(api.routes["info"], i)["format"] for i in range(2)] == ["markdown", "json"]
    assert api.routes["update"].call_count == 1


@pytest.mark.parametrize(
    ("content", "fmt"),
    [
        (HTML_PAGE + f"<p>{mention_html(BO, 'Bo', 'm2')}</p>", "html"),
        (HTML_PAGE.replace(ANA, BO), "html"),
        (doc(mention_json(BO, "Bo")), "json"),
        (f"Ask {mention_html(BO, 'Bo')}", "markdown"),
        # Docmost decodes entities before parsing, so this is mention markup the
        # client cannot match to a mention on the page.
        (HTML_PAGE + "<p>&lt;span data-type=mention&gt;@Bo&lt;/span&gt;</p>", "html"),
        # A mention without an entity id cannot be matched either.
        (HTML_PAGE + '<p><span data-type="mention" data-id="m1">@Ana</span></p>', "html"),
        # Docmost keeps the first of duplicated attributes, Python's parser the last.
        (
            HTML_PAGE + '<p><span data-type="mention" data-id="m2" data-entity-type="user" '
            f'data-entity-id="{BO}" data-entity-id="{ANA}">@x</span></p>',
            "html",
        ),
        (
            '<p><span data-type="mention" data-entity-type="user" '
            f'data-entity-id="{BO}" data-entity-id="{ANA}">@x</span></p>',
            "markdown",
        ),
        # Docmost finds mentions at any depth, including inside another mention.
        (doc(mention_json(ANA) | {"content": [mention_json(BO, "Bo")]}), "json"),
    ],
)
def test_new_mentions_are_refused_before_writing(
    client: DocmostClient, api: respx.MockRouter, content: Any, fmt: str
) -> None:
    serve(api, {"html": HTML_PAGE, "json": doc(mention_json(ANA)), "markdown": "Ask @Ana."})

    with pytest.raises(InvalidRequestError, match="not already on the page"):
        client.update_page(PAGE_ID, content=content, operation="replace", format=fmt)  # type: ignore[arg-type]

    assert api.routes["update"].call_count == 0


def test_creating_a_page_with_mentions_is_still_refused(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    create = api.post(f"{API}/pages/create")

    with pytest.raises(InvalidRequestError, match="mention"):
        client.create_page(space=ENG_ID, title="x", content=f"<p>{mention_html(ANA)}</p>")

    assert create.call_count == 0


# --- edit_section --------------------------------------------------------------


def test_a_section_edit_may_keep_a_mention_already_on_the_page(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    serve(api, {"html": HTML_PAGE})

    client.edit_section(
        PAGE_ID,
        heading_id="install",
        operation="replace",
        content=f"<p>Ask {mention_html(ANA)} first.</p>",
        expected_updated_at=UPDATED_AT,
    )

    assert f"Ask {mention_html(ANA)} first." in body(api.routes["update"])["content"]


def test_a_section_edit_may_not_add_a_new_mention(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    serve(api, {"html": HTML_PAGE})

    with pytest.raises(InvalidRequestError, match="not already on the page"):
        client.edit_section(
            PAGE_ID,
            heading_id="configure",
            operation="append",
            content=f"<p>{mention_html(BO, 'Bo')}</p>",
            expected_updated_at=UPDATED_AT,
        )

    assert api.routes["update"].call_count == 0


def test_page_mentions_count_only_the_first_node_with_each_id(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    # Docmost builds the "already mentioned" list keeping the first node per node id, so
    # BO (second node with id m1) is not on the page as far as notifications go.
    duplicated = doc(mention_json(ANA), mention_json(BO, "Bo"))
    serve(api, {"json": duplicated})
    fresh = mention_json(BO, "Bo") | {"attrs": mention_json(BO, "Bo")["attrs"] | {"id": "m9"}}

    with pytest.raises(InvalidRequestError, match="not already on the page"):
        client.update_page(PAGE_ID, content=doc(fresh), operation="replace", format="json")

    assert api.routes["update"].call_count == 0


def test_page_mentions_without_a_node_id_do_not_count(
    client: DocmostClient, api: respx.MockRouter
) -> None:
    # Docmost ignores mention nodes without an id when listing who was mentioned before.
    id_less = {"type": "mention", "attrs": {"entityType": "user", "entityId": BO}}
    serve(api, {"json": doc(id_less)})

    with pytest.raises(InvalidRequestError, match="not already on the page"):
        client.update_page(
            PAGE_ID, content=doc(mention_json(BO, "Bo")), operation="replace", format="json"
        )

    assert api.routes["update"].call_count == 0
