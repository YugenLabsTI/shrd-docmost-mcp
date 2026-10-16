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

Docmost applies its own permissions on top: the account comments when it can edit the
page, or when the space allows viewer comments (space settings in Docmost). For a
reader that comments, give the account the `reader` role and turn that space setting on.

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

## MCP tools

| Tool | Mode | Use it to |
|------|------|-----------|
| `search` | read | Find pages by full text; returns snippets and page ids. |
| `list_spaces` | read | Discover the spaces the server can access. |
| `list_children` | read | Browse a space's page tree. |
| `get_page` | read | Read a page as `markdown` (default), `html`, or `json`. |
| `list_recent_pages` | read | See what changed lately, across spaces or in one space. |
| `list_comments` | read | Read a page's comments (plain text, with resolved state and replies). |
| `add_comment` | comment | Add a page comment or a reply, in plain text. |
| `create_page` | write | Create a page, optionally under a parent, with initial content. |
| `update_page` | write | `append`, `prepend`, or `replace` content and/or rename a page. |

Failures return `is_error: true` with
`{"error": {"code": "...", "message": "...", "retryable": false}}`. Arguments that do not
match a tool's input schema (missing, wrong type, out of range) are rejected by the MCP
SDK before the tool runs, with an untyped error message. Codes:
`READ_ONLY`, `COMMENTS_DISABLED`, `CONFIRMATION_DECLINED`, `CONFIRMATION_UNAVAILABLE`,
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
- **Mentions are not written.** Content containing mention nodes is rejected, because
  mentions notify users.
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
