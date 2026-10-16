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
| T0 | S5, S15 | delegated (parallel with T1, disjoint surface `docs/docmost-api-v0.96.0.md`) | done | L11; commit `docs: add Docmost v0.96.0 API reference` |
| T1 | S1-S3, S11, S16 | inline | done | L8; commit `chore: scaffold uv workspace` |
| T2 | S6, S7, S8, S10 | inline | done | L9; commit `feat(client): load secure settings from environment` |
| T3 | S1, S6, S10 | inline | done | L12; commit `feat(client): add authenticated sync and async sessions` |
| T4 | S1, S4, S5, S12, S15 | inline | done | L14; commit `feat(client): add typed read operations` |
| T5 | S8, S9 | inline | done (verified; read-only guard landed in T6) | L15; commit `feat(client): enforce the space allowlist` |
| T6 | S4, S5, S15 | inline | done (verified; 3 blockers fixed) | L16; commit `feat(client): add guarded page writes` |
| T7 | S2, S3, S4, S5, S12 | inline | done | L18; commit `feat(mcp): serve Docmost tools over stdio` |
| T8 | S4, S8 | inline | done (same commit as T7) | L18 |
| T9 | S13, S15 | inline | done | L19; commit `docs: add README, security model, and changelog` |

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
- **L9 (2026-10-16, T2 evidence):** RED: collection ImportError (`DocmostSettings` missing). GREEN: `uv run pytest -q` → 40 passed; ruff, ruff format, pyright strict clean. Decisions (assumptions, documented in `from_env` docstring): `DOCMOST_ALLOW_INSECURE_HTTP` is the http opt-in flag; `*_FILE` supported for EMAIL and PASSWORD (both set → error); unset `DOCMOST_ALLOWED_SPACES` = all spaces the account can access, set-but-empty fails closed; `DOCMOST_TIMEOUT_SECONDS` default 30; `DOCMOST_MAX_CONTENT_BYTES` default 1,000,000; URL with userinfo/query/fragment rejected. T1 native review: `lens_context_budget_exceeded` (uv.lock size), so an independent general-purpose verifier was used instead.
- **L10 (2026-10-16, T1 verifier):** independent verifier on d959d34: S1, S2, S3, S11, S16 pass, 0 blockers (action SHAs match tags; setup-uv `python-version` sets `UV_PYTHON` so the matrix is real; hashed runtime audit clean). Advisories applied in a follow-up `ci:` commit: `!.env.example`, `*.pem`, `*.key`; job `timeout-minutes: 15`; cancel-in-progress only on PRs; dependabot 7-day cooldown. Accepted advisories: build backend unhashed at build time; pyright needs Node (dev-only).
- **L11 (2026-10-16, T0 evidence + design decisions):** `docs/docmost-api-v0.96.0.md` written from source (tag v0.96.0, commit 9b3e5dd), every claim cited. Parent spot check confirmed login (`auth.controller.ts#L55-L105`: JWT only via `Set-Cookie: authToken`; MFA path returns 200 without cookie) and `/api/version` (`version.service.ts`: returns `undefined` when the GitHub fetch fails, losing `currentVersion`). Design decisions derived (assumptions, no user decision needed):
  - T3: take JWT from `Set-Cookie`, disable cookie jar, send `Authorization: Bearer` only; login rate limit is 10/min/IP and each login creates a server session (max 25) → single-flight login, re-login at most once per 401, `close()` calls `/api/auth/logout`; 200 without cookie → `AUTH_FAILED` (MFA/SSO hint); 429 → `RATE_LIMITED`. Unwrap `{data, success, status}`; NestJS errors `{message, error, statusCode}`; non-member space → 404.
  - T4: cursor pagination `{items, meta{...nextCursor}}` (limit 1-100); search uses `limit`/`offset` and returns `{items}`; search hits use `space.id`; sidebar/recent need UUIDs (resolve slugs first). Version gate: known unsupported version → refuse unless `DOCMOST_ALLOW_UNTESTED_VERSION=1`; unknown version (GitHub fetch failed) → proceed with warning; call `/api/version` at most once per process.
  - T5/T6: treat `deletedAt != null` as `NOT_FOUND`; refuse writes on `isLocked` pages; always send `format`; never send `spaceId`/`parentPageId` on update; reject markdown content starting with `---` (front-matter regex deletes content) with a hint to use html; reject agent content containing mention nodes (fake notifications) — assumption, fail closed; `max_content_bytes` default 1,000,000 stays under Fastify 1 MiB.
  - T7 tool guidance: read markdown for comprehension; `replace` on rich pages via html round-trip (lossless enough); markdown append/prepend fine; json for exact structure.
  - Open questions needing a disposable local Docmost 0.96.0 (never the live instance): error bodies 413/429/400, content without format, Set-Cookie behind proxy, markdown fidelity of tables/details/embeds, replace during live typing, json validation strictness, `/api/version` offline.
- **L12 (2026-10-16, T3 evidence):** RED: collection ImportError. First GREEN attempt failed `test_logs_in_once_and_sends_bearer_token_only` — the cookie jar still stored `authToken` because httpx copies an `httpx.Cookies` into a default jar (dropping the policy); fixed by passing a `CookieJar` with a reject-all policy directly. GREEN: 88 passed (sync and async parametrized); ruff, pyright strict on src (tests on standard because respx is partially typed) clean. Sync/async share `_protocol.py` (I/O-free); `anyio` added as an explicit dep (already transitive via httpx) for the async login lock.
- **L13 (2026-10-16, native review):** user granted review of slice d959d34..36af8b3 (T2, CI hardening, T0 doc, T3); lenses risk + reliability; outcome **approved**, acknowledged (`gentle-ai.review-acknowledged/v1`, lineage review-e9714025609dd1b5). Reviewed boundary → 36af8b3. Non-blocking advisories (fixed in a follow-up `fix(client)` commit): session use after close re-logs in on a closed client; empty `DOCMOST_PASSWORD=""` plus `_FILE` wrongly rejected as ambiguous; no thread single-flight test; untested settings branches (oversized/invalid-UTF-8 secret file, nan/inf timeout, IPv6 host).
- **L14 (2026-10-16, T4 evidence):** RED: collection ImportError. GREEN: 120 passed (py3.12 and py3.11); ruff, pyright strict clean. Operations are I/O-free generators in `_ops.py` driven by `drive`/`drive_async` (sync/async parity without codegen). Fixtures in `tests/fixtures/v0_96_0` are synthesized from source types (README says so); recorded fixtures from a disposable local Docmost 0.96.0 remain a follow-up. Response validation errors map to `UPSTREAM_ERROR` without echoing input (page bodies). Version gate per L11 (`DOCMOST_ALLOW_UNTESTED_VERSION`).
- **L15 (2026-10-16, T5 evidence):** RED: collection ImportError (`SpaceNotAllowedError`). GREEN: 145 passed (py3.12, py3.11); ruff, pyright strict clean. Allowlist enforced inside the client on every read path: list_spaces filters, get_space/get_page refuse (page content never returned), list_children refuses before listing a disallowed space and after listing a disallowed parent's children, search refuses a disallowed `space` before searching and drops hits from disallowed spaces. Slug entries resolve to ids lazily, once per client; unresolvable entries grant nothing; matching is case-insensitive. Error code `SPACE_NOT_ALLOWED` (assumption: reveals that the space exists, accepted for operator clarity). Advisory fixes from L13 committed as 99238a6.
- **L16 (2026-10-16, T6 evidence):** RED: collection ImportError. GREEN: 174 passed (py3.12, py3.11); ruff, pyright strict clean. `create_page`/`update_page` in both clients. Order: read-only check (`READ_ONLY`, no request) → local validation (operation required with content, format/type match, non-empty, `DOCMOST_MAX_CONTENT_BYTES`, Docmost front-matter regex, mention nodes in html/markdown/json) → precheck `pages/info` (allowlist, trash, `isLocked`, `canEdit`, optional `expected_updated_at` → `STALE_PAGE`) → update with `pageId` UUID, never `spaceId`/`parentPageId`, always `format` → silent no-op detection (content unchanged after a non-identical write → `UPSTREAM_ERROR` naming `COLLAB_DISABLE_REDIS`). Create resolves the space through the allowlist and returns the page without content (Docmost does not echo it). Assumption: mention rejection is fail-closed and not configurable in the MVP.
- **L17 (2026-10-16, T5+T6 independent verifier):** S8, S9, S10 pass; S5, S15 failed with 3 blockers, fixed in one correction batch (`fix(client): close content guard gaps...`), each with a RED regression test: B1 no-op detector false-positived on a `replace` Docmost normalizes → now only append/prepend are checked; B2 mention guard bypassed with HTML entities (`&#109;ention`) → match after `html.unescape`; B3 leading U+FEFF bypassed the front-matter guard (JS `\s` includes it) → `[\s\ufeff]*`. Advisories also fixed: size cap now counts the JSON-encoded bytes actually sent; naive `expected_updated_at` → `INVALID_INPUT`; non-serializable json → `INVALID_INPUT`; `create_page` prechecks the parent (allowlist + same space). Accepted advisories: empty `list_children` of a disallowed UUID parent returns an empty list (no leak); allowlist resolution cached per client; Docmost error messages echoed (baseline). GREEN: 211 passed (py3.12, py3.11).
- **L18 (2026-10-16, T7+T8 evidence):** MCP SDK is `mcp` 2.3.0 (`FastMCP` renamed `MCPServer`). RED: collection ImportError. One GREEN failure surfaced an SDK behavior: `pre_parse_json` JSON-decodes string arguments unless the annotation is exactly `str`, so free-text params (`content`, `title`, `query`) are typed `str` with `""` meaning unset (regression test with "[1, 2]", "null", "true", '{"a": 1}'). GREEN: 211 passed (py3.12, py3.11); ruff, pyright strict clean. Ports `WikiReader`/`WikiWriter` (Protocols) are satisfied structurally by `AsyncDocmostClient`; tools never import httpx. Structured outputs (pydantic) + typed error results `{"error": {"code", "message", "retryable"[, "current_updated_at"]}}` with `is_error=true`. Compatibility checked once before the first tool (unsupported → `UNSUPPORTED_VERSION` on every tool; unknown → stderr warning). `update_page` requires an aware `expected_updated_at`. Write tools registered only when `DOCMOST_READ_ONLY` is false (T8). Runtime harness: real stdio subprocess via `mcp.Client(StdioServerParameters)` → READ_ONLY=1 lists 4 read tools, READ_ONLY=0 lists 6; `yugen-docmost-mcp --version` prints `yugen-docmost-mcp 0.1.0`.
- **L19 (2026-10-16, T9 evidence):** README (unofficial disclaimer, quick path, env table, tool table, error codes, format guide, security model, compatibility matrix Docmost 0.96.0 ↔ 0.1.x, known limitations incl. the residual updatedAt race), SECURITY.md (threat model + deployment), CHANGELOG.md, package READMEs for PyPI. Added a test proving shutdown logs out (SECURITY.md claim). 212 passed; `uv build --all-packages` builds 2 wheels + 2 sdists. License remains TBD (S13).
- **L20 (2026-10-16, native review of e07947d..76d5224):** user granted; lenses risk, readability, reliability; outcome **approved**, acknowledged (lineage review-2c1f9e27a04dec95); reviewed boundary → 76d5224. The 36af8b3..e07947d client slice was covered by the independent verifier (L17) instead, because native review only reviews base..HEAD without changing checkout. Non-blocking advisories fixed in a follow-up `fix:` commit, each with a RED test: search `next_offset` was computed after allowlist filtering (agents stopped paging early) → client `search` now returns `SearchResults(hits, next_offset)` computed from Docmost's raw page (API change, unreleased 0.1.0); id/cursor/space params typed `str | None` were JSON-decoded by the SDK ("null" silently dropped the space filter) → all optional string params are plain `str` with "" = unset; README and tool descriptions claimed every failure has a code → now state that schema-validation failures come from the SDK untyped; compatibility gate uses `isinstance(UnsupportedVersionError)` and retries transient failures. 218 passed (py3.12, py3.11); ruff, pyright clean.
