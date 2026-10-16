# Changelog

All notable changes to this project are documented here. Both packages follow
[Semantic Versioning](https://semver.org/); the public API of `docmost-client` is what
`docmost_client.__all__` exports.

## Unreleased

### Block 1

- `DOCMOST_ALLOW_COMMENTS` (off by default, independent of `DOCMOST_READ_ONLY`) enables
  `add_comment`; `list_comments` and `list_recent_pages` are new read tools.
- Client: `list_comments`, `create_comment`, `list_recent_pages`, models `Comment` and
  `RecentPage`, error `CommentsDisabledError`.
- `update_page` asks the user to confirm a `replace` (`DOCMOST_CONFIRM_REPLACE`, on by
  default); new error codes `CONFIRMATION_DECLINED` and `CONFIRMATION_UNAVAILABLE`.

### docmost-client 0.1.0

- Settings from `DOCMOST_*` environment variables with secure defaults.
- `Session` / `AsyncSession`: in-memory JWT, single-flight login, one re-login on 401,
  logout on close, typed errors.
- `DocmostClient` / `AsyncDocmostClient`: `me`, `list_spaces`, `get_space`, `get_page`,
  `list_children`, `search`, `check_compatibility`, `create_page`, `update_page`.
- Space allowlist, read-only mode, and content guards enforced inside the client.
- Supports Docmost 0.96.0.

### yugen-docmost-mcp 0.1.0

- stdio MCP server with `search`, `list_spaces`, `get_page`, `list_children`, and
  (when writes are enabled) `create_page` and `update_page`.
- Structured results and typed error codes.
