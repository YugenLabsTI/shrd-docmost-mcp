# shrd-docmost-mcp

> **Unofficial, not affiliated with Docmost.** Docmost is a trademark of its owners.

A security-first MCP server and Python client that let AI agents search, read, and
(optionally) write a **self-hosted Docmost Community Edition** wiki. Docmost's own MCP
server and public API require a Business/Enterprise license; this project talks to the
internal API the Docmost web app uses, with read-only access by default.

| Package | PyPI name | What it is |
|---------|-----------|------------|
| [`packages/docmost-client`](packages/docmost-client) | `docmost-client` | Typed sync + async Python client |
| [`packages/yugen-docmost-mcp`](packages/yugen-docmost-mcp) | `yugen-docmost-mcp` | MCP server (stdio) built on the client |

## Quick path

1. Create a dedicated Docmost account for the agent and add it only to the spaces it
   needs, with the lowest role that works (reader for read-only use). Docmost also adds
   new members to the default space as writers: remove it there or use
   `DOCMOST_ALLOWED_SPACES`.
2. Configure your MCP host to run the server with that account:

   ```json
   {
     "mcpServers": {
       "docmost": {
         "command": "uvx",
         "args": ["yugen-docmost-mcp"],
         "env": {
           "DOCMOST_BASE_URL": "https://wiki.example.com",
           "DOCMOST_EMAIL": "agent@example.com",
           "DOCMOST_PASSWORD_FILE": "/run/secrets/docmost_password",
           "DOCMOST_ALLOWED_SPACES": "engineering,runbooks"
         }
       }
     }
   }
   ```

   Until the packages are published, run from a checkout instead:
   `"command": "uv", "args": ["run", "--directory", "/path/to/shrd-docmost-mcp", "yugen-docmost-mcp"]`.
3. Ask the agent to search the wiki. Writes stay disabled until you set
   `DOCMOST_READ_ONLY=0`.

## Configuration

All settings come from environment variables. Nothing is written to disk.

| Variable | Default | Meaning |
|----------|---------|---------|
| `DOCMOST_BASE_URL` | required | Instance URL. Must be `https://` unless `DOCMOST_ALLOW_INSECURE_HTTP=1`. No credentials, query, or fragment. |
| `DOCMOST_EMAIL` / `DOCMOST_EMAIL_FILE` | required | Login email, or a file containing it. |
| `DOCMOST_PASSWORD` / `DOCMOST_PASSWORD_FILE` | required | Password, or a file containing it (preferred). |
| `DOCMOST_READ_ONLY` | `1` | Set to `0` to enable `create_page` and `update_page`. |
| `DOCMOST_ALLOW_COMMENTS` | `0` | Set to `1` to enable `add_comment`, independently of `DOCMOST_READ_ONLY`. |
| `DOCMOST_CONFIRM_REPLACE` | `1` | Ask the user to confirm every `replace` (see below). `0` skips the question. |
| `DOCMOST_ALLOWED_SPACES` | all the account's spaces | Comma-separated space slugs or IDs. Set but empty is an error. |
| `DOCMOST_ALLOW_INSECURE_HTTP` | `0` | Allow `http://` base URLs (local development only). |
| `DOCMOST_ALLOW_UNTESTED_VERSION` | `0` | Connect to a Docmost version not in the compatibility matrix. |
| `DOCMOST_TIMEOUT_SECONDS` | `30` | Per-request timeout. |
| `DOCMOST_MAX_CONTENT_BYTES` | `1000000` | Largest content a write may send (encoded size). |
| `DOCMOST_BUSY_WINDOW_SECONDS` | `60` | `edit_section` refuses pages saved this recently (`PAGE_BUSY`). From `45` (Docmost's editor save delay) to `86400`. |

The account must log in with email and password: accounts that require MFA or SSO are
not supported.

### What the agent may do

Two independent switches decide which write tools exist. Reading pages and comments is
always allowed.

| `DOCMOST_READ_ONLY` | `DOCMOST_ALLOW_COMMENTS` | The agent can |
|---|---|---|
| `1` (default) | `0` (default) | read pages and comments |
| `1` | `1` | read, and comment (a reader that comments) |
| `0` | `0` | read, create and edit pages, but not comment |
| `0` | `1` | everything above |

Docmost applies its own permissions on top: the account can comment where it can edit the
page. Letting readers comment ("viewer comments") is an Enterprise feature, so on
Community Edition an agent that comments needs the `writer` role in those spaces. In that
setup `DOCMOST_READ_ONLY=1` is what stops it from editing pages: the server does not
register the page write tools and the client refuses page writes. Keep the writer role
to the spaces where comments are wanted and list them in `DOCMOST_ALLOWED_SPACES`.

### Confirming a replace

`update_page` with `operation: replace` deletes the whole page body, including recent
edits by other people. With `DOCMOST_CONFIRM_REPLACE=1` (the default) the server asks the
user through the MCP host before writing:

- confirmed: the replace goes ahead;
- declined or cancelled: nothing is written (`CONFIRMATION_DECLINED`);
- the host cannot ask (no MCP elicitation support): nothing is written
  (`CONFIRMATION_UNAVAILABLE`). Use `append`/`prepend`, or set `DOCMOST_CONFIRM_REPLACE=0`
  for that host.

`append`, `prepend` and title changes never ask.

### Editing one section

`edit_section` changes one section instead of the whole page. The agent reads the
outline with `get_page_outline`, picks a heading by its id, and sends HTML content:

- `replace` swaps the section body (subsections included; the heading stays);
- `prepend` inserts right after the heading;
- `append` inserts at the end of the section, before the next heading of the same or a
  higher level.

Docmost can only save whole pages, so the server splices the section into the page's
HTML and writes the whole page back. Edits someone is typing in the browser are saved
up to ~45 s late and would be lost, so two protections apply:

1. if the page was saved in the last 60 seconds (`DOCMOST_BUSY_WINDOW_SECONDS`), the
   call fails with `PAGE_BUSY` (retryable, with `retry_after_seconds`) before anything
   is asked. The window is measured on the earlier of Docmost's clock (from the `Date`
   header of its successful responses) and the local one, so a small skew on either
   side cannot shorten it; when the two differ by more than 5 minutes, one of them is
   misconfigured and the local clock is used;
2. otherwise the user confirms the edit, like a `replace` (`DOCMOST_CONFIRM_REPLACE`).

The window only sees edits Docmost has already saved. Someone typing right now on a page
last saved long ago is not detected (Docmost does not expose who has a page open), so
the confirmation is what protects that case.

Only top-level headings can be targeted (not headings inside columns, callouts or
collapsible blocks). New content must be well-formed HTML: every element closed and
nested correctly, `<` written as `&lt;` in text, and no comments, `<!...>`/`<?...?>`
constructs or self-closed non-void elements such as `<div/>` (Docmost's parser would let
them swallow the rest of the page), and no `script`, `style`, `iframe`, `textarea` or
other raw-text elements. New headings cannot reuse an id another heading on the page
already has; leave `data-id`/`id` off new headings and Docmost assigns fresh ones.
Mentions follow the same rule as `update_page` (see below).

## MCP tools

| Tool | Mode | Use it to |
|------|------|-----------|
| `search` | read | Find pages by full text; returns snippets and page ids. |
| `list_spaces` | read | Discover the spaces the server can access. |
| `list_children` | read | Browse a space's page tree. |
| `get_page` | read | Read a page as `markdown` (default), `html`, or `json`. |
| `get_page_outline` | read | List a page's top-level headings (id, level, text) to target a section. |
| `list_recent_pages` | read | See what changed lately, across spaces or in one space. |
| `list_comments` | read | Read a page's comments (plain text, with resolved state and replies). |
| `add_comment` | comment | Add a page comment or a reply, in plain text. |
| `create_page` | write | Create a page, optionally under a parent, with initial content. |
| `update_page` | write | `append`, `prepend`, or `replace` content and/or rename a page. |
| `edit_section` | write | `replace`, `prepend`, or `append` within one section, in HTML. |

Failures return `is_error: true` with
`{"error": {"code": "...", "message": "...", "retryable": false}}`. Arguments that do not
match a tool's input schema (missing, wrong type, out of range) are rejected by the MCP
SDK before the tool runs, with an untyped error message. Codes:
`READ_ONLY`, `COMMENTS_DISABLED`, `CONFIRMATION_DECLINED`, `CONFIRMATION_UNAVAILABLE`,
`PAGE_BUSY`,
`SPACE_NOT_ALLOWED`, `STALE_PAGE`, `NOT_FOUND`, `FORBIDDEN`,
`INVALID_INPUT`, `AUTH_FAILED`, `RATE_LIMITED`, `UPSTREAM_ERROR`,
`UNSUPPORTED_VERSION`. Invalid configuration stops the server at startup with a message
on stderr.

### Choosing a content format

| Format | Read | Write | Use for |
|--------|------|-------|---------|
| `markdown` | Compact; drops comments, mentions, colors, diagrams, embeds | Every single newline becomes a line break | Reading, appending prose |
| `html` | Keeps nearly everything | Round-trips what was read | Replacing rich pages (read html, edit, write html) |
| `json` | The exact ProseMirror document | Lightly validated by Docmost | Precise structural edits |

Details and evidence: [docs/docmost-api-v0.96.0.md](docs/docmost-api-v0.96.0.md#5-content-formats-s5).

## Security model

Two independent barriers protect the wiki: the Docmost account's own permissions, and
this server's policy. Details in [SECURITY.md](SECURITY.md).

- Read-only by default. Write and comment tools are not even registered unless enabled,
  and the client refuses them on its own as well.
- A `replace` asks the user to confirm before anything is written.
- Comments are built from plain text by the client, so an agent cannot mention (and
  notify) users.
- The space allowlist is enforced inside the client for every read and write.
- The JWT lives only in memory. It is sent as a bearer header only; cookies are refused
  and redirects are never followed.
- Credentials, tokens, and page bodies are never logged or echoed in errors.
- Only mainstream Python dependencies; no binaries are downloaded.

## Compatibility

Docmost has no public API for Community Edition; this project uses its internal API,
which can change in any release. Each version below has contract fixtures and tests.

| docmost-client | yugen-docmost-mcp | Docmost |
|----------------|-------------------|---------|
| 0.1.x | 0.1.x | 0.96.0 |

On the first tool call the server asks Docmost for its version. An untested version is
refused unless `DOCMOST_ALLOW_UNTESTED_VERSION=1`. If Docmost cannot report its version
(it looks up GitHub releases to answer), the server continues and logs a warning.

## Known limitations

- **Concurrent edits.** Docmost has no compare-and-swap. `update_page` refuses when the
  page changed after the agent read it, but a change can still land between that check
  and the write, and browser edits are saved up to ~45 s late. `append` and `prepend`
  merge safely; `replace` overwrites.
- **Silent content drops.** If the server runs with `COLLAB_DISABLE_REDIS=true`, Docmost
  accepts content updates without applying them. The client detects this for `append`
  and `prepend`.
- **No new mentions.** Docmost notifies a user (in the app and by email) when a save
  adds a mention of someone who was not mentioned before. `update_page` and
  `edit_section` therefore keep mentions already on the page, matched by user or page id,
  and reject any other mention, so editing a page round-trip never notifies anyone.
  `create_page` rejects all mentions. Markdown drops mentions when reading, so edit pages
  with mentions as html or json.
- **Live editing.** What a `replace` does to text a user is typing at that moment has
  not been observed yet.

## Development

```bash
uv sync
uv run pytest            # tests (HTTP mocked with respx; no Docmost needed)
uv run ruff check .      # lint
uv run ruff format .     # format
uv run pyright           # types (strict on src)
```

Integration tests run against a local, disposable Docmost (see
[dev/docmost](dev/docmost/README.md)):

```bash
set -a; . dev/docmost/.env.test; set +a
DOCMOST_INTEGRATION=1 uv run pytest -m integration
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/).

## License

To be decided before the first public release.
