"""Structured tool results and typed error payloads returned to agents."""

import json
import re
from datetime import datetime
from typing import Any

from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict

from docmost_client import (
    Comment,
    DocmostError,
    Page,
    PageBusyError,
    PageOutline,
    PageSummary,
    RecentPage,
    SearchHit,
    Space,
    SpaceRef,
    StalePageError,
)

# Errors an agent can resolve by waiting or by re-reading and trying again.
RETRYABLE_CODES = frozenset({"RATE_LIMITED", "UPSTREAM_ERROR", "STALE_PAGE", "PAGE_BUSY"})
_HIGHLIGHT = re.compile(r"</?b>", re.IGNORECASE)


class _Result(BaseModel):
    model_config = ConfigDict(frozen=True)


class SpaceBrief(_Result):
    id: str
    slug: str
    name: str

    @classmethod
    def of(cls, space: SpaceRef) -> "SpaceBrief":
        return cls(id=space.id, slug=space.slug, name=space.name)


class SpaceItem(_Result):
    id: str
    slug: str
    name: str
    description: str | None
    role: str | None

    @classmethod
    def of(cls, space: Space) -> "SpaceItem":
        return cls(
            id=space.id,
            slug=space.slug,
            name=space.name,
            description=space.description,
            role=space.role,
        )


class SpacesResult(_Result):
    spaces: list[SpaceItem]
    next_cursor: str | None


class SearchHitItem(_Result):
    page_id: str
    slug_id: str | None
    title: str | None
    space: SpaceBrief
    updated_at: datetime | None
    snippet: str | None

    @classmethod
    def of(cls, hit: SearchHit) -> "SearchHitItem":
        snippet = None if hit.highlight is None else _HIGHLIGHT.sub("**", hit.highlight)
        return cls(
            page_id=hit.id,
            slug_id=hit.slug_id,
            title=hit.title,
            space=SpaceBrief.of(hit.space),
            updated_at=hit.updated_at,
            snippet=snippet,
        )


class SearchResult(_Result):
    hits: list[SearchHitItem]
    next_offset: int | None


class PageInfo(_Result):
    id: str
    slug_id: str
    title: str | None
    space_id: str
    space: SpaceBrief | None
    parent_page_id: str | None
    updated_at: datetime
    is_locked: bool
    can_edit: bool | None

    @classmethod
    def fields_of(cls, page: Page) -> dict[str, Any]:
        return {
            "id": page.id,
            "slug_id": page.slug_id,
            "title": page.title,
            "space_id": page.space_id,
            "space": None if page.space is None else SpaceBrief.of(page.space),
            "parent_page_id": page.parent_page_id,
            "updated_at": page.updated_at,
            "is_locked": page.is_locked,
            "can_edit": page.can_edit,
        }

    @classmethod
    def of(cls, page: Page) -> "PageInfo":
        return cls(**cls.fields_of(page))


class PageContent(PageInfo):
    format: str
    content: str | dict[str, Any] | None

    @classmethod
    def of(cls, page: Page) -> "PageContent":
        return cls(**cls.fields_of(page), format=page.format, content=page.content)


class ChildItem(_Result):
    id: str
    slug_id: str
    title: str | None
    parent_page_id: str | None
    has_children: bool

    @classmethod
    def of(cls, page: PageSummary) -> "ChildItem":
        return cls(
            id=page.id,
            slug_id=page.slug_id,
            title=page.title,
            parent_page_id=page.parent_page_id,
            has_children=page.has_children,
        )


class ChildrenResult(_Result):
    pages: list[ChildItem]
    next_cursor: str | None


class HeadingItem(_Result):
    id: str
    level: int
    text: str


class OutlineResult(_Result):
    page_id: str
    title: str | None
    updated_at: datetime
    headings: list[HeadingItem]

    @classmethod
    def of(cls, outline: PageOutline) -> "OutlineResult":
        return cls(
            page_id=outline.page_id,
            title=outline.title,
            updated_at=outline.updated_at,
            headings=[HeadingItem(id=h.id, level=h.level, text=h.text) for h in outline.headings],
        )


class RecentPageItem(_Result):
    id: str
    slug_id: str
    title: str | None
    parent_page_id: str | None
    space: SpaceBrief
    updated_at: datetime

    @classmethod
    def of(cls, page: RecentPage) -> "RecentPageItem":
        return cls(
            id=page.id,
            slug_id=page.slug_id,
            title=page.title,
            parent_page_id=page.parent_page_id,
            space=SpaceBrief.of(page.space),
            updated_at=page.updated_at,
        )


class RecentPagesResult(_Result):
    pages: list[RecentPageItem]
    next_cursor: str | None


class CommentItem(_Result):
    id: str
    parent_comment_id: str | None
    type: str | None
    selection: str | None
    text: str
    author: str | None
    created_at: datetime
    resolved: bool

    @classmethod
    def of(cls, comment: Comment) -> "CommentItem":
        return cls(
            id=comment.id,
            parent_comment_id=comment.parent_comment_id,
            type=comment.type,
            selection=comment.selection,
            text=comment.text,
            author=comment.creator_name,
            created_at=comment.created_at,
            resolved=comment.resolved_at is not None,
        )


class CommentsResult(_Result):
    comments: list[CommentItem]
    next_cursor: str | None


def error_result(exc: DocmostError) -> CallToolResult:
    """A tool error with a stable code that agents can branch on."""
    error: dict[str, Any] = {
        "code": exc.code,
        "message": str(exc),
        "retryable": exc.code in RETRYABLE_CODES,
    }
    if isinstance(exc, StalePageError):
        error["current_updated_at"] = _iso(exc.current_updated_at)
    if isinstance(exc, PageBusyError):
        error["retry_after_seconds"] = exc.retry_after_seconds
    payload = {"error": error}
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structured_content=payload,
        is_error=True,
    )


def _iso(value: datetime) -> str:
    text = value.isoformat()
    return text[:-6] + "Z" if text.endswith("+00:00") else text


class AuditSummaryResult(_Result):
    """What the audit log recorded in a span (see ``yugen_docmost_mcp.audit``)."""

    calls: int
    first: str | None
    last: str | None
    by_tool: dict[str, dict[str, int]]
    errors_by_code: dict[str, int]
    spaces: dict[str, int]
    pages_written: list[str]
    pages_refused: list[str]
    interrupted: list[dict[str, str]]
