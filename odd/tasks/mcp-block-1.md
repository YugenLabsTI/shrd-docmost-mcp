# Feature: MCP block 1 — comments, recent pages, confirmation on replace

Objective: make the MCP more useful and safer: read/add page comments (comment-only role via `DOCMOST_ALLOW_COMMENTS`), list recent pages, and require human confirmation before `replace`.
Branch: `feat/block-1` (from `main`). Delivery: chained PRs, feature branch chain (strategy cached from the MVP). Test runner: `uv run pytest` (+ opt-in `-m integration` against `dev/docmost`).

## Specs

- **S1 — Comments flag.** "dale, vamos con DOCMOST_ALLOW_COMMENTS así!" — as proposed (L2): `DOCMOST_ALLOW_COMMENTS` is independent of `DOCMOST_READ_ONLY` and off by default in both modes; reading comments is always allowed; the space allowlist applies to comments like pages. User's framing: "finalmente es un rol de lectura que solo puede comentar".
- **S2 — Permission matrix in docs.** "Y me gusta como se va explicando la combinación de permisos, seria bueno tenerlo en la documentación!" — the READ_ONLY × ALLOW_COMMENTS table goes into the README.
- **S3 — Block 1 scope.** "Vamos con el primer bloque, si!" — comments (read + create), recent pages (`/api/pages/recent`), human confirmation before `replace` via MCP elicitation.
- **S4 — Roadmap kept.** "deja en engram la propuesta del segundo bloque para que no la perdamos" and move_page + audit log "que se vaya a engram tambien y abordamos en orden!" — done before implementation (Engram topic `roadmap/docmost-mcp-next-blocks`).
- **S5 — Inherited constraints.** MVP specs S6-S16 (`odd/tasks/docmost-mcp-mvp.md`) still apply: secure defaults, allowlist inside the client, no credentials/bodies in logs, TDD, typed errors, never the live instance without authorization, no AI attribution, no instance data in the repo.

Assumptions (agent decisions, documented): comments are created as page-level (`type: page`) only — inline comments need a Yjs editor selection; comment content is accepted as plain text and built into a ProseMirror document by the client (so mention nodes cannot be forged); reading returns plain text. `DOCMOST_CONFIRM_REPLACE` (default on): `replace` requires an accepted confirmation; a host without elicitation support gets `CONFIRMATION_UNAVAILABLE` (opt-out `DOCMOST_CONFIRM_REPLACE=0`); a declined/cancelled confirmation gets `CONFIRMATION_DECLINED`.

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S1, S3, S5 | inline | done | L5; commit `feat: add comment and replace-confirmation settings` |
| T2 | S3, S5 | inline | done | L6; commit `feat(client): list recent pages` |
| T3 | S1, S3, S5 | inline | done (verifier pending, with T4) | L7; commit `feat(client): read and add page comments` |
| T4 | S1, S3, S5 | inline | pending | |
| T5 | S1, S2 | inline | pending | |
| T6 | S1, S3, S5 | inline | pending | |

T1 settings `DOCMOST_ALLOW_COMMENTS`, `DOCMOST_CONFIRM_REPLACE` + errors. T2 client `list_recent_pages` with allowlist. T3 client `list_comments` / `create_comment` (flag, allowlist, trash, plain-text→ProseMirror, deleted filtered). T4 MCP tools `list_recent_pages`, `list_comments`, `add_comment` (registered only with the flag) and replace confirmation via `Resolve`/`Elicit`. T5 README permission matrix, env vars, tools, SECURITY (comment side effects), CHANGELOG. T6 local Docmost: enable viewer comments in bootstrap, integration tests (reader comments, recent pages), smoke script update.

High-risk: T3 (writes, permissions), T4 (permission gating, confirmation). Forecast ~900 authored lines → chained PRs.

## Log

- **L1 (2026-10-16, user, verbatim):** "Vamos con el primer bloque, si! Pero ajustaria el alcance de modo "solo comentarios" finalmente es un rol de lectura que solo puede comentar ¿No? Creo que podemos aterrizar a una variable de entorno algo así como ALLOW_COMMENTS_IN_READ_MODE o algo por el estilo ¿Que opinas?. En general estoy de acuerdo como pintas las otras dos ideas. El otro bloque de alto valor tambien lo quiero! Pero vamos primero con el primer bloque (deja en engram la propuesta del segundo bloque para que no la perdamos). Y de las ideas de "mas adelante" veo muy interesante el move_page y log de auditoria, que se vaya a engram tambien y abordamos en orden!"
- **L2 (2026-10-16, user, verbatim):** "dale, vamos con DOCMOST_ALLOW_COMMENTS así! Y me gusta como se va explicando la combinación de permisos, seria bueno tenerlo en la documentación!"
- **L3 (2026-10-16, evidence):** Docmost v0.96.0 `validateCanComment` (page-access.service.ts): edit permission, or view permission when the space setting `comments.allowViewerComments` is on → a reader account can comment without being able to edit. `CreateCommentDto`: `pageId`, `content` (JSON string), `selection?`, `type?` inline|page (default page), `parentCommentId?` (one reply level), `yjsSelection?`. Creating a comment adds the author as page watcher, queues notifications (mentions extracted from content) and emits a websocket event. `findPageComments` returns comments with creator/resolvedBy and does not filter `deletedAt`. Comment rows carry `spaceId`.
- **L4 (2026-10-16, evidence):** mcp 2.3 elicitation probe: `Resolve(fn)` + `Elicit(message, schema)` works on both the 2026-07-28 protocol (input_required rounds) and legacy; accept/decline both delivered; without client elicitation support the call fails with a protocol error, detectable beforehand via `ctx.session.check_client_capability(ClientCapabilities(elicitation=...))`. Direct `ctx.elicit` has no back-channel on the modern protocol.
- **L5 (2026-10-16, T1 evidence):** RED: collection ImportError (`confirm_replace_from_env`). GREEN: 252 passed. `DocmostSettings.allow_comments` (DOCMOST_ALLOW_COMMENTS, default false, independent of read-only); the client's boolean parser is now public as `docmost_client.settings.env_flag`; `confirm_replace_from_env` (DOCMOST_CONFIRM_REPLACE, default true) lives in the MCP package because confirmation is an MCP-host concern.
- **L6 (2026-10-16, T2 evidence):** RED: 6 failed (missing method). GREEN: 258 passed; ruff, pyright clean. `list_recent_pages(space=None, limit, cursor)` in both clients over `/api/pages/recent` (UUID resolved through the allowlist before the request; results from disallowed spaces dropped; paging follows Docmost's page). New model `RecentPage` (no content; `updated_at`, `last_updated_by_id`, `space`). Fixture synthesized from baseFields + space; to be recorded in T6.
- **L7 (2026-10-16, T3 evidence):** RED: collection ImportError. GREEN first run: 286 passed; ruff, pyright clean. `list_comments(page_id)` (always allowed; prechecks the page for allowlist/trash/UUID; drops `deletedAt` comments; plain text with mentions as `@label`, blocks on separate lines) and `create_comment(page_id, text, parent_comment_id=None)` (refused with `COMMENTS_DISABLED` before any request unless `DOCMOST_ALLOW_COMMENTS`, in both read modes; plain text → ProseMirror paragraphs built client-side, so no mention nodes can be sent; size capped; page precheck; `type: page`; a 403 is rethrown with a hint about the space's viewer-comments setting). New model `Comment`, error `CommentsDisabledError`.
