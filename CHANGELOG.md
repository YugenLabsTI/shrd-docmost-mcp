# Changelog

All notable changes to this project are documented here. Both packages follow
[Semantic Versioning](https://semver.org/); the public API of `docmost-client` is what
`docmost_client.__all__` exports.

## Unreleased

### Fixed

- The `docmost://space/{space}/tree` resource keeps the pages it already fetched when its
  request budget runs out in the middle of a level, instead of dropping that level.
- A prompt file that clashes with a built-in prompt is named in the startup error.
- `DOCMOST_BUSY_WINDOW_SECONDS` accepts only plain ASCII digits (no `+`, `_` or other
  scripts' digits).
- Client: `PageBusyError.after(seconds)` builds the standard busy error.

### Resources and prompts

- Read-only MCP resources: `docmost://page/{page_id}` (markdown), `docmost://space/{space}/tree`
  (bounded page tree) and `docmost://recent`; they respect `DOCMOST_ALLOWED_SPACES`.
- Generic prompts `summarize_page` and `answer_from_wiki`, hidden with
  `DOCMOST_BUILTIN_PROMPTS=0`.
- Team prompts from TOML files in `DOCMOST_PROMPTS_DIR` (`name`, `title`, `description`,
  `template` with `{{argument}}` placeholders, `[[arguments]]` with `required` or
  `default`), validated at startup; see `examples/prompts/`.

### Busy window settings

- `DOCMOST_BUSY_WINDOW_SECONDS` (default `60`, from `45` to `86400`) sets how recently
  saved a page must be for `edit_section` to refuse it with `PAGE_BUSY`.
- When Docmost's clock and the local clock differ by more than 5 minutes, section edits
  fail with the new `CLOCK_SKEW` error (`ClockSkewError`) instead of keeping every page
  busy or switching the protection off; only successful responses update Docmost's clock.
- Client: `busy_retry_after(updated_at)` on both clients; `busy_retry_after` takes an
  optional `window`.

### Section editing follow-ups

- `update_page` and `edit_section` keep mentions already on the page (matched by entity
  type and id) and still refuse new ones, so a page with mentions can be edited round
  trip as html or json. `create_page` still refuses all mentions.
- The busy window is measured on the earlier of Docmost's clock (from the `Date` header
  of its latest response) and the local clock; `busy_retry_after` takes an optional
  `now`. Client: `server_now()`.
- Section edits refuse new headings that reuse an id already on the page and raw-text
  elements (`script`, `style`, `iframe`, ...); `NOT_FOUND` tells a nested heading apart
  from an id that is not a heading.

### Section editing

- `get_page_outline` (read) lists a page's top-level headings; `edit_section` (write)
  replaces, prepends to, or appends to one section by heading id, in HTML.
- A section edit is refused with `PAGE_BUSY` when the page was saved in the last 60
  seconds, and otherwise asks the user to confirm (`DOCMOST_CONFIRM_REPLACE`).
- Client: `get_page_outline`, `edit_section`, models `PageOutline` and `Heading`, error
  `PageBusyError`, `busy_retry_after`.

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
