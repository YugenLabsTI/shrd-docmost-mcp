# shrd-docmost-mcp

> **Unofficial, not affiliated with Docmost.** Docmost is a trademark of its owners.

A security-first MCP server and Python client that let AI agents search, read, and
(optionally) write a **self-hosted Docmost Community Edition** wiki. Docmost's own MCP
server and public API require a Business/Enterprise license; this project talks to the
internal API the Docmost web app uses, with read-only access by default.

| Package | Distribution name | What it is |
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
         "args": [
           "--from",
           "git+ssh://git@github.com/YugenLabsTI/shrd-docmost-mcp@yugen-docmost-mcp-v0.1.0#subdirectory=packages/yugen-docmost-mcp",
           "yugen-docmost-mcp"
         ],
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

   The packages are not on PyPI yet: `uvx` installs the server from a release tag of this
   repository (see [Releases and versioning](#releases-and-versioning)), and builds
   `docmost-client` from the same commit. It needs read access to the repository over SSH
   (or HTTPS after `gh auth setup-git`). To run your own checkout instead:
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
| `DOCMOST_ALLOW_MOVE` | `0` | Set to `1` to enable `move_page`; it also needs `DOCMOST_READ_ONLY=0`. |
| `DOCMOST_CONFIRM_REPLACE` | `1` | Ask the user to confirm every `replace` (see below). `0` skips the question. |
| `DOCMOST_ALLOWED_SPACES` | all the account's spaces | Comma-separated space slugs or IDs. Set but empty is an error. |
| `DOCMOST_ALLOW_INSECURE_HTTP` | `0` | Allow `http://` base URLs (local development only). |
| `DOCMOST_ALLOW_UNTESTED_VERSION` | `0` | Connect to a Docmost version not in the compatibility matrix. |
| `DOCMOST_TIMEOUT_SECONDS` | `30` | Per-request timeout. |
| `DOCMOST_MAX_CONTENT_BYTES` | `1000000` | Largest content a write may send (encoded size). |
| `DOCMOST_AUDIT_LOG` | unset | File where every write, comment, move and refused attempt is recorded (see [Audit log](#audit-log)). Unset: no audit file. |
| `DOCMOST_AUDIT_READS` | `0` | Also record read tools. Needs `DOCMOST_AUDIT_LOG`. |
| `DOCMOST_AUDIT_EXPOSE` | `0` | Offer the read-only `audit_summary` tool to the agent. Needs `DOCMOST_AUDIT_LOG`. |
| `DOCMOST_BUILTIN_PROMPTS` | `1` | Offer the generic `summarize_page` and `answer_from_wiki` prompts. `0` hides them. |
| `DOCMOST_PROMPTS_DIR` | unset | Directory of team prompt files (`*.toml`, see [MCP prompts](#mcp-prompts)). |
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

Moving pages is a third switch on top of writes: `move_page` exists only with
`DOCMOST_READ_ONLY=0` and `DOCMOST_ALLOW_MOVE=1`, because reorganizing a space affects
everyone who navigates it.

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
   side cannot shorten it. Time zones do not matter (both are absolute instants); when
   the two clocks differ by more than 5 minutes one of them is wrong, and section edits
   fail with `CLOCK_SKEW` until an operator fixes the time synchronization;
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
| `move_page` | move | Move a page under another parent (or to the space root) and place it after a sibling, first or last. |

Failures return `is_error: true` with
`{"error": {"code": "...", "message": "...", "retryable": false}}`. Arguments that do not
match a tool's input schema (missing, wrong type, out of range) are rejected by the MCP
SDK before the tool runs, with an untyped error message. Codes:
`READ_ONLY`, `COMMENTS_DISABLED`, `MOVE_DISABLED`, `AUDIT_UNAVAILABLE`, `CONFIRMATION_DECLINED`, `CONFIRMATION_UNAVAILABLE`,
`PAGE_BUSY`, `CLOCK_SKEW`,
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

### Moving a page

`move_page` keeps the page's content and only changes where it sits. Pass the new parent
(an empty `parent_page_id` means the space root), optionally `after_page_id` (a page
already under that parent) or `placement` (`start` or `end`, the default), and the
`updated_at` you read. Docmost orders siblings by a position key the client computes
between the two neighbours; when two neighbours leave no room for one (after many moves
into the same gap), the call fails with `INVALID_INPUT` and the page stays where it was.
Pages only move within their space, never under one of their own descendants.

## MCP resources

Hosts can attach these as context without a tool call. They are read-only, exist in
read-only mode too, and respect `DOCMOST_ALLOWED_SPACES`.

| URI | Content |
|-----|---------|
| `docmost://page/{page_id}` | The page as markdown, after its title, ids and last update. `page_id` is the UUID or slug id. |
| `docmost://space/{space}/tree` | The space's page hierarchy (slug or id) as a nested list of titles and slug ids; at most 200 pages, marked when truncated. |
| `docmost://recent` | The 50 most recently updated pages in the allowed spaces. |

A failed read returns the same error codes as the tools (for example `SPACE_NOT_ALLOWED`).

## MCP prompts

Prompts are reusable instructions a user picks in the MCP host. The server ships two
generic ones, `summarize_page(page_id)` and `answer_from_wiki(question, space?)` (search,
read and answer citing pages), which `DOCMOST_BUILTIN_PROMPTS=0` hides.

Team workflows belong in configuration, not in this server: point `DOCMOST_PROMPTS_DIR`
at a directory with one `.toml` file per prompt.

```toml
name = "weekly_report"                       # lowercase letters, digits, "_" or "-"
title = "Draft the weekly report"            # optional
description = "Draft the weekly report page" # optional
template = """
Read the recent pages in {{space}} and draft ...
"""

[[arguments]]
name = "space"
description = "Space slug or id."  # optional
required = true                    # default false

[[arguments]]
name = "tone"
default = "neutral"                # optional arguments only
```

- `{{argument}}` is replaced by the argument's value (or its `default`, or nothing). Only
  declared arguments can appear, values are inserted verbatim in one pass, and nothing
  in the template is evaluated.
- Only `*.toml` files directly inside the directory are read, at most 100 of 64 KiB
  each. Any invalid file, duplicate name or a name that clashes with a built-in prompt
  stops the server at startup with an error naming the file (never its template).
- [`examples/prompts/`](examples/prompts) has a complete example.

## Audit log

With `DOCMOST_AUDIT_LOG=/var/log/docmost-mcp/audit.jsonl` the server appends one JSON line
per event to that file (created with mode `0600`): every write, comment and move, and
every refused attempt (a declined confirmation, `PAGE_BUSY`, `FORBIDDEN`, ...). Reads are
added with `DOCMOST_AUDIT_READS=1`. Calls the MCP layer rejects before they reach a tool
(arguments that break the tool's input schema, unknown tool names) are not recorded.

```json
{"ts":"2026-10-17T10:05:00+00:00","session":"3f2a9c1b7d4e","call":"9b1c...","phase":"finished",
 "tool":"update_page","kind":"write","args":{"page_id":"...","operation":"replace","format":"html"},
 "outcome":"error","code":"CONFIRMATION_DECLINED","duration_ms":2100}
```

- Only ids and enum-like arguments are kept (`page_id`, `space`, `parent_page_id`,
  `operation`, `format`, `heading_id`, `after_page_id`, `placement`, `parent_comment_id`).
  Page content, titles, comment text, search queries and icons are never written. Values
  are cut to 128 characters, and control, formatting and line-separator characters are
  replaced by spaces so they cannot disguise the report.
- A write records a `started` line first; if that cannot be written, the write is refused
  with `AUDIT_UNAVAILABLE` and nothing changes in Docmost. A `started` line without its
  `finished` line marks a call that was interrupted.
- The server does not start when the file cannot be created or appended to. A file that
  already exists keeps its permissions. It never
  rotates the file: use logrotate with `copytruncate`, or similar.

Operators read it with the report command, independently of the agent:

```bash
yugen-docmost-mcp audit report --since 7d          # uses DOCMOST_AUDIT_LOG
yugen-docmost-mcp audit report --file audit.jsonl --json
```

With `DOCMOST_AUDIT_EXPOSE=1` the agent also gets `audit_summary(since_hours)`, a read-only
tool with the same counts, so it can answer "what did you change this week?" from data.
The report is the trusted view: the agent can summarize, but it does not replace reading
the log.

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

Commits follow [Conventional Commits](https://www.conventionalcommits.org/); they decide
the next versions (see below).

## Releases and versioning

Both packages are versioned and released independently, from CI, with
[release-please](https://github.com/googleapis/release-please):

1. Every push to `main` whose checks all pass updates one release pull request. It bumps
   the version of each package that changed (in its `pyproject.toml` and in `uv.lock`)
   and adds the commits to that package's `CHANGELOG.md`.
2. Merging the release pull request tags each bumped package, as
   `docmost-client-vX.Y.Z` or `yugen-docmost-mcp-vX.Y.Z`, and publishes a GitHub release
   with its notes.
3. To upgrade, change the tag in the MCP host configuration (see the Quick path).

A failing check in either package stops the release of both: the release job runs only
after lint, the tests, the dependency audit and the wheel check pass on that commit. A
test also fails when `yugen-docmost-mcp`'s `docmost-client` range no longer includes the
client's version, because uv does not check ranges between workspace members.

| Commit | Before 1.0 | From 1.0 |
|--------|------------|----------|
| `fix:` | patch | patch |
| `feat:` | patch | minor |
| `feat!:` or a `BREAKING CHANGE:` footer | minor | major |

A commit counts for a package only when it changes files in that package's directory.
`perf:`, `revert:` and `docs:` count as patches; `chore:`, `ci:`, `test:`, `refactor:`,
`build:` and `style:` never start a release.

**Why 0.x.** Under [Semantic Versioning](https://semver.org/), 0.x is initial
development and the public API may still change. Both packages depend on Docmost's
internal API, so 1.0 waits until:

- the public API is reviewed and frozen: `docmost_client.__all__`, the MCP tools and
  their arguments, the error codes and the `DOCMOST_*` settings;
- the packages have been used in production for a few releases without a breaking
  change;
- at least two Docmost versions are in the [compatibility](#compatibility) matrix;
- the integration tests run in CI, and a deprecation policy is written down.

A commit with a `Release-As: 1.0.0` footer starts 1.0; the MCP's `docmost-client` range
then becomes `>=1.0,<2`.

**Maintainers.** The release job uses the workflow's `GITHUB_TOKEN`, so the repository
must allow GitHub Actions to create pull requests (Settings → Actions → General →
Workflow permissions). Pull requests opened with that token do not trigger workflows, so
the job starts CI on the release pull request's branch itself; wait for it to pass
before merging.
Publishing to PyPI is planned for when the repository is public.

## License

[Apache License 2.0](LICENSE) for both packages. Copyright Yugen Labs.

This project is not affiliated with or endorsed by Docmost. It talks to Docmost only
through its HTTP API and does not include Docmost code.
