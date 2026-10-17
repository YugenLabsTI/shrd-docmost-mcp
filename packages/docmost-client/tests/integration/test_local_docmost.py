"""Integration tests against the local Docmost 0.96.0 from dev/docmost.

Opt-in: they run only with DOCMOST_INTEGRATION=1 and the variables written by
dev/docmost/bootstrap.py (``set -a; . dev/docmost/.env.test; set +a``). They log in as
the seeded agent (reader in engineering, writer in sandbox) and write only to sandbox.
Clients are shared per module because Docmost allows 10 logins per minute per IP.
"""

import os
import uuid
from collections.abc import Iterator
from datetime import timedelta, timezone

import pytest

from docmost_client import (
    DocmostClient,
    DocmostSettings,
    InvalidRequestError,
    NotFoundError,
    Page,
    PageBusyError,
    PermissionDeniedError,
    ReadOnlyError,
    SpaceNotAllowedError,
    StalePageError,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DOCMOST_INTEGRATION") != "1",
        reason="set DOCMOST_INTEGRATION=1 and load dev/docmost/.env.test",
    ),
]


def _settings(**overrides: str) -> DocmostSettings:
    env = {key: value for key, value in os.environ.items() if key.startswith("DOCMOST_")}
    env.pop("DOCMOST_ALLOWED_SPACES", None)
    env.update(overrides)
    settings = DocmostSettings.from_env(env)
    assert settings.base_url.startswith(("http://localhost", "http://127.0.0.1"))
    return settings


@pytest.fixture(scope="module")
def reader() -> Iterator[DocmostClient]:
    with DocmostClient(_settings()) as client:
        yield client


@pytest.fixture(scope="module")
def writer() -> Iterator[DocmostClient]:
    with DocmostClient(_settings(DOCMOST_READ_ONLY="0")) as client:
        yield client


@pytest.fixture(scope="module")
def scoped() -> Iterator[DocmostClient]:
    settings = _settings(DOCMOST_READ_ONLY="0", DOCMOST_ALLOWED_SPACES="engineering")
    with DocmostClient(settings) as client:
        yield client


@pytest.fixture(scope="module")
def rich(reader: DocmostClient) -> Page:
    roots = reader.list_children(space="engineering")
    page_id = next(page.id for page in roots.items if page.title == "Rich page")
    return reader.get_page(page_id, format="html")


def test_server_is_a_supported_version(reader: DocmostClient) -> None:
    report = reader.check_compatibility()

    assert report.status == "supported"
    assert report.docmost_version == "0.96.0"


def test_agent_sees_its_spaces_only(reader: DocmostClient) -> None:
    slugs = {space.slug for space in reader.list_spaces().items}

    assert {"engineering", "sandbox"} <= slugs
    assert "ops" not in slugs
    with pytest.raises(NotFoundError):
        reader.get_space("ops")


def test_search_finds_seeded_pages(reader: DocmostClient) -> None:
    titles = {hit.title for hit in reader.search("worker", space="engineering").hits}

    assert {"Runbook", "Restart procedure"} <= titles


def test_page_tree_by_slug(reader: DocmostClient) -> None:
    runbook = next(
        page for page in reader.list_children(space="engineering").items if page.title == "Runbook"
    )
    children = reader.list_children(parent_page_id=runbook.slug_id)

    assert [page.title for page in children.items] == ["Restart procedure"]


def test_markdown_drops_what_html_keeps(reader: DocmostClient, rich: Page) -> None:
    markdown = reader.get_page(rich.id, format="markdown").content
    assert isinstance(markdown, str)
    assert isinstance(rich.content, str)

    assert 'data-callout-type="warning"' in rich.content
    assert "<u>Underlined</u>" in rich.content
    assert "color: #dc2626" in rich.content
    assert "<u>" not in markdown
    assert "#dc2626" not in markdown
    assert ":::warning" in markdown


def test_reader_role_cannot_write_and_nothing_is_sent(writer: DocmostClient, rich: Page) -> None:
    with pytest.raises(PermissionDeniedError, match="cannot edit"):
        writer.update_page(rich.id, content="x", operation="append")

    # Docmost bumps updatedAt on every update request, so an unchanged value proves
    # that no update reached the server.
    assert writer.get_page(rich.id, format="html").updated_at == rich.updated_at


def test_read_only_client_refuses_writes(reader: DocmostClient) -> None:
    with pytest.raises(ReadOnlyError):
        reader.create_page(space="sandbox", title="Never")


def test_allowlist_blocks_writes_to_other_spaces(scoped: DocmostClient) -> None:
    with pytest.raises(SpaceNotAllowedError):
        scoped.create_page(space="sandbox", title="Never")


def test_write_lifecycle_in_the_sandbox(writer: DocmostClient) -> None:
    title = f"IT {uuid.uuid4().hex[:8]}"
    created = writer.create_page(space="sandbox", title=title, content="First paragraph.")
    first = writer.get_page(created.id)

    appended = writer.update_page(
        created.id,
        content="Second paragraph.",
        operation="append",
        expected_updated_at=first.updated_at,
    )
    assert isinstance(appended.content, str)
    assert "First paragraph." in appended.content
    assert "Second paragraph." in appended.content
    assert appended.updated_at > first.updated_at

    with pytest.raises(StalePageError):
        writer.update_page(
            created.id,
            content="Too late.",
            operation="append",
            expected_updated_at=first.updated_at,
        )

    replaced = writer.update_page(
        created.id,
        content="<p>Only <strong>this</strong>.</p>",
        operation="replace",
        format="html",
        title=f"{title} (renamed)",
        expected_updated_at=appended.updated_at,
    )
    assert replaced.title == f"{title} (renamed)"
    assert isinstance(replaced.content, str)
    assert "<strong>this</strong>" in replaced.content
    assert "First paragraph." not in replaced.content


def test_html_round_trip_preserves_rich_content(writer: DocmostClient, rich: Page) -> None:
    assert isinstance(rich.content, str)
    copy = writer.create_page(
        space="sandbox",
        title=f"Rich copy {uuid.uuid4().hex[:8]}",
        content=rich.content,
        format="html",
    )
    reread = writer.get_page(copy.id, format="markdown")
    original = writer.get_page(rich.id, format="markdown")

    assert reread.content == original.content


def test_precheck_tolerates_equal_instants_in_other_offsets(writer: DocmostClient) -> None:
    page = writer.create_page(space="sandbox", title=f"Offset {uuid.uuid4().hex[:8]}", content="a")
    current = writer.get_page(page.id)
    shifted = current.updated_at.astimezone(timezone(timedelta(hours=-5)))
    assert shifted.utcoffset() != current.updated_at.utcoffset()

    result = writer.update_page(
        page.id, content="b", operation="append", expected_updated_at=shifted
    )

    assert result.updated_at > current.updated_at


def test_front_matter_guard_runs_before_any_request(writer: DocmostClient) -> None:
    with pytest.raises(InvalidRequestError, match="front matter"):
        writer.create_page(space="sandbox", title="Never", content="---\nIntro\n---\nBody")


# --- block 1: comments and recent pages ----------------------------------------


@pytest.fixture(scope="module")
def commenter() -> Iterator[DocmostClient]:
    # Read-only + comments: on Community Edition the account needs the writer role to
    # comment (sandbox), so the server's read-only mode is what blocks page edits.
    with DocmostClient(_settings(DOCMOST_ALLOW_COMMENTS="1")) as client:
        yield client


def test_comment_only_mode_comments_but_never_edits(commenter: DocmostClient) -> None:
    page = next(iter(commenter.list_children(space="sandbox").items))

    comment = commenter.create_comment(page.id, "Integration comment.\nSecond line.")
    listed = commenter.list_comments(page.id).items

    assert comment.text == "Integration comment.\nSecond line."
    assert any(item.id == comment.id and item.text == comment.text for item in listed)
    with pytest.raises(ReadOnlyError):
        commenter.update_page(page.id, content="never", operation="append")


def test_reader_role_cannot_comment(commenter: DocmostClient, rich: Page) -> None:
    with pytest.raises(PermissionDeniedError, match="edit access"):
        commenter.create_comment(rich.id, "never")


def test_recent_pages_show_the_latest_update_first(writer: DocmostClient) -> None:
    page = writer.create_page(space="sandbox", title=f"Recent {uuid.uuid4().hex[:8]}", content="x")

    recent = writer.list_recent_pages(space="sandbox", limit=20).items

    # Other writes may land in between: check membership and ordering, not position.
    mine = next(item for item in recent if item.id == page.id)
    assert mine.space.slug == "sandbox"
    assert mine.updated_at == page.updated_at
    assert [item.updated_at for item in recent] == sorted(
        (item.updated_at for item in recent), reverse=True
    )


# --- section editing ---------------------------------------------------------------

SECTIONED = (
    "<h1>Guide</h1><p>Intro.</p>"
    "<h2>Install</h2><p>Run the installer.</p>"
    "<h2>Configure</h2><p>Old configure body.</p><h3>Advanced</h3><p>Knobs.</p>"
    "<h2>Uninstall</h2><p>Remove it.</p>"
)


def test_a_page_saved_moments_ago_is_busy(writer: DocmostClient) -> None:
    page = writer.create_page(
        space="sandbox", title=f"Busy {uuid.uuid4().hex[:8]}", content=SECTIONED, format="html"
    )
    outline = writer.get_page_outline(page.id)
    install = next(h for h in outline.headings if h.text == "Install")

    with pytest.raises(PageBusyError) as exc:
        writer.edit_section(
            page.id,
            heading_id=install.id,
            operation="append",
            content="<p>never</p>",
            expected_updated_at=outline.updated_at,
        )

    assert exc.value.retry_after_seconds > 0


def test_section_edits_change_only_their_section(
    writer: DocmostClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    from docmost_client._protocol import ServerClock

    # Pretend two minutes passed on Docmost's clock, so the busy window does not apply.
    monkeypatch.setattr(ServerClock, "now", lambda self: datetime.now(UTC) + timedelta(minutes=2))
    page = writer.create_page(
        space="sandbox", title=f"Sections {uuid.uuid4().hex[:8]}", content=SECTIONED, format="html"
    )
    outline = writer.get_page_outline(page.id)
    assert [(h.level, h.text) for h in outline.headings] == [
        (1, "Guide"),
        (2, "Install"),
        (2, "Configure"),
        (3, "Advanced"),
        (2, "Uninstall"),
    ]
    ids = {h.text: h.id for h in outline.headings}

    replaced = writer.edit_section(
        page.id,
        heading_id=ids["Configure"],
        operation="replace",
        content="<p>New configure body.</p>",
        expected_updated_at=outline.updated_at,
    )
    prepended = writer.edit_section(
        page.id,
        heading_id=ids["Install"],
        operation="prepend",
        content="<p>Before installing.</p>",
        expected_updated_at=replaced.updated_at,
    )
    writer.edit_section(
        page.id,
        heading_id=ids["Uninstall"],
        operation="append",
        content="<p>Bye.</p>",
        expected_updated_at=prepended.updated_at,
    )

    markdown = writer.get_page(page.id, format="markdown").content
    assert markdown == (
        "# Guide\n\nIntro.\n\n## Install\n\nBefore installing.\n\nRun the installer.\n\n"
        "## Configure\n\nNew configure body.\n\n## Uninstall\n\nRemove it.\n\nBye."
    )
    after = writer.get_page_outline(page.id)
    assert [h.text for h in after.headings] == ["Guide", "Install", "Configure", "Uninstall"]
    assert {h.text: h.id for h in after.headings} == {
        k: v for k, v in ids.items() if k != "Advanced"
    }


def test_pages_with_mentions_round_trip_without_new_mentions(writer: DocmostClient) -> None:
    me = writer.me()
    page = writer.create_page(space="sandbox", title=f"Mentions {uuid.uuid4().hex[:8]}")
    mention = {"type": "mention", "attrs": {"id": uuid.uuid4().hex, "label": me.name,
                                            "entityType": "user", "entityId": me.id,
                                            "creatorId": me.id}}  # fmt: skip
    # The client never adds mentions, so seed one (a self-mention notifies nobody).
    writer._session.call(  # pyright: ignore[reportPrivateUsage]
        "/pages/update",
        {
            "pageId": page.id,
            "operation": "replace",
            "format": "json",
            "content": {"type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Ask "}, mention]},
                {"type": "paragraph", "content": [{"type": "text", "text": "Old body."}]},
            ]},
        },
    )  # fmt: skip
    current = writer.get_page(page.id, format="html")
    assert isinstance(current.content, str)
    assert f'data-entity-id="{me.id}"' in current.content

    edited = writer.update_page(
        page.id,
        content=current.content.replace("Old body.", "New body."),
        operation="replace",
        format="html",
        expected_updated_at=current.updated_at,
    )
    assert isinstance(edited.content, str)
    assert "New body." in edited.content
    assert f'data-entity-id="{me.id}"' in edited.content

    stranger = edited.content.replace(me.id, str(uuid.uuid4()))
    with pytest.raises(InvalidRequestError, match="not already on the page"):
        writer.update_page(
            page.id,
            content=stranger,
            operation="replace",
            format="html",
            expected_updated_at=edited.updated_at,
        )
    assert writer.get_page(page.id).updated_at == edited.updated_at
