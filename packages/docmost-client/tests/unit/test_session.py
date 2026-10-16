"""Session behavior shared by the sync and async transports."""

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol

import anyio
import httpx
import pytest
import respx

from docmost_client import (
    AsyncSession,
    AuthenticationError,
    DocmostSettings,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    Session,
    UpstreamError,
)

BASE = "https://wiki.example.com"
API = f"{BASE}/api"
PASSWORD = "s3cr3t-Pa55word!"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.first.signature"
TOKEN_2 = "eyJhbGciOiJIUzI1NiJ9.second.signature"


def settings() -> DocmostSettings:
    return DocmostSettings.from_env(
        {
            "DOCMOST_BASE_URL": BASE,
            "DOCMOST_EMAIL": "bot@example.com",
            "DOCMOST_PASSWORD": PASSWORD,
        }
    )


def login_ok(token: str = TOKEN) -> httpx.Response:
    return httpx.Response(
        200,
        json={"success": True, "status": 200},
        headers={"set-cookie": f"authToken={token}; Path=/; HttpOnly; SameSite=Lax"},
    )


def wrapped(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "success": True, "status": 200})


class Caller(Protocol):
    async def call(self, path: str, payload: Mapping[str, Any] | None = None) -> Any: ...

    async def close(self) -> None: ...


class SyncCaller:
    def __init__(self) -> None:
        self.session = Session(settings())

    async def call(self, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        return self.session.call(path, payload)

    async def close(self) -> None:
        self.session.close()


class AsyncCaller:
    def __init__(self) -> None:
        self.session = AsyncSession(settings())

    async def call(self, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        return await self.session.call(path, payload)

    async def close(self) -> None:
        await self.session.aclose()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def api(respx_mock: respx.MockRouter) -> respx.MockRouter:
    respx_mock.post(f"{API}/auth/logout", name="logout").mock(
        return_value=httpx.Response(200, json={"success": True, "status": 200})
    )
    return respx_mock


@pytest.fixture(params=["sync", "async"])
async def caller(request: pytest.FixtureRequest, api: respx.MockRouter) -> AsyncIterator[Caller]:
    del api
    instance: Caller = SyncCaller() if request.param == "sync" else AsyncCaller()
    yield instance
    await instance.close()


pytestmark = [pytest.mark.anyio, pytest.mark.respx(assert_all_called=False)]


async def test_logs_in_once_and_sends_bearer_token_only(
    caller: Caller, api: respx.MockRouter
) -> None:
    login = api.post(f"{API}/auth/login").mock(return_value=login_ok())
    me = api.post(f"{API}/users/me").mock(return_value=wrapped({"user": {"id": "u1"}}))

    assert await caller.call("/users/me") == {"user": {"id": "u1"}}
    assert await caller.call("/users/me") == {"user": {"id": "u1"}}

    assert login.call_count == 1
    assert login.calls[0].request.read() == (
        b'{"email":"bot@example.com","password":"s3cr3t-Pa55word!"}'
    )
    for call in me.calls:
        assert call.request.headers["authorization"] == f"Bearer {TOKEN}"
        assert "cookie" not in call.request.headers


async def test_sends_json_payload(caller: Caller, api: respx.MockRouter) -> None:
    api.post(f"{API}/auth/login").mock(return_value=login_ok())
    info = api.post(f"{API}/pages/info").mock(return_value=wrapped({"id": "p1"}))

    await caller.call("/pages/info", {"pageId": "p1", "format": "markdown"})

    assert info.calls[0].request.read() == b'{"pageId":"p1","format":"markdown"}'
    assert info.calls[0].request.headers["content-type"] == "application/json"


async def test_relogs_in_once_on_401_and_retries(caller: Caller, api: respx.MockRouter) -> None:
    login = api.post(f"{API}/auth/login").mock(side_effect=[login_ok(), login_ok(TOKEN_2)])
    me = api.post(f"{API}/users/me").mock(
        side_effect=[
            wrapped({"n": 1}),
            httpx.Response(401, json={"message": "Unauthorized", "statusCode": 401}),
            wrapped({"n": 2}),
        ]
    )

    await caller.call("/users/me")
    assert await caller.call("/users/me") == {"n": 2}

    assert login.call_count == 2
    assert me.calls[-1].request.headers["authorization"] == f"Bearer {TOKEN_2}"


async def test_gives_up_when_retry_after_relogin_is_still_401(
    caller: Caller, api: respx.MockRouter
) -> None:
    login = api.post(f"{API}/auth/login").mock(side_effect=[login_ok(), login_ok(TOKEN_2)])
    api.post(f"{API}/users/me").mock(
        return_value=httpx.Response(401, json={"message": "Unauthorized", "statusCode": 401})
    )

    with pytest.raises(AuthenticationError) as exc:
        await caller.call("/users/me")

    assert exc.value.code == "AUTH_FAILED"
    assert exc.value.status_code == 401
    assert login.call_count == 2


async def test_login_without_cookie_is_reported_as_auth_failure(
    caller: Caller, api: respx.MockRouter
) -> None:
    api.post(f"{API}/auth/login").mock(
        return_value=wrapped({"userHasMfa": True, "requiresMfaSetup": False})
    )

    with pytest.raises(AuthenticationError, match="MFA"):
        await caller.call("/users/me")


@pytest.mark.parametrize("status", [400, 401])
async def test_rejected_login_never_echoes_the_password(
    caller: Caller, api: respx.MockRouter, status: int
) -> None:
    api.post(f"{API}/auth/login").mock(
        return_value=httpx.Response(
            status, json={"message": "Email or password does not match", "statusCode": status}
        )
    )

    with pytest.raises(AuthenticationError) as exc:
        await caller.call("/users/me")

    assert PASSWORD not in str(exc.value)
    assert "DOCMOST_EMAIL" in str(exc.value)


@pytest.mark.parametrize(
    ("status", "error", "code"),
    [
        (400, InvalidRequestError, "INVALID_INPUT"),
        (403, PermissionDeniedError, "FORBIDDEN"),
        (404, NotFoundError, "NOT_FOUND"),
        (413, InvalidRequestError, "INVALID_INPUT"),
        (429, RateLimitedError, "RATE_LIMITED"),
        (500, UpstreamError, "UPSTREAM_ERROR"),
        (502, UpstreamError, "UPSTREAM_ERROR"),
    ],
)
async def test_http_errors_map_to_typed_errors(
    caller: Caller, api: respx.MockRouter, status: int, error: type[Exception], code: str
) -> None:
    api.post(f"{API}/auth/login").mock(return_value=login_ok())
    api.post(f"{API}/pages/info").mock(
        return_value=httpx.Response(
            status, json={"message": "Page not found", "error": "x", "statusCode": status}
        )
    )

    with pytest.raises(error) as exc:
        await caller.call("/pages/info", {"pageId": "p1"})

    assert getattr(exc.value, "code", None) == code
    assert getattr(exc.value, "status_code", None) == status


async def test_validation_messages_are_joined(caller: Caller, api: respx.MockRouter) -> None:
    api.post(f"{API}/auth/login").mock(return_value=login_ok())
    api.post(f"{API}/pages/update").mock(
        return_value=httpx.Response(
            400,
            json={
                "message": ["operation must be one of append, prepend, replace", "bad format"],
                "error": "Bad Request",
                "statusCode": 400,
            },
        )
    )

    with pytest.raises(InvalidRequestError, match=r"operation must be one of.*; bad format"):
        await caller.call("/pages/update", {"pageId": "p1"})


async def test_login_rate_limit_is_typed(caller: Caller, api: respx.MockRouter) -> None:
    api.post(f"{API}/auth/login").mock(
        return_value=httpx.Response(429, json={"message": "Too many requests", "statusCode": 429})
    )

    with pytest.raises(RateLimitedError):
        await caller.call("/users/me")


async def test_redirects_are_not_followed(caller: Caller, api: respx.MockRouter) -> None:
    api.post(f"{API}/auth/login").mock(return_value=login_ok())
    api.post(f"{API}/users/me").mock(
        return_value=httpx.Response(302, headers={"location": "https://evil.example.net/"})
    )

    with pytest.raises(UpstreamError, match="302"):
        await caller.call("/users/me")


async def test_network_errors_are_typed_and_do_not_leak_token(
    caller: Caller, api: respx.MockRouter
) -> None:
    api.post(f"{API}/auth/login").mock(return_value=login_ok())
    api.post(f"{API}/users/me").mock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(UpstreamError) as exc:
        await caller.call("/users/me")

    assert TOKEN not in str(exc.value)
    assert exc.value.__cause__ is None


async def test_non_json_success_is_an_upstream_error(caller: Caller, api: respx.MockRouter) -> None:
    api.post(f"{API}/auth/login").mock(return_value=login_ok())
    api.post(f"{API}/users/me").mock(return_value=httpx.Response(200, text="<html>proxy</html>"))

    with pytest.raises(UpstreamError):
        await caller.call("/users/me")


async def test_close_logs_out_to_revoke_the_server_session(
    caller: Caller, api: respx.MockRouter
) -> None:
    api.post(f"{API}/auth/login").mock(return_value=login_ok())
    api.post(f"{API}/users/me").mock(return_value=wrapped({}))
    logout = api.routes["logout"]

    await caller.call("/users/me")
    await caller.close()

    assert logout.call_count == 1
    assert logout.calls[0].request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_close_without_login_does_not_call_logout(
    caller: Caller, api: respx.MockRouter
) -> None:
    logout = api.routes["logout"]

    await caller.close()

    assert logout.call_count == 0


async def test_close_ignores_logout_failures(caller: Caller, api: respx.MockRouter) -> None:
    api.post(f"{API}/auth/login").mock(return_value=login_ok())
    api.post(f"{API}/users/me").mock(return_value=wrapped({}))
    api.routes["logout"].mock(side_effect=httpx.ConnectError("down"))

    await caller.call("/users/me")
    await caller.close()


async def test_session_repr_never_contains_secrets(api: respx.MockRouter) -> None:
    api.post(f"{API}/auth/login").mock(return_value=login_ok())
    api.post(f"{API}/users/me").mock(return_value=wrapped({}))
    async with AsyncSession(settings()) as session:
        await session.call("/users/me")
        assert TOKEN not in repr(session)
        assert PASSWORD not in repr(session)


async def test_concurrent_async_calls_share_a_single_login(api: respx.MockRouter) -> None:
    login = api.post(f"{API}/auth/login").mock(return_value=login_ok())
    api.post(f"{API}/users/me").mock(return_value=wrapped({}))

    async with AsyncSession(settings()) as session, anyio.create_task_group() as group:
        for _ in range(5):
            group.start_soon(session.call, "/users/me")

    assert login.call_count == 1


def test_sync_session_is_a_context_manager(api: respx.MockRouter) -> None:
    api.post(f"{API}/auth/login").mock(return_value=login_ok())
    api.post(f"{API}/users/me").mock(return_value=wrapped({"ok": True}))
    logout = api.routes["logout"]

    with Session(settings()) as session:
        assert session.call("/users/me") == {"ok": True}

    assert logout.call_count == 1


async def test_uses_configured_base_path(api: respx.MockRouter) -> None:
    sub = DocmostSettings.from_env(
        {
            "DOCMOST_BASE_URL": f"{BASE}/docmost",
            "DOCMOST_EMAIL": "bot@example.com",
            "DOCMOST_PASSWORD": PASSWORD,
        }
    )
    api.post(f"{BASE}/docmost/api/auth/login").mock(return_value=login_ok())
    me = api.post(f"{BASE}/docmost/api/users/me").mock(return_value=wrapped({}))
    api.post(f"{BASE}/docmost/api/auth/logout").mock(return_value=httpx.Response(200, json={}))

    async with AsyncSession(sub) as session:
        await session.call("/users/me")

    assert me.call_count == 1
