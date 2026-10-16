"""High-level Docmost clients.

``DocmostClient`` (blocking) and ``AsyncDocmostClient`` expose the same methods; both run
the I/O-free operations in ``_ops`` against a session.
"""

from types import TracebackType
from typing import Any, Self, TypeVar

from docmost_client import _ops, compat
from docmost_client.models import (
    CompatibilityReport,
    ContentFormat,
    CurrentUser,
    Page,
    PageSummary,
    Paginated,
    SearchHit,
    Space,
)
from docmost_client.session import AsyncSession, Session
from docmost_client.settings import DocmostSettings

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 20
DEFAULT_SEARCH_RESULTS = 10


class DocmostClient:
    """Blocking client for a Docmost v0.96.0 instance."""

    def __init__(self, settings: DocmostSettings, *, session: Session | None = None) -> None:
        self._settings = settings
        self._session = Session(settings) if session is None else session
        self._version: str | None = None
        self._version_loaded = False

    @classmethod
    def from_env(cls) -> Self:
        """Create a client from ``DOCMOST_*`` environment variables."""
        return cls(DocmostSettings.from_env())

    @property
    def settings(self) -> DocmostSettings:
        return self._settings

    def __repr__(self) -> str:
        return f"DocmostClient(base_url={self._settings.base_url!r})"

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Log out and release connections."""
        self._session.close()

    def me(self) -> CurrentUser:
        """Return the account the client is logged in as."""
        return self._run(_ops.me())

    def server_version(self) -> str | None:
        """Return the Docmost version, or None when the server cannot report it.

        Fetched once per client: Docmost calls GitHub on every version request.
        """
        if not self._version_loaded:
            self._version = self._run(_ops.server_version())
            self._version_loaded = True
        return self._version

    def check_compatibility(self) -> CompatibilityReport:
        """Compare the server version with the tested versions.

        Raises UnsupportedVersionError for an untested version unless
        DOCMOST_ALLOW_UNTESTED_VERSION is set.
        """
        return compat.evaluate(
            self.server_version(), allow_untested=self._settings.allow_untested_version
        )

    def list_spaces(
        self, *, limit: int = DEFAULT_PAGE_SIZE, cursor: str | None = None, query: str | None = None
    ) -> Paginated[Space]:
        """List spaces the account is a member of, optionally filtered by name."""
        return self._run(_ops.list_spaces(limit, cursor, query))

    def get_space(self, space: str) -> Space:
        """Return a space by UUID or slug."""
        return self._run(_ops.get_space(space))

    def get_page(self, page_id: str, *, format: ContentFormat = "markdown") -> Page:
        """Return a page (by UUID or slug ID) with its content in ``format``."""
        return self._run(_ops.get_page(page_id, format))

    def list_children(
        self,
        *,
        space: str | None = None,
        parent_page_id: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> Paginated[PageSummary]:
        """List the root pages of ``space`` or the children of ``parent_page_id``."""
        return self._run(_ops.list_children(space, parent_page_id, limit, cursor))

    def search(
        self,
        query: str,
        *,
        space: str | None = None,
        limit: int = DEFAULT_SEARCH_RESULTS,
        offset: int = 0,
        title_only: bool = False,
    ) -> list[SearchHit]:
        """Full-text search over pages the account can read."""
        return self._run(_ops.search(query, space, limit, offset, title_only))

    def _run(self, op: _ops.Op[T]) -> T:
        return _ops.drive(op, self._call)

    def _call(self, path: str, payload: dict[str, Any]) -> Any:
        return self._session.call(path, payload)


class AsyncDocmostClient:
    """Asynchronous client for a Docmost v0.96.0 instance."""

    def __init__(self, settings: DocmostSettings, *, session: AsyncSession | None = None) -> None:
        self._settings = settings
        self._session = AsyncSession(settings) if session is None else session
        self._version: str | None = None
        self._version_loaded = False

    @classmethod
    def from_env(cls) -> Self:
        """Create a client from ``DOCMOST_*`` environment variables."""
        return cls(DocmostSettings.from_env())

    @property
    def settings(self) -> DocmostSettings:
        return self._settings

    def __repr__(self) -> str:
        return f"AsyncDocmostClient(base_url={self._settings.base_url!r})"

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Log out and release connections."""
        await self._session.aclose()

    async def me(self) -> CurrentUser:
        """Return the account the client is logged in as."""
        return await self._run(_ops.me())

    async def server_version(self) -> str | None:
        """Return the Docmost version, or None when the server cannot report it."""
        if not self._version_loaded:
            self._version = await self._run(_ops.server_version())
            self._version_loaded = True
        return self._version

    async def check_compatibility(self) -> CompatibilityReport:
        """Compare the server version with the tested versions (see DocmostClient)."""
        return compat.evaluate(
            await self.server_version(), allow_untested=self._settings.allow_untested_version
        )

    async def list_spaces(
        self, *, limit: int = DEFAULT_PAGE_SIZE, cursor: str | None = None, query: str | None = None
    ) -> Paginated[Space]:
        """List spaces the account is a member of, optionally filtered by name."""
        return await self._run(_ops.list_spaces(limit, cursor, query))

    async def get_space(self, space: str) -> Space:
        """Return a space by UUID or slug."""
        return await self._run(_ops.get_space(space))

    async def get_page(self, page_id: str, *, format: ContentFormat = "markdown") -> Page:
        """Return a page (by UUID or slug ID) with its content in ``format``."""
        return await self._run(_ops.get_page(page_id, format))

    async def list_children(
        self,
        *,
        space: str | None = None,
        parent_page_id: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> Paginated[PageSummary]:
        """List the root pages of ``space`` or the children of ``parent_page_id``."""
        return await self._run(_ops.list_children(space, parent_page_id, limit, cursor))

    async def search(
        self,
        query: str,
        *,
        space: str | None = None,
        limit: int = DEFAULT_SEARCH_RESULTS,
        offset: int = 0,
        title_only: bool = False,
    ) -> list[SearchHit]:
        """Full-text search over pages the account can read."""
        return await self._run(_ops.search(query, space, limit, offset, title_only))

    async def _run(self, op: _ops.Op[T]) -> T:
        return await _ops.drive_async(op, self._call)

    async def _call(self, path: str, payload: dict[str, Any]) -> Any:
        return await self._session.call(path, payload)
