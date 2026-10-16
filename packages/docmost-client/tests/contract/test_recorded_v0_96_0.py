"""Contract tests against responses recorded from a real Docmost 0.96.0.

Fixtures under fixtures/v0_96_0/recorded come from dev/docmost/record_fixtures.py run
against the local dev instance. These tests prove that the models parse real responses,
that real error bodies map to the right typed errors, and that the synthesized fixtures
used by the unit tests only contain fields Docmost actually returns.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from docmost_client import (
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
)
from docmost_client._ops import drive, get_page, get_space, list_children, list_spaces, me, search
from docmost_client._protocol import token_from_login, unwrap
from docmost_client.errors import AuthenticationError, DocmostError
from docmost_client.models import ContentFormat
from docmost_client.policy import SpaceAllowlist

FIXTURES = Path(__file__).parent.parent / "fixtures" / "v0_96_0"
RECORDED = FIXTURES / "recorded"
OPEN = SpaceAllowlist(None)


def recorded(name: str) -> Any:
    return json.loads((RECORDED / f"{name}.json").read_text())


def replay(responses: dict[str, Any]) -> Any:
    """A transport that answers each path with recorded data."""

    def call(path: str, payload: dict[str, Any]) -> Any:
        del payload
        return responses[path]

    return call


def test_current_user_parses() -> None:
    user = drive(me(), replay({"/users/me": recorded("users_me")}))

    assert user.email == "agent@example.com"
    assert user.workspace_id


def test_spaces_parse() -> None:
    page = drive(list_spaces(OPEN, 20, None, None), replay({"/spaces": recorded("spaces_list")}))

    assert {space.slug for space in page.items} >= {"engineering", "sandbox"}
    assert all(space.role in {"admin", "writer", "reader"} for space in page.items)


def test_space_info_parses() -> None:
    space = drive(get_space(OPEN, "engineering"), replay({"/spaces/info": recorded("space_info")}))

    assert space.slug == "engineering"
    assert space.role == "reader"


@pytest.mark.parametrize("fmt", ["markdown", "html", "json"])
def test_page_info_parses_in_every_format(fmt: ContentFormat) -> None:
    page = drive(get_page(OPEN, "x", fmt), replay({"/pages/info": recorded(f"page_info_{fmt}")}))

    assert page.title == "Runbook"
    assert page.space is not None
    assert page.space.slug == "engineering"
    assert page.can_edit is False  # the agent is a reader in engineering
    if fmt == "json":
        assert isinstance(page.content, dict)
        assert page.content["type"] == "doc"
    else:
        assert isinstance(page.content, str)
        assert "Restart the worker pool" in page.content


def test_sidebar_pages_parse() -> None:
    children = drive(
        list_children(OPEN, None, "0192b7a4-0000-7000-8000-000000000000", 20, None),
        replay({"/pages/sidebar-pages": recorded("sidebar_pages")}),
    )
    roots = drive(
        list_children(OPEN, "0192b7a4-0000-7000-8000-000000000001", None, 20, None),
        replay({"/pages/sidebar-pages": recorded("sidebar_root_pages")}),
    )

    assert [page.title for page in children.items] == ["Restart procedure"]
    assert {page.title for page in roots.items} == {"Runbook", "Rich page"}
    assert next(p for p in roots.items if p.title == "Runbook").has_children is True


def test_search_parses() -> None:
    results = drive(
        search(OPEN, "worker", None, 10, 0, False), replay({"/search": recorded("search")})
    )

    assert {hit.title for hit in results.hits} >= {"Runbook", "Restart procedure"}
    assert all("<b>worker</b>" in (hit.highlight or "") for hit in results.hits)


def test_update_response_includes_new_content_and_timestamp() -> None:
    created = recorded("page_create")
    updated = recorded("page_update")

    assert "content" not in created
    assert updated["updatedAt"] >= created["updatedAt"]
    assert "Appended line" in updated["content"]


@pytest.mark.parametrize(
    ("name", "error", "message"),
    [
        ("space_not_member", NotFoundError, "Space permissions not found"),
        ("page_not_found", NotFoundError, "Page not found"),
        ("update_without_operation", InvalidRequestError, "operation must be one of"),
        ("content_without_format", InvalidRequestError, "format must be one of"),
        ("write_as_reader", PermissionDeniedError, "Forbidden"),
        ("body_too_large", InvalidRequestError, "Request body is too large"),
    ],
)
def test_recorded_errors_map_to_typed_errors(
    name: str, error: type[DocmostError], message: str
) -> None:
    record = recorded(f"errors/{name}")
    response = httpx.Response(record["status"], json=record["body"])

    with pytest.raises(error, match=message):
        unwrap(response)


def test_recorded_login_errors_map_to_typed_errors() -> None:
    rejected = recorded("errors/login_rejected")
    limited = recorded("errors/login_rate_limited")

    with pytest.raises(AuthenticationError, match="Email or password does not match"):
        token_from_login(httpx.Response(rejected["status"], json=rejected["body"]))
    with pytest.raises(RateLimitedError):
        token_from_login(httpx.Response(limited["status"], json=limited["body"]))


def _keys(value: Any, prefix: str = "") -> set[str]:
    if isinstance(value, dict):
        found: set[str] = set()
        for key, item in value.items():
            found.add(prefix + key)
            found |= _keys(item, f"{prefix}{key}.")
        return found
    if isinstance(value, list) and value:
        return _keys(value[0], f"{prefix}[].")
    return set()


def _empty_list_paths(value: Any, prefix: str = "") -> set[str]:
    if isinstance(value, dict):
        found: set[str] = set()
        for key, item in value.items():
            if item == []:
                found.add(f"{prefix}{key}.[].")
            found |= _empty_list_paths(item, f"{prefix}{key}.")
        return found
    if isinstance(value, list) and value:
        return _empty_list_paths(value[0], f"{prefix}[].")
    return set()


@pytest.mark.parametrize(
    "name",
    [
        "users_me",
        "version",
        "spaces_list",
        "space_info",
        "page_info_markdown",
        "sidebar_pages",
        "search",
    ],
)
def test_synthesized_fixtures_only_use_real_fields(name: str) -> None:
    synthesized = json.loads((FIXTURES / f"{name}.json").read_text())
    real = recorded(name)
    unseen = {
        key
        for key in _keys(synthesized) - _keys(real)
        if not any(key.startswith(path) for path in _empty_list_paths(real))
    }

    assert unseen == set()
