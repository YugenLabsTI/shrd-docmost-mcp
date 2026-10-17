# Feature: local audit log, operator report and agent summary

Objective: record what the agent did through this server (writes and refused attempts) without any page content, give operators a trusted report, and optionally let the agent summarize its own recent activity.
Branch: `feat/audit-log` (from `main` 9e13166). Delivery: ask-on-risk; feature branch chain if over ~400 lines (cached). Test runner: `uv run pytest` (+ opt-in `-m integration` against `dev/docmost`).

## Specs

- **S1 — Audit log.** Roadmap: "Local write audit log: who changed what, recording only IDs/operations/timestamps, never page content (S10)." Accepted scope (L2): "Log JSONL append-only (escrituras + intentos rechazados, sin contenido)".
- **S2 — Operator report.** "comando `audit report` para el operador".
- **S3 — Agent summary.** "un recurso/tool de solo lectura para el agente, apagado por defecto (DOCMOST_AUDIT_EXPOSE=1)".
- **S4 — Inherited constraints.** Read-only by default, allowlist in the client, no credentials or content in logs/errors, TDD, typed errors, never the live instance without authorization, no AI attribution, no instance data in the repo, minimal dependencies; help text and docs updated with behavior.

Assumptions (agent decisions): enabled only when `DOCMOST_AUDIT_LOG` names a file (no surprise files); writes, comments and moves are always recorded, reads only with `DOCMOST_AUDIT_READS=1`; events are JSON lines with `ts`, `session`, `call`, `phase`, `tool`, `kind` (read/write), allowlisted id/enum arguments (`page_id`, `space`, `parent_page_id`, `operation`, `format`, `heading_id`, `after_page_id`, `placement`, `parent_comment_id`, values truncated to 128 chars), `outcome` (`ok`/`error`), `code`, `duration_ms`, `result_page_id`; never content, titles, comment text, search queries or icons; file created with mode 0600; write tools fail closed: a `started` line is written first and the call is refused with `AUDIT_UNAVAILABLE` if it cannot be written; the `finished` line is best effort (a warning on stderr); a `started` without `finished` is reported as interrupted; startup fails (exit 2) when the log cannot be opened; report `yugen-docmost-mcp audit report [--since 7d|24h] [--json] [--file PATH]`; agent tool `audit_summary(since_hours)` (read-only) registered only with the log and `DOCMOST_AUDIT_EXPOSE=1`; no rotation (documented: use logrotate with copytruncate).

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S1, S4 | inline | done | L3 |
| T2 | S1, S4 | inline | pending | |
| T3 | S2, S4 | inline | pending | |
| T4 | S3, S4 | inline | pending | |

T1 audit module (settings, sanitized events, append with 0600, fail-closed start, best-effort finish, reading and summarizing). T2 wire it into every tool call through the server's tool guard. T3 `audit report` CLI. T4 `audit_summary` tool, docs (README, SECURITY, CHANGELOG), integration test against the local Docmost.

High-risk: T1, T2 (writes to disk on every call; a governance control). Independent verifier at the feature's end.

## Log

- **L1 (2026-10-17, user, verbatim):** "Dale, sigamos con auditoria. Creo que la tienes muy clara, pero adicional a lo que me expusiste, ¿Crees que genere valor una tool de auditoria donde genere reporte de auditoria o simlemente pueda dar un panorama amplio de como ha sido el comportamiento con base a los logs?"
- **L2 (2026-10-17, user decision):** "Log + reporte CLI + panorama MCP (Recommended)" — "Log JSONL append-only (escrituras + intentos rechazados, sin contenido), comando `audit report` para el operador, y un recurso/tool de solo lectura para el agente, apagado por defecto (DOCMOST_AUDIT_EXPOSE=1)."
- **L3 (2026-10-17, T1 evidence):** RED: ModuleNotFoundError. GREEN: 16 tests; ruff, pyright clean. `yugen_docmost_mcp/audit.py`: `audit_settings_from_env` (flags need the log), `AuditLog.open` (creates/appends with `os.open(..., 0o600)`, ConfigError when impossible), `wants` (writes always, reads on request), `started` (raises `AuditUnavailableError` / `AUDIT_UNAVAILABLE`), `finished` (best effort, warning without system details), allowlisted string arguments cleaned of control characters and truncated to 128 chars, one `os.write` per line with `O_APPEND`; `read_events` (skips malformed lines, `since` filter) and `summarize` (calls, ok/error per tool, errors by code, spaces, pages written/refused, interrupted calls, first/last).
