"""I/O-free helpers shared by the sync and async sessions.

Docmost v0.96.0 conventions (see docs/docmost-api-v0.96.0.md):
- every endpoint is ``POST /api/<path>`` with a JSON body;
- success bodies are wrapped as ``{"data": ..., "success": true, "status": 200}``;
- errors use the NestJS shape ``{"message": str | list[str], "error": str, "statusCode": int}``;
- login returns the JWT only in the ``authToken`` cookie.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
from typing import Any, cast
from urllib.request import Request

import httpx

from docmost_client.errors import (
    AuthenticationError,
    DocmostError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    UpstreamError,
)
from docmost_client.settings import DocmostSettings

AUTH_COOKIE = "authToken"
LOGIN_PATH = "/auth/login"
LOGOUT_PATH = "/auth/logout"
_MAX_SERVER_MESSAGE = 500


class ServerClock:
    """Docmost's clock, estimated from the ``Date`` header of its latest response.

    The header has one-second resolution and is stamped before the response travels, so
    the estimate lags slightly behind the server: a busy window measured on it errs
    toward refusing.
    """

    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._anchor: tuple[datetime, float] | None = None

    def observe(self, response: httpx.Response) -> None:
        value = response.headers.get("date")
        if not value:
            return
        try:
            server = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return
        if server.tzinfo is None:
            server = server.replace(tzinfo=UTC)
        self._anchor = (server, self._monotonic())

    def now(self) -> datetime | None:
        anchor = self._anchor
        if anchor is None:
            return None
        server, seen_at = anchor
        return server + timedelta(seconds=self._monotonic() - seen_at)


class _RejectAllCookies(DefaultCookiePolicy):
    """Cookie policy that never stores or sends a cookie."""

    def set_ok(self, cookie: Cookie, request: Request) -> bool:
        return False

    def return_ok(self, cookie: Cookie, request: Request) -> bool:
        return False


def client_options(settings: DocmostSettings, user_agent: str) -> dict[str, Any]:
    """Options for ``httpx.Client`` / ``httpx.AsyncClient``.

    Redirects are never followed so the bearer token cannot be forwarded to another
    host, and the cookie jar refuses every cookie so the token only travels as a
    bearer header that this module controls.
    """
    return {
        "base_url": f"{settings.base_url}/api",
        "timeout": settings.timeout_seconds,
        "follow_redirects": False,
        # Pass the jar itself: httpx copies a Cookies object into a default jar,
        # which would drop the policy.
        "cookies": CookieJar(policy=_RejectAllCookies()),
        "headers": {"user-agent": user_agent, "accept": "application/json"},
    }


def login_payload(settings: DocmostSettings) -> dict[str, str]:
    return {"email": settings.email, "password": settings.password.get_secret_value()}


def bearer(token: str | None) -> dict[str, str]:
    return {} if token is None else {"authorization": f"Bearer {token}"}


def transport_error(exc: httpx.HTTPError) -> UpstreamError:
    """Describe a transport failure without echoing request details."""
    return UpstreamError(f"Could not reach Docmost ({type(exc).__name__}).")


def token_from_login(response: httpx.Response) -> str:
    """Return the JWT set by a login response or raise a typed error."""
    if response.status_code in (400, 401, 403):
        detail = _server_message(response)
        raise AuthenticationError(
            "Docmost rejected the login; check DOCMOST_EMAIL and DOCMOST_PASSWORD"
            + (f" ({detail})." if detail else "."),
            status_code=response.status_code,
        )
    _raise_for_status(response)
    for header in response.headers.get_list("set-cookie"):
        name, _, rest = header.partition("=")
        value = rest.split(";", 1)[0].strip()
        if name.strip() == AUTH_COOKIE and value:
            return value
    raise AuthenticationError(
        "Docmost accepted the credentials but returned no session token. The account "
        "probably requires MFA or SSO, which this client does not support; use a "
        "dedicated service account with password login.",
        status_code=response.status_code,
    )


def unwrap(response: httpx.Response) -> Any:
    """Return the ``data`` of a successful response or raise a typed error."""
    _raise_for_status(response)
    body = _json(response)
    if body is _NOT_JSON:
        raise UpstreamError(
            "Docmost returned a response that is not JSON.", status_code=response.status_code
        )
    if isinstance(body, dict):
        return cast(dict[str, Any], body).get("data")
    return body


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    error_type = _ERRORS_BY_STATUS.get(status)
    if error_type is None:
        if 300 <= status < 400:
            raise UpstreamError(
                f"Docmost answered with a redirect (HTTP {status}); redirects are not "
                "followed. Check DOCMOST_BASE_URL.",
                status_code=status,
            )
        error_type = UpstreamError
    detail = _server_message(response)
    message = f"Docmost returned HTTP {status}" + (f": {detail}" if detail else ".")
    raise error_type(message, status_code=status)


_ERRORS_BY_STATUS: dict[int, type[DocmostError]] = {
    400: InvalidRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    413: InvalidRequestError,
    422: InvalidRequestError,
    429: RateLimitedError,
}


_NOT_JSON = object()


def _json(response: httpx.Response) -> object:
    try:
        return cast(object, response.json())
    except ValueError:
        return _NOT_JSON


def _server_message(response: httpx.Response) -> str:
    body = _json(response)
    if not isinstance(body, dict):
        return ""
    message = cast(dict[str, object], body).get("message")
    if isinstance(message, list):
        text = "; ".join(str(item) for item in cast(list[object], message))
    elif isinstance(message, str):
        text = message
    else:
        return ""
    return text[:_MAX_SERVER_MESSAGE]
