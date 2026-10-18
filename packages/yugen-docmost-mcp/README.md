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

Read tools: `search`, `list_spaces`, `list_children`, `get_page`, `get_page_outline`,
`list_recent_pages` and `list_comments`. Only when enabled: `add_comment`, `create_page`,
`update_page`, `edit_section` and `move_page`.

See the [project README](https://github.com/YugenLabsTI/shrd-docmost-mcp#readme) for configuration, the tool reference, the
security model, and the compatibility matrix.
