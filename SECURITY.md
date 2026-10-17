# Security

## Reporting a vulnerability

Report vulnerabilities privately to the maintainers (Yugen Labs) rather than in a public
issue. Include the affected version, the configuration (without secrets), and steps to
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
| A section edit discards edits someone is typing | Docmost only saves whole pages, so `edit_section` rewrites the page. It refuses pages saved in the last 60 seconds (`PAGE_BUSY`), then asks the user to confirm (`DOCMOST_CONFIRM_REPLACE`), rechecks `updatedAt` when writing, and only accepts well-formed HTML so new content cannot swallow the following sections. |
| Agent posts unwanted comments | `add_comment` exists only with `DOCMOST_ALLOW_COMMENTS`, off by default and independent of `DOCMOST_READ_ONLY`; the client refuses comments on its own as well. Comments are built from plain text, so they cannot mention users. Each comment makes the account a watcher of the page and notifies its watchers. On Community Edition commenting requires the `writer` role (viewer comments are an Enterprise feature), so for a commenting agent the page-edit barrier is this server's read-only mode, not Docmost's role. |
| Agent overwrites concurrent human edits | `update_page` requires the `updated_at` the agent read and refuses stale pages. Tool descriptions steer agents to `append`/`prepend`. |
| Agent spams users through mentions | Content containing mention nodes is rejected, including HTML-entity-encoded forms. |
| Content silently destroyed by format quirks | Markdown that Docmost would strip as front matter is rejected; the docs and tool descriptions explain which format preserves what. |
| Credential theft from disk | Credentials come only from environment variables or `*_FILE` secrets. The JWT is kept in memory only and revoked on shutdown (logout). |
| Token leakage over the network | HTTPS is required unless explicitly overridden. Redirects are never followed and cookies are refused, so the token is only sent as a bearer header to the configured host. |
| Secrets or page text in logs | Errors name settings and status codes, never values; response validation errors never echo input; tool failures log codes only. |
| Supply-chain compromise | Only mainstream PyPI dependencies, locked with hashes. CI audits locked runtime dependencies with `pip-audit`, and GitHub Actions are pinned by commit SHA. |

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
