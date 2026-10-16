"""Seed a local, disposable Docmost 0.96.0 started from dev/docmost/compose.yaml.

Creates an admin, an "agent" member, three spaces and sample pages, then writes the
credentials to dev/docmost/.env.test (git-ignored). Refuses any non-local base URL.

    uv run python dev/docmost/bootstrap.py
"""

import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from docmost_client import DocmostClient, DocmostSettings

BASE_URL = "http://localhost:3000"
HERE = Path(__file__).parent
ENV_TEST = HERE / ".env.test"
DB_CONTAINER = "docmost-dev-db-1"
ADMIN_EMAIL = "admin@example.com"
AGENT_EMAIL = "agent@example.com"
INVITE_QUERY = "select id, token from workspace_invitations where email = 'agent@example.com'"

RICH_HTML = """\
<h2>Service matrix</h2>
<table><tbody>
<tr><th><p>Service</p></th><th><p>Owner</p></th></tr>
<tr><td><p>worker</p></td><td><p><mark data-color="#fde68a">platform</mark></p></td></tr>
</tbody></table>
<div data-type="callout" data-callout-type="warning"><p>Restart only during the window.</p></div>
<ul data-type="taskList"><li data-type="taskItem" data-checked="true"><p>Drain <strong>queue</strong></p></li></ul>
<details><summary>Rollback</summary><div data-type="detailsContent"><p>Use the previous image.</p></div></details>
<p><u>Underlined</u> and <span style="color: #dc2626">red</span> text with a <a href="https://example.com">link</a>.</p>
"""


def main() -> None:
    if urlsplit(BASE_URL).hostname not in {"localhost", "127.0.0.1"}:
        sys.exit("bootstrap.py only targets a local Docmost.")
    admin_password = secrets.token_urlsafe(18)
    agent_password = secrets.token_urlsafe(18)

    with httpx.Client(base_url=f"{BASE_URL}/api", timeout=30) as http:
        response = http.post(
            "/auth/setup",
            json={
                "name": "Admin",
                "email": ADMIN_EMAIL,
                "password": admin_password,
                "workspaceName": "Dev",
            },
        )
        if response.status_code >= 400:
            sys.exit(f"Setup failed (HTTP {response.status_code}); is the instance already set up?")
        admin = _admin_session(http, admin_password)

        spaces = {
            slug: _call(admin, "/spaces/create", {"name": name, "slug": slug})["id"]
            for slug, name in (
                ("engineering", "Engineering"),
                ("sandbox", "Sandbox"),
                ("ops", "Operations"),
            )
        }
        agent_id = _invite_agent(admin, agent_password)
        _call(
            admin,
            "/spaces/members/add",
            {
                "spaceId": spaces["engineering"],
                "role": "reader",
                "userIds": [agent_id],
                "groupIds": [],
            },
        )
        _call(
            admin,
            "/spaces/members/add",
            {"spaceId": spaces["sandbox"], "role": "writer", "userIds": [agent_id], "groupIds": []},
        )

    _seed_pages(admin_password)
    credentials = (
        f"DOCMOST_BASE_URL={BASE_URL}\n"
        "DOCMOST_ALLOW_INSECURE_HTTP=1\n"
        f"DOCMOST_ADMIN_EMAIL={ADMIN_EMAIL}\n"
        f"DOCMOST_ADMIN_PASSWORD={admin_password}\n"
        f"DOCMOST_EMAIL={AGENT_EMAIL}\n"
        f"DOCMOST_PASSWORD={agent_password}\n"
    )
    # Create the file with owner-only permissions from the start.
    fd = os.open(ENV_TEST, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(credentials)
    print(f"Seeded {BASE_URL}; credentials in {ENV_TEST.relative_to(Path.cwd())}")


def _admin_session(http: httpx.Client, password: str) -> httpx.Client:
    login = http.post("/auth/login", json={"email": ADMIN_EMAIL, "password": password})
    login.raise_for_status()
    token = login.cookies["authToken"]
    return httpx.Client(
        base_url=f"{BASE_URL}/api", timeout=30, headers={"authorization": f"Bearer {token}"}
    )


def _call(client: httpx.Client, path: str, payload: dict[str, object]) -> dict[str, object]:
    response = client.post(path, json=payload)
    if response.status_code >= 400:
        sys.exit(f"{path} failed: HTTP {response.status_code} {response.text[:300]}")
    body = response.json()
    return body.get("data") or {}


def _invite_agent(admin: httpx.Client, password: str) -> str:
    _call(
        admin,
        "/workspace/invites/create",
        {"emails": [AGENT_EMAIL], "role": "member", "groupIds": []},
    )
    # Invitation tokens are emailed; read it from the local database instead.
    row = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "docker",
            "exec",
            DB_CONTAINER,
            "psql",
            "-U",
            "docmost",
            "-d",
            "docmost",
            "-tA",
            "-c",
            INVITE_QUERY,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    invitation_id, token = row.split("|")
    with httpx.Client(base_url=f"{BASE_URL}/api", timeout=30) as anonymous:
        accepted = anonymous.post(
            "/workspace/invites/accept",
            json={
                "invitationId": invitation_id,
                "token": token,
                "name": "Agent",
                "password": password,
            },
        )
        accepted.raise_for_status()
    members = _call(admin, "/workspace/members", {"limit": 100})
    items = members.get("items")
    assert isinstance(items, list)
    return next(
        str(m["id"]) for m in items if isinstance(m, dict) and m.get("email") == AGENT_EMAIL
    )


def _seed_pages(admin_password: str) -> None:
    settings = DocmostSettings.from_env(
        {
            "DOCMOST_BASE_URL": BASE_URL,
            "DOCMOST_ALLOW_INSECURE_HTTP": "1",
            "DOCMOST_EMAIL": ADMIN_EMAIL,
            "DOCMOST_PASSWORD": admin_password,
            "DOCMOST_READ_ONLY": "0",
        }
    )
    with DocmostClient(settings) as admin:
        runbook = admin.create_page(
            space="engineering",
            title="Runbook",
            content="# Runbook\n\nRestart the worker pool when the queue backs up.\n\n- Check metrics\n- Drain the queue\n",
        )
        admin.create_page(
            space="engineering",
            title="Restart procedure",
            parent_page_id=runbook.id,
            content="Stop the worker, then start it again.",
        )
        admin.create_page(space="engineering", title="Rich page", content=RICH_HTML, format="html")
        admin.create_page(space="sandbox", title="Scratch", content="Agent playground.")
        admin.create_page(space="ops", title="Ops secrets", content="Only admins should read this.")


if __name__ == "__main__":
    main()
