"""Read-only MCP resources: pages, a space's page tree, and recently updated pages.

Hosts attach resources as context without a tool call. They go through the same client
as the tools, so the space allowlist and the compatibility gate apply.
"""

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError

from docmost_client import DocmostError, PageSummary
from yugen_docmost_mcp.ports import WikiReader

# A space tree walks the hierarchy one level per request; keep it bounded.
MAX_TREE_PAGES = 200
MAX_TREE_REQUESTS = 50
MAX_RECENT_PAGES = 50
_PAGE_SIZE = 100
_MARKDOWN = "text/markdown"
_TRUNCATED = "\n(truncated: the tree is larger than this view)\n"

T = TypeVar("T")


def register_resources(
    server: MCPServer[Any], reader: WikiReader, ensure: Callable[[], Awaitable[None]]
) -> None:
    """Register the resources; ``ensure`` runs the compatibility gate before each read."""

    async def guarded(read: Callable[[], Awaitable[T]]) -> T:
        try:
            await ensure()
            return await read()
        except DocmostError as exc:
            # Client errors are already free of credentials and page content.
            raise ResourceError(f"{exc.code}: {exc}") from None

    @server.resource(
        "docmost://page/{page_id}",
        name="page",
        title="Docmost page",
        description="A page as markdown, with its title, ids and last update. page_id is the "
        "page UUID or slug id.",
        mime_type=_MARKDOWN,
    )
    async def page(page_id: str) -> str:
        found = await guarded(lambda: reader.get_page(page_id, format="markdown"))
        space = f"Space: {found.space.slug}\n" if found.space is not None else ""
        content = found.content if isinstance(found.content, str) else ""
        return (
            f"# {found.title or 'Untitled'}\n\n"
            f"Page id: {found.id}\n"
            f"Slug id: {found.slug_id}\n"
            f"{space}"
            f"Updated: {found.updated_at.isoformat()}\n\n"
            "---\n\n"
            f"{content}"
        )

    @server.resource(
        "docmost://space/{space}/tree",
        name="space_tree",
        title="Docmost space tree",
        description="The page hierarchy of a space (slug or id), as a nested list of titles "
        f"and slug ids. Shows at most {MAX_TREE_PAGES} pages.",
        mime_type=_MARKDOWN,
    )
    async def space_tree(space: str) -> str:
        tree = await guarded(lambda: _walk_tree(reader, space))
        text = f"# Pages in {space}\n\n" + "".join(f"{line}\n" for line in tree.lines)
        return text + (_TRUNCATED if tree.truncated else "")

    @server.resource(
        "docmost://recent",
        name="recent",
        title="Recently updated Docmost pages",
        description=f"The {MAX_RECENT_PAGES} most recently updated pages in the allowed spaces.",
        mime_type=_MARKDOWN,
    )
    async def recent() -> str:
        found = await guarded(
            lambda: reader.list_recent_pages(space=None, limit=MAX_RECENT_PAGES, cursor=None)
        )
        lines = "".join(
            f"- {item.title or 'Untitled'} ({item.slug_id}) in {item.space.slug}, "
            f"updated {item.updated_at.isoformat()}\n"
            for item in found.items
        )
        return "# Recently updated pages\n\n" + lines


class _Tree:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.truncated = False
        self.requests = 0


async def _walk_tree(reader: WikiReader, space: str) -> _Tree:
    tree = _Tree()

    async def children(parent: str | None) -> list[PageSummary]:
        """The pages under ``parent``; stops (truncated) when the request budget is spent."""
        items: list[PageSummary] = []
        cursor: str | None = None
        while True:
            if tree.requests >= MAX_TREE_REQUESTS:
                tree.truncated = True
                return items
            tree.requests += 1
            found = await reader.list_children(
                space=space if parent is None else None,
                parent_page_id=parent,
                limit=_PAGE_SIZE,
                cursor=cursor,
            )
            items.extend(found.items)
            if not found.has_next_page or not found.next_cursor:
                return items
            cursor = found.next_cursor

    async def walk(parent: str | None, depth: int) -> None:
        for item in await children(parent):
            if len(tree.lines) >= MAX_TREE_PAGES:
                tree.truncated = True
                return
            tree.lines.append(f"{'  ' * depth}- {item.title or 'Untitled'} ({item.slug_id})")
            if item.has_children:
                await walk(item.id, depth + 1)

    await walk(None, 0)
    return tree
