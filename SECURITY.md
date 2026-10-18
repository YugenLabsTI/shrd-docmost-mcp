# Security

## Reporting a vulnerability

Report vulnerabilities privately through
[GitHub's private vulnerability reporting](https://github.com/YugenLabsTI/shrd-docmost-mcp/security/advisories/new)
rather than in a public issue. Include the affected version, the configuration (without secrets), and steps to
reproduce.

## Threat model

The server gives an AI agent access to a wiki. The agent, and any text it reads, are
untrusted: a page can contain instructions that try to make the agent leak or change
data (prompt injection). The design limits what a misled agent can do.

| Risk | Mitigation |
|------|------------|
| Agent changes or destroys content | Read-only by default (`DOCMOST_READ_ONLY`). Write tools are not registered, and the client refuses writes independently. No delete, move, or permission tools exist. |
| Agent reaches spaces it should not | Use a dedicated least-privilege Docmost account (first barrier). `DOCMOST_ALLOWED_SPACES` is enforced inside the client on every read and write (second barrier). |
| Agent rewrites a whole page by mistake | `replace` asks the user to confirm through the MCP host (`DOCMOST_CONFIRM_REPLACE`, on by default); declined, cancelled, or impossible to ask means nothing is written. |
| A section edit discards edits someone is typing | Docmost only saves whole pages, so `edit_section` rewrites the page. It refuses pages saved in the last 60 seconds (`PAGE_BUSY`; `DOCMOST_BUSY_WINDOW_SECONDS`, never below Docmost's 45-second save delay), measured on the earlier of Docmost's clock (its `Date` header) and the local one; if the two differ by more than 5 minutes it refuses with `CLOCK_SKEW` instead of guessing, then asks the user to confirm (`DOCMOST_CONFIRM_REPLACE`), rechecks `updatedAt` when writing, and only accepts well-formed HTML so new content cannot swallow the following sections. |
| Agent posts unwanted comments | `add_comment` exists only with `DOCMOST_ALLOW_COMMENTS`, off by default and independent of `DOCMOST_READ_ONLY`; the client refuses comments on its own as well. Comments are built from plain text, so they cannot mention users. Each comment makes the account a watcher of the page and notifies its watchers. On Community Edition commenting requires the `writer` role (viewer comments are an Enterprise feature), so for a commenting agent the page-edit barrier is this server's read-only mode, not Docmost's role. |
| Agent overwrites concurrent human edits | `update_page` requires the `updated_at` the agent read and refuses stale pages. Tool descriptions steer agents to `append`/`prepend`. |
| Agent spams users through mentions | Docmost notifies only users who were not mentioned in the previously saved content. Writes may keep mentions already on the page (matched by entity type and id) and reject any other mention, including HTML-entity-encoded, nested, duplicated-attribute or otherwise unmatched mention markup; new pages cannot contain mentions. |
| Nobody can tell what the agent did | With `DOCMOST_AUDIT_LOG`, every write, comment, move and refused attempt that reaches a tool is appended to a local JSON-lines file (created with mode 0600) with ids, outcome and error code only, never content; calls rejected earlier by input-schema validation are not recorded. Writes fail closed when they cannot be recorded (`AUDIT_UNAVAILABLE`), and the server does not start with an unusable log. Operators read it with `yugen-docmost-mcp audit report`; the agent's `audit_summary` tool is off unless `DOCMOST_AUDIT_EXPOSE=1`. The file is not tamper-proof against someone with access to it; ship it to central logging if that matters. |
| Agent reorganizes a space by mistake | `move_page` exists only with `DOCMOST_READ_ONLY=0` and `DOCMOST_ALLOW_MOVE=1` (off by default), and the client refuses moves on its own too. It moves within one allowed space, requires the `updated_at` the agent read, never omits the parent (Docmost would move a nested page to the root) and changes no content. |
| Resources expose pages outside the allowed spaces | `docmost://` resources are read-only and go through the same client as the tools, so `DOCMOST_ALLOWED_SPACES` and the compatibility check apply; the space tree is capped at 200 pages and 50 requests. |
| A prompt file runs code or leaks its contents | Prompt files are operator configuration read once at startup from `DOCMOST_PROMPTS_DIR` (top-level `*.toml`, at most 100 files of 64 KiB). Templates only substitute declared `{{argument}}` placeholders in one pass and are never evaluated; argument values are inserted verbatim. Startup errors name the file, never the template. A prompt is text for the agent, so it carries no more authority than the tools and settings already allow. |
| Content silently destroyed by format quirks | Markdown that Docmost would strip as front matter is rejected; the docs and tool descriptions explain which format preserves what. |
| Credential theft from disk | Credentials come only from environment variables or `*_FILE` secrets. The JWT is kept in memory only and revoked on shutdown (logout). |
| Token leakage over the network | HTTPS is required unless explicitly overridden. Redirects are never followed and cookies are refused, so the token is only sent as a bearer header to the configured host. |
| Secrets or page text in logs | Errors name settings and status codes, never values; response validation errors never echo input; tool failures log codes only. |
| Supply-chain compromise | Only mainstream PyPI dependencies, locked with hashes. CI audits locked runtime dependencies with `pip-audit`, and GitHub Actions are pinned by commit SHA. Releases are tagged by CI from `main` only after every check passes, published with Trusted Publishing (no PyPI token in the repository), installed from TestPyPI before they reach PyPI, and published to PyPI only after a maintainer approves. |

## Recommended deployment

- Create a dedicated Docmost account for each agent. Add it only to the spaces it needs,
  with the `reader` role unless writes are required.
- Provide the password through `DOCMOST_PASSWORD_FILE` (for example a Docker or
  Kubernetes secret) instead of `DOCMOST_PASSWORD`.
- Set `DOCMOST_ALLOWED_SPACES` even when the account's membership looks narrow: Docmost
  adds every new member to the workspace's default space with the **writer** role.
  Alternatively, remove the account from the default space.
- Enable writes (`DOCMOST_READ_ONLY=0`) only for agents that need them. For an agent
  that should only propose changes, keep it read-only and set `DOCMOST_ALLOW_COMMENTS=1`.
  On Community Edition it needs the `writer` role to comment, so grant that role only in
  the spaces where it should comment and keep them in `DOCMOST_ALLOWED_SPACES`.

## Out of scope

- Docmost server vulnerabilities. Report those to the Docmost project.
- Accounts protected by MFA or SSO. They cannot log in through this client.
