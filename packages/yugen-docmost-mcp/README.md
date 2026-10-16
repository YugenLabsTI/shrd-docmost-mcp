# yugen-docmost-mcp

> **Unofficial, not affiliated with Docmost.**

Security-first MCP server that lets AI agents search, read, and optionally write a
self-hosted **Docmost Community Edition** wiki (tested with Docmost 0.96.0).

```bash
DOCMOST_BASE_URL=https://wiki.example.com \
DOCMOST_EMAIL=agent@example.com \
DOCMOST_PASSWORD_FILE=/run/secrets/docmost_password \
yugen-docmost-mcp
```

Tools: `search`, `list_spaces`, `list_children`, `get_page`, and, only when
`DOCMOST_READ_ONLY=0`, `create_page` and `update_page`.

See the [project README](../../README.md) for configuration, the tool reference, the
security model, and the compatibility matrix.
