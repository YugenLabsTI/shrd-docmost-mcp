"""Smoke test against the real Docmost instance configured in dev/live/.env.live.

    uv run python dev/live/smoke.py           # read-only checks
    uv run python dev/live/smoke.py --write   # also writes ONE page in the sandbox space

Runs the offline --check gate first and stops if it fails. Prints identifiers, counts,
roles and outcomes only: never page content, the password, or the session token.
The page created by --write is left in the sandbox (the client has no delete operation);
its ID is printed so it can be deleted from the Docmost UI.
"""

import argparse
import asyncio
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import init_env

from docmost_client import (
    DocmostClient,
    DocmostError,
    DocmostSettings,
    ReadOnlyError,
    StalePageError,
)

failures: list[str] = []


def step(name: str, action: Callable[[], str]) -> None:
    try:
        detail = action()
    except AssertionError as exc:
        failures.append(name)
        print(f"FAIL  {name}: {exc}")
    except DocmostError as exc:
        failures.append(name)
        print(f"FAIL  {name}: {exc.code} {exc}")
    else:
        print(f"ok    {name}: {detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="also write one sandbox page")
    args = parser.parse_args()

    if init_env.check() != 0:
        sys.exit("Fix dev/live/.env.live first.")
    env = init_env._parse(init_env.ENV_FILE.read_text())
    read_space, sandbox = env["DOCMOST_LIVE_READ_SPACE"], env["DOCMOST_LIVE_SANDBOX_SPACE"]
    settings = DocmostSettings.from_env(env)

    with DocmostClient(settings) as client:
        read_checks(client, read_space, sandbox)
    asyncio.run(mcp_checks(settings, read_space))
    if args.write and failures:
        sys.exit("\nRead checks failed; not running --write.")
    if args.write:
        writable = settings.model_copy(update={"read_only": False})
        with DocmostClient(writable) as client:
            write_checks(client, read_space, sandbox)

    print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'All checks passed.'}")
    sys.exit(1 if failures else 0)


def read_checks(client: DocmostClient, read_space: str, sandbox: str) -> None:
    def compatibility() -> str:
        report = client.check_compatibility()
        return f"Docmost {report.docmost_version or 'unknown'} ({report.status})"

    def visible_spaces() -> str:
        slugs = {space.slug.lower() for space in client.list_spaces(limit=100).items}
        allowed = {read_space.lower(), sandbox.lower()}
        assert slugs <= allowed, (
            f"spaces outside the allowlist are visible: {sorted(slugs - allowed)}"
        )
        return f"{len(slugs)} visible, all inside the allowlist"

    def roles() -> str:
        read_role = client.get_space(read_space).role
        sandbox_role = client.get_space(sandbox).role
        assert sandbox_role in {"writer", "admin"}, f"sandbox role is {sandbox_role}, not writer"
        # A writer role would let --write tests reach real pages: refuse to go on.
        assert read_role == "reader", f"read space role is {read_role}; it must be reader"
        return f"read space={read_role}, sandbox={sandbox_role}"

    step("compatibility", compatibility)
    step("account", lambda: f"role {client.me().role}")
    step("allowlist hides other spaces", visible_spaces)
    step("space roles", roles)

    pages = client.list_children(space=read_space).items
    step("page tree", lambda: f"{len(pages)} top-level pages in {read_space}")
    if not pages:
        print("skip  search/read: the read space has no pages")
        return
    first = pages[0]

    def search() -> str:
        words = (first.title or "").split()
        assert words, "first page has no title to search for"
        hits = client.search(words[0], space=read_space, title_only=True).hits
        assert any(hit.id == first.id for hit in hits), "first page not found by its title"
        return f"{len(hits)} hits for its first title word, page found"

    def read(fmt: Any) -> Callable[[], str]:
        def run() -> str:
            page = client.get_page(first.id, format=fmt)
            size = len(page.content) if isinstance(page.content, str) else "-"
            return f"{fmt}: {size} chars, updated_at {page.updated_at.isoformat()}, can_edit={page.can_edit}"

        return run

    def refused() -> str:
        try:
            client.create_page(space=sandbox, title="never")
        except ReadOnlyError:
            return "write refused locally (READ_ONLY)"
        raise AssertionError("read-only client accepted a write")

    step("search", search)
    step("read markdown", read("markdown"))
    step("read html", read("html"))
    step("read-only refusal", refused)


async def mcp_checks(settings: DocmostSettings, read_space: str) -> None:
    from mcp import Client

    from yugen_docmost_mcp.__main__ import create_server

    async with Client(create_server(settings)) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        expected = {"search", "list_spaces", "get_page", "list_children"}
        ok = names == expected
        print(f"{'ok   ' if ok else 'FAIL '} mcp tools: {sorted(names)}")
        if not ok:
            failures.append("mcp tools")
        result = await client.call_tool("list_children", {"space": read_space})
        if result.is_error:
            failures.append("mcp list_children")
            print(f"FAIL  mcp list_children: {result.structured_content}")
        else:
            count = len(result.structured_content["pages"])
            print(f"ok    mcp list_children: {count} pages")


def write_checks(client: DocmostClient, read_space: str, sandbox: str) -> None:
    def role_barrier() -> str:
        # Read-only check: never send an update outside the sandbox.
        pages = client.list_children(space=read_space).items
        if not pages:
            return "skipped (no page in the read space)"
        page = client.get_page(pages[0].id)
        assert page.can_edit is False, "the account can edit the read space"
        return "account cannot edit the read space (checked without writing)"

    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    created: dict[str, str] = {}

    def create() -> str:
        page = client.create_page(
            space=sandbox,
            title=f"yugen-docmost-mcp smoke test {stamp}",
            content="Created by the live smoke test. Safe to delete.",
        )
        created["id"] = page.id
        return f"page {page.id} (slug {page.slug_id}) created in {sandbox}"

    def append_and_stale() -> str:
        before = client.get_page(created["id"])
        after = client.update_page(
            created["id"],
            content="Appended by the smoke test.",
            operation="append",
            expected_updated_at=before.updated_at,
        )
        assert isinstance(after.content, str)
        assert "Appended by the smoke test." in after.content, "appended text missing"
        try:
            client.update_page(
                created["id"],
                content="never",
                operation="append",
                expected_updated_at=before.updated_at,
            )
        except StalePageError:
            return "append landed; stale update refused before sending"
        raise AssertionError("a stale update was accepted")

    step("role barrier on the read space", role_barrier)
    step("create in sandbox", create)
    if "id" in created:
        step("append + stale precheck", append_and_stale)
        print(f"\nDelete the test page from the Docmost UI when done: {created['id']}")


if __name__ == "__main__":
    main()
