"""Record Docmost 0.96.0 responses from the local dev instance as contract fixtures.

Runs as the seeded agent (dev/docmost/.env.test) and writes the unwrapped ``data`` of
each response to packages/docmost-client/tests/fixtures/v0_96_0/recorded/, plus raw
error bodies under recorded/errors/. Refuses any non-local base URL. Writes only to the
sandbox space.

    set -a; . dev/docmost/.env.test; set +a
    uv run python dev/docmost/record_fixtures.py
"""

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from docmost_client import DocmostClient, DocmostSettings, Session

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "packages/docmost-client/tests/fixtures/v0_96_0/recorded"


def main() -> None:
    settings = DocmostSettings.from_env()
    if urlsplit(settings.base_url).hostname not in {"localhost", "127.0.0.1"}:
        sys.exit("record_fixtures.py only targets a local Docmost.")
    (OUT / "errors").mkdir(parents=True, exist_ok=True)

    with DocmostClient(settings) as client:
        runbook = next(
            hit
            for hit in client.search("worker", space="engineering").hits
            if hit.title == "Runbook"
        )
        engineering = client.get_space("engineering")
        sandbox = client.get_space("sandbox")

    writable = settings.model_copy(update={"read_only": False})
    with Session(writable) as session:
        _save("users_me", session.call("/users/me"))
        _save("version", session.call("/version"))
        _save("spaces_list", session.call("/spaces", {"limit": 20}))
        _save("space_info", session.call("/spaces/info", {"spaceId": "engineering"}))
        for fmt in ("markdown", "html", "json"):
            _save(
                f"page_info_{fmt}",
                session.call("/pages/info", {"pageId": runbook.id, "format": fmt}),
            )
        _save(
            "sidebar_pages",
            session.call("/pages/sidebar-pages", {"pageId": runbook.id, "limit": 20}),
        )
        _save(
            "sidebar_root_pages",
            session.call("/pages/sidebar-pages", {"spaceId": engineering.id, "limit": 20}),
        )
        _save("search", session.call("/search", {"query": "worker", "limit": 10, "offset": 0}))
        created = session.call(
            "/pages/create",
            {
                "spaceId": sandbox.id,
                "title": "Recorded",
                "content": "First line",
                "format": "markdown",
            },
        )
        _save("page_create", created)
        _save(
            "page_update",
            session.call(
                "/pages/update",
                {
                    "pageId": created["id"],
                    "content": "Appended line",
                    "operation": "append",
                    "format": "markdown",
                },
            ),
        )

    _record_errors(settings, runbook.id, sandbox.id)
    print(f"Recorded fixtures into {OUT.relative_to(ROOT)}")


def _record_errors(settings: DocmostSettings, page_id: str, sandbox_id: str) -> None:
    """Raw error bodies, which the client never returns as data."""
    password = settings.password.get_secret_value()
    with httpx.Client(base_url=f"{settings.base_url}/api", timeout=60) as http:
        login = http.post("/auth/login", json={"email": settings.email, "password": password})
        token = login.cookies["authToken"]
        http.cookies.clear()
        auth = {"authorization": f"Bearer {token}"}
        cases: dict[str, tuple[str, dict[str, Any]]] = {
            "space_not_member": ("/spaces/info", {"spaceId": "ops"}),
            "page_not_found": ("/pages/info", {"pageId": "0192b7a4-0000-7000-8000-00000000dead"}),
            "update_without_operation": (
                "/pages/update",
                {"pageId": page_id, "content": "x", "format": "markdown"},
            ),
            "content_without_format": (
                "/pages/create",
                {"spaceId": sandbox_id, "title": "No format", "content": "x"},
            ),
            "write_as_reader": (
                "/pages/update",
                {"pageId": page_id, "content": "x", "operation": "append", "format": "markdown"},
            ),
            "body_too_large": (
                "/pages/create",
                {
                    "spaceId": sandbox_id,
                    "title": "Big",
                    "content": "x" * 1_100_000,
                    "format": "markdown",
                },
            ),
        }
        for name, (path, payload) in cases.items():
            response = http.post(path, json=payload, headers=auth)
            _save_error(name, response)
        http.post("/auth/logout", headers=auth)
        wrong = {"email": settings.email, "password": "wrong-password"}
        _save_error("login_rejected", http.post("/auth/login", json=wrong))
        # Last: exceed the login rate limit (10/min/IP). Blocks logins for a minute.
        for _ in range(10):
            response = http.post("/auth/login", json=wrong)
        _save_error("login_rate_limited", response)


def _save(name: str, data: Any) -> None:
    (OUT / f"{name}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )


def _save_error(name: str, response: httpx.Response) -> None:
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text[:2000]
    record = {"status": response.status_code, "body": body}
    (OUT / "errors" / f"{name}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
