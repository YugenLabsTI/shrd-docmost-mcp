"""Command-line entry point: ``yugen-docmost-mcp`` serves MCP over stdio."""

import logging
import sys
from collections.abc import Sequence
from typing import Any

from mcp.server.mcpserver import MCPServer

from docmost_client import AsyncDocmostClient, ConfigError, DocmostSettings
from yugen_docmost_mcp._version import __version__
from yugen_docmost_mcp.server import build_server


def create_server(settings: DocmostSettings) -> MCPServer[Any]:
    """Build the server for ``settings``; write tools exist only when writes are enabled."""
    client = AsyncDocmostClient(settings)
    writer = None if settings.read_only else client
    return build_server(client, writer, on_shutdown=client.aclose)


def main(argv: Sequence[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--version" in args:
        sys.stdout.write(f"yugen-docmost-mcp {__version__}\n")
        raise SystemExit(0)
    # stdout carries the MCP protocol; logs go to stderr. Request and response
    # bodies are never logged.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    try:
        settings = DocmostSettings.from_env()
    except ConfigError as exc:
        sys.stderr.write(f"yugen-docmost-mcp: {exc}\n")
        raise SystemExit(2) from None
    create_server(settings).run("stdio")


if __name__ == "__main__":
    main()
