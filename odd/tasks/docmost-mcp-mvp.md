# Feature: docmost-mcp MVP

Objective: unofficial MCP server + Python client for self-hosted Docmost Community Edition (v0.96.0), secure by default.
Branch: `feat/mvp` (main is unborn; remote `YugenLabsTI/shrd-docmost-mcp` empty). Packages: `docmost-client` (import `docmost_client`), `yugen-docmost-mcp` (import `yugen_docmost_mcp`; PyPI `docmost-mcp` is taken by an unrelated project). Delivery strategy: `ask-on-risk` (chain strategy pending user choice; commits are work-unit sized).
Test runner: `uv run pytest` (respx for HTTP mocks); lint `uv run ruff check`, types `uv run pyright`.

## Specs

- **S1 — Client package.** "`docmost-client`: typed httpx client (sync + async if cheap), pydantic models, session lifecycle (login, cache in memory, re-login on 401)". Decision (2026-10-16): sync API is required because the wikiops `DocumentProvider` is sync; async core + generated sync facade. "keep the client's public API stable and semver it."
- **S2 — MCP package.** "`docmost-mcp`: MCP server on the official Python MCP SDK, depends on `docmost-client`." "stdio transport first; streamable HTTP later."
- **S3 — Architecture.** "Language: Python. Package/workspace manager: `uv`". "Hexagonal: the MCP tools layer depends on client ports, not on httpx." "MUST NOT depend on wikiops or wikiops-sdk."
- **S4 — MVP tools.** "`search`, `list_spaces`, `get_page` (markdown), `list_chi (markdown, optional parent), `update_page` (markdown, append|prepend|replace, with an `updatedAt` precheck)." "NOT in the MVP: delete, permanent delete, space create/upents." "`move_page` maybe later, behind a flag." (Source text is truncated; interpreted tool set: search, list_spaces, get_page, list_children, create_page, update_page.)
- **S5 — Content formats.** "quiero que añadamos de una ves soporte para los demas modos de ingresar contenido, como html, con eso daremos un gran plus y segun el caso el agente puede decidir si inserta markdown, html u otro segun sea soportado!" Verified v0.96.0: create/update accept `format` in `json|markdown|html`; `pages/info` reads in the same three.
- **S6 — Credentials.** "Credentials only from env vars (e.g. `DOCMOST_BASE_URL`T_PASSWORD`, or a `*_FILE` variant). Never write tokens or passwords to disk; keep the JWT in memory only."
- **S7 — Transport security.** "Reject non-`https://` base URLs unless an explicit `DOC` is set (for local dev)." (Assumption: flag name `DOCMOST_ALLOW_INSECURE_HTTP`.)
- **S8 — Read-only.** "`DOCMOST_READ_ONLY=1` hides/blocks every write tool. Default to read-only; writes must be opt-in."
- **S9 — Space allowlist.** "`DOCMOST_ALLOWED_SPACES` allowlist (slugs or IDs), enfonot only in tools." (Assumption: enforced inside the client, not only in tools.)
- **S10 — Redaction.** "Never log credentials, tokens, or page bodies by default; redact them in errors."
- **S11 — Supply chain.** "No third-party binaries; minimal, mainstream deps; CI wy audit."
- **S12 — Quality.** "TDD with pytest, using respx (or equivalent) to mock HTTP. Contract tests per Docmost version, using recorded fixtures." "Tool descriptions written for agents: when to use each one, what it returns, failure modes. Structured JSON results and typed error codes."
- **S13 — Docs.** "README marked "Unofficial, not affiliated with Docmost". Include a compatibility matrix (Docmost version vs our version). License TBD before an"
- **S14 — Live instance.** "Do not run anything against our live Docmost instance (ployment) without my explicit authorization for that specific operation and credential."
- **S15 — API fidelity.** "Verify each DTO against the v0.96.0 source before impleoads." "Docmost has no ETag/If-Match. For optimistic concurrency, compare `updatedAt` before writing and document the remaining race." "This is an INTERNAL API: any Docmost upgrade may break it. Pin and test per version."
- **S16 — Commits.** "Conventional commits, no AI attribution in commits."

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T0 | S5, S15 | delegated (parallel with T1, disjoint surface `docs/docmost-api-v0.96.0.md`) | in progress | |
| T1 | S1-S3, S11, S16 | inline | done | L8; commit `chore: scaffold uv workspace` |
| T2 | S6, S7, S8, S10 | inline | pending | |
| T3 | S1, S6, S10 | inline | pending | |
| T4 | S1, S4, S5, S12, S15 | inline | pending | |
| T5 | S8, S9 | inline | pending | |
| T6 | S4, S5, S15 | inline | pending | |
| T7 | S2, S3, S4, S5, S12 | inline | pending | |
| T8 | S4, S8 | inline | pending | |
| T9 | S13, S15 | inline | pending | |

Task summaries: T0 verify v0.96.0 API from source (docs only, no live calls). T1 uv workspace scaffold + CI. T2 config (env, `*_FILE`, https guard, read-only default, redacted repr). T3 session + transport (login, in-memory JWT, 401 re-login, error mapping, redaction). T4 client reads + contract fixtures. T5 read-only guard + space allowlist in client. T6 client writes (create/update, `updatedAt` precheck, format, size cap, never forward `spaceId` on update). T7 MCP read tools (ports, adapter, structured results, agent descriptions, stdio). T8 MCP write tools gated by read-only. T9 README, SECURITY, compatibility matrix.

High-risk (independent verifier): T3, T5, T6 (security / data).
Forecast: ~3000 authored changed lines → exceeds 400; chain strategy to be confirmed with the user before opening PRs.

## Log

- **L1 (2026-10-16, user original request, verbatim):**

  > # Context: build `shrd-docmost-mcp`
  >
  > ## Goal
  > Build an unofficial MCP server + Python client for **self-hosted Docmost Community Edition**,
  > so AI agents can search/read/write our wiki with tight control and security. Private repo for now
  > (YugenLabsTI/shrd-docmost-mcp); may be published later, so build it product-grade.
  >
  > ## Why we build our own (decided)
  > - Docmost's native MCP and its public API/API keys require a Business/Enterprise license
  >   (docmost.com/docs/user-guide/mcp, /docs/user-guide/api). We run Community `docmost/docmost:0.96.0`.
  > - We audited the community alternative `wisflux/docmost-local-mcp` and rejected it:
  >   - its npm postinstall downloads the Rust binary with no checksum or signature, from a mutable release;
  >   - it claims keychain storage but compiles `keyring` without a backend, so the JWT lands in
  >     plaintext `~/.docmost-local-mcp/session.json`;
  >   - it accepts `http://` base URLs;
  >   - it has no read-only mode and exposes write tools (update/move pages, update spaces).
  >   Our version must fix all of these.
  >
  > ## Verified Docmost v0.96.0 facts (source: docmost/docmost tag v0.96.0)
  > - Community uses the internal JSON POST API the web frontend uses. Auth: `POST /api/auth/login`
  >   (email/password) returns a JWT (cookie `authToken`; Bearer also works). Our instance sets
  >   `JWT_TOKEN_EXPIRES_IN=30d`.
  > - `POST /api/pages/update` (`apps/server/src/core/page/dto/update-page.dto.ts`): `pageId`, optional
  >   `content` (string|object), `operation` in `append|prepend|replace`, `format` in `json|markdown|html`.
  > - `POST /api/pages/info` (`apps/server/src/core/page/dto/page.dto.ts`): `pageId`, `includeSpace`,
  >   `format` in `json|markdown|html`, so content can be READ as markdown.
  > - Other endpoints seen in use: `/api/version`, `/api/users/me`, `/api/spaces`, `/api/spaces/info`,
  >   `/api/search`, `/api/pages/recent`, `/api/pages/sidebar-pages`, `/api/pages/create`,
  >   `/api/pages/move`, `/api/comments`, `/api/comments/create`.
  >   Verify each DTO against the v0.96.0 source before impleoads.
  > - Docmost has no ETag/If-Match. For optimistic concurrency, compare `updatedAt` before writing and
  >   document the remaining race.
  > - This is an INTERNAL API: any Docmost upgrade may break it. Pin and test per version.
  >
  > ## Architecture (decided)
  > - Language: Python. Package/workspace manager: `uv` worksckages:
  >   - `docmost-client`: typed httpx client (sync + async if cheap), pydantic models, session
  >     lifecycle (login, cache in memory, re-login on 401), here.
  >   - `docmost-mcp`: MCP server on the official Python MCP SDK, depends on `docmost-client`.
  >     stdio transport first; streamable HTTP later. Distrib
  > - Hexagonal: the MCP tools layer depends on client ports, not on httpx.
  > - MUST NOT depend on wikiops or wikiops-sdk. A separate wiops, Python,
  >   `DocumentProvider` protocol from `wikiops-sdk`, entry-point group `wikiops.providers`) will later
  >   consume `docmost-client` from PyPI. Dependency directioent only.
  >   So keep the client's public API stable and semver it.
  >
  > ## MVP tools
  > `search`, `list_spaces`, `get_page` (markdown), `list_chi (markdown, optional
  > parent), `update_page` (markdown, append|prepend|replace, with an `updatedAt` precheck).
  > NOT in the MVP: delete, permanent delete, space create/upents.
  > `move_page` maybe later, behind a flag.
  >
  > ## Security requirements (non-negotiable)
  > - Credentials only from env vars (e.g. `DOCMOST_BASE_URL`T_PASSWORD`, or a
  >   `*_FILE` variant). Never write tokens or passwords to disk; keep the JWT in memory only.
  > - Reject non-`https://` base URLs unless an explicit `DOC` is set (for local dev).
  > - `DOCMOST_READ_ONLY=1` hides/blocks every write tool. Default to read-only; writes must be opt-in.
  > - `DOCMOST_ALLOWED_SPACES` allowlist (slugs or IDs), enfonot only in tools.
  > - Never log credentials, tokens, or page bodies by default; redact them in errors.
  > - Intended use: a dedicated least-privilege Docmost servins are the second
  >   barrier.
  > - No third-party binaries; minimal, mainstream deps; CI wy audit.
  >
  > ## Quality
  > - TDD with pytest, using respx (or equivalent) to mock HTTP. Contract tests per Docmost version,
  >   using recorded fixtures.
  > - Tool descriptions written for agents: when to use each one, what it returns, failure modes.
  >   Structured JSON results and typed error codes.
  > - README marked "Unofficial, not affiliated with Docmost". Include a compatibility matrix
  >   (Docmost version vs our version). License TBD before an
  > - Conventional commits, no AI attribution in commits.
  >
  > ## Constraints
  > - Do not run anything against our live Docmost instance (ployment) without
  >   my explicit authorization for that specific operation and credential.
  > - Start by proposing the repo layout and the MVP task breore writing code.
  >
  > --- Pese a que el prompt esta en ingles, sigamos desde aquí en español

- **L2 (2026-10-16, user, verbatim):** "Puedes decirlo tu mismo revisando el repo: github.com/sgg10/wikiops, pero el foco esta en el producto individual por ahora. Me gusta tu plan pero tambien quiero que añadamos de una ves soporte para los demas modos de ingresar contenido, como html, con eso daremos un gran plus y segun el caso el agente puede decidir si inserta markdown, html u otro segun sea soportado!"
- **L3 (2026-10-16, evidence):** wikiops `DocumentProvider` is sync (`src/wikiops/providers/local_files/provider.py`: plain `def get_document`, `def apply_changes`). Docmost v0.96.0 `create-page.dto.ts` and `update-page.dto.ts` accept `format` `json|markdown|html` (default `json`); `UpdatePageDto extends PartialType(CreatePageDto)` so update also accepts `spaceId`/`parentPageId` → client must never forward `spaceId` on update; DTO has no content size limit → client-side cap.
- **L4 (2026-10-16, user, verbatim):** "dale, arrancá con T0 y T1. De hecho ve en auto-mode en lo que consideres y solo para cuando en verdad me necesites!"
- **L5 (2026-10-16, evidence):** PyPI `docmost-mcp` exists (unrelated project, Dev789/docmost-mcp-server); `docmost-client` and `yugen-docmost-mcp` are free.
- **L6 (2026-10-16, user, verbatim):** "No, usa yugen-docmost-mcp"
- **L7 (2026-10-16, user, verbatim):** "El nombre del repo debe ser shrd-docmost-mcp, pero el paquete en pypi puede ser ese, yugen-docmost-mcp"
- **L8 (2026-10-16, T1 evidence):** RED: `uv run pytest -q` → 2 failed (AttributeError `__version__`). GREEN: 2 passed (py3.12 and py3.11). `ruff check`, `ruff format --check`, `pyright` strict: clean. `pip-audit --strict --require-hashes` on locked runtime deps: no known vulnerabilities. `uv build --all-packages`: 2 sdists + 2 wheels. Sync API decision: sans-IO request/response helpers shared by thin `httpx.Client` and `httpx.AsyncClient` wrappers (no codegen dependency); decided in T3.
