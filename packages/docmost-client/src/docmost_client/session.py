"""Authenticated sessions against the Docmost internal API.

The JWT lives only in memory. Login is single-flight and repeated at most once per
request when Docmost answers 401; closing the session logs out, which revokes the
server-side session (Docmost keeps at most 25 per user).
"""

import contextlib
import threading
from collections.abc import Mapping
from datetime import datetime
from types import TracebackType
from typing import Any, Self

import anyio
import httpx

from docmost_client import _protocol
from docmost_client._version import USER_AGENT
from docmost_client.errors import DocmostError
from docmost_client.settings import DocmostSettings

Payload = Mapping[str, Any]


def _ensure_open(closed: bool) -> None:
    # Checked under the login lock so a call racing close() cannot open a new
    # server-side session that would never be logged out.
    if closed:
        raise RuntimeError("The Docmost session is closed.")


class Session:
    """Blocking session. Safe to share between threads."""

    def __init__(
        self, settings: DocmostSettings, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._client = httpx.Client(
            transport=transport, **_protocol.client_options(settings, USER_AGENT)
        )
        self._token: str | None = None
        self._lock = threading.Lock()
        self._closed = False
        self._clock = _protocol.ServerClock()

    def __repr__(self) -> str:
        return (
            f"Session(base_url={self._settings.base_url!r}, "
            f"authenticated={self._token is not None})"
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def call(self, path: str, payload: Payload | None = None) -> Any:
        """POST ``payload`` to ``/api{path}`` and return the unwrapped ``data``."""
        token = self._ensure_token()
        response = self._post(path, payload, token)
        if response.status_code == 401:
            response = self._post(path, payload, self._relogin(token))
        return _protocol.unwrap(response)

    def server_now(self) -> datetime | None:
        """Docmost's current time from its latest Date header, or None before any response."""
        return self._clock.now()

    def close(self) -> None:
        """Log out (best effort) and release connections. Idempotent."""
        with self._lock:
            self._closed = True
            token, self._token = self._token, None
        if token is not None:
            with contextlib.suppress(DocmostError):
                self._post(_protocol.LOGOUT_PATH, None, token)
        self._client.close()

    def _ensure_token(self) -> str:
        with self._lock:
            _ensure_open(self._closed)
            if self._token is None:
                self._token = self._login()
            return self._token

    def _relogin(self, stale: str) -> str:
        with self._lock:
            _ensure_open(self._closed)
            if self._token is None or self._token == stale:
                self._token = None
                self._token = self._login()
            return self._token

    def _login(self) -> str:
        payload = _protocol.login_payload(self._settings)
        return _protocol.token_from_login(self._post(_protocol.LOGIN_PATH, payload, None))

    def _post(self, path: str, payload: Payload | None, token: str | None) -> httpx.Response:
        try:
            response = self._client.post(
                path, json=dict(payload or {}), headers=_protocol.bearer(token)
            )
        except httpx.HTTPError as exc:
            raise _protocol.transport_error(exc) from None
        self._clock.observe(response)
        return response


class AsyncSession:
    """Asynchronous session (asyncio or trio via anyio). Safe to share between tasks."""

    def __init__(
        self, settings: DocmostSettings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            transport=transport, **_protocol.client_options(settings, USER_AGENT)
        )
        self._token: str | None = None
        self._lock = anyio.Lock()
        self._closed = False
        self._clock = _protocol.ServerClock()

    def __repr__(self) -> str:
        return (
            f"AsyncSession(base_url={self._settings.base_url!r}, "
            f"authenticated={self._token is not None})"
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def call(self, path: str, payload: Payload | None = None) -> Any:
        """POST ``payload`` to ``/api{path}`` and return the unwrapped ``data``."""
        token = await self._ensure_token()
        response = await self._post(path, payload, token)
        if response.status_code == 401:
            response = await self._post(path, payload, await self._relogin(token))
        return _protocol.unwrap(response)

    def server_now(self) -> datetime | None:
        """Docmost's current time from its latest Date header, or None before any response."""
        return self._clock.now()

    async def aclose(self) -> None:
        """Log out (best effort) and release connections. Idempotent."""
        async with self._lock:
            self._closed = True
            token, self._token = self._token, None
        if token is not None:
            with contextlib.suppress(DocmostError):
                await self._post(_protocol.LOGOUT_PATH, None, token)
        await self._client.aclose()

    async def _ensure_token(self) -> str:
        async with self._lock:
            _ensure_open(self._closed)
            if self._token is None:
                self._token = await self._login()
            return self._token

    async def _relogin(self, stale: str) -> str:
        async with self._lock:
            _ensure_open(self._closed)
            if self._token is None or self._token == stale:
                self._token = None
                self._token = await self._login()
            return self._token

    async def _login(self) -> str:
        payload = _protocol.login_payload(self._settings)
        response = await self._post(_protocol.LOGIN_PATH, payload, None)
        return _protocol.token_from_login(response)

    async def _post(self, path: str, payload: Payload | None, token: str | None) -> httpx.Response:
        try:
            response = await self._client.post(
                path, json=dict(payload or {}), headers=_protocol.bearer(token)
            )
        except httpx.HTTPError as exc:
            raise _protocol.transport_error(exc) from None
        self._clock.observe(response)
        return response
