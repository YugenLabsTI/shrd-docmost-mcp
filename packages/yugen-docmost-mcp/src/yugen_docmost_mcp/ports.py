"""Ports the MCP tools depend on.

The tools layer talks to these protocols only, never to HTTP. ``AsyncDocmostClient``
from docmost-client satisfies both structurally; tests use in-memory fakes.
"""

from datetime import datetime
from typing import Any, Protocol

from docmost_client import (
    Comment,
    CompatibilityReport,
    ContentFormat,
    ContentOperation,
    Page,
    PageSummary,
    Paginated,
    RecentPage,
    SearchResults,
    Space,
)


class WikiReader(Protocol):
    async def check_compatibility(self) -> CompatibilityReport: ...

    async def list_spaces(
        self, *, limit: int, cursor: str | None, query: str | None
    ) -> Paginated[Space]: ...

    async def search(
        self, query: str, *, space: str | None, limit: int, offset: int, title_only: bool
    ) -> SearchResults: ...

    async def get_page(self, page_id: str, *, format: ContentFormat) -> Page: ...

    async def list_children(
        self, *, space: str | None, parent_page_id: str | None, limit: int, cursor: str | None
    ) -> Paginated[PageSummary]: ...

    async def list_recent_pages(
        self, *, space: str | None, limit: int, cursor: str | None
    ) -> Paginated[RecentPage]: ...

    async def list_comments(
        self, page_id: str, *, limit: int, cursor: str | None
    ) -> Paginated[Comment]: ...


class WikiCommenter(Protocol):
    async def create_comment(
        self, page_id: str, text: str, *, parent_comment_id: str | None
    ) -> Comment: ...


class WikiWriter(Protocol):
    async def create_page(
        self,
        *,
        space: str,
        title: str | None,
        content: str | dict[str, Any] | None,
        format: ContentFormat,
        parent_page_id: str | None,
        icon: str | None,
    ) -> Page: ...

    async def update_page(
        self,
        page_id: str,
        *,
        content: str | dict[str, Any] | None,
        operation: ContentOperation | None,
        format: ContentFormat,
        title: str | None,
        icon: str | None,
        expected_updated_at: datetime | None,
    ) -> Page: ...
