# Feature: official support for Docmost 0.97.0

Objective: `docmost-client` and `yugen-docmost-mcp` officially support Docmost 0.97.0 next to 0.96.0, backed by the same evidence (API reference, recorded contract fixtures, integration tests) (issue #64).
Branch: `feat/docmost-0.97.0` from `main` (4a60146). Delivery: single PR with `Closes #64`; it supersedes Dependabot #61. Test runner: `uv run pytest` (unit + contract); integration with `DOCMOST_INTEGRATION=1 uv run pytest -m integration` against the local Docmost from `dev/docmost`.

## Specs

- **S1 — API review.** Issue #64: "Review the `v0.96.0...v0.97.0` diff of `docmost/docmost` for every endpoint and DTO the client uses (auth, version, spaces, pages, search, comments, history, move) and document the differences next to `docs/docmost-api-v0.96.0.md`." "If the diff shows a breaking change in an endpoint we use, the fix goes in this issue before the version is added."
- **S2 — New content nodes.** Issue #64: "Check that pages that use the new content nodes (tabs, the updated subpages) still read correctly as markdown and html, and that rewriting a page does not silently drop them." Scope chosen by the user (L3): tabs are documented in the loss matrix and the server instructions, and integration tests pin the html round-trip and the markdown read shape; the markdown-replace guard is out of scope (issue #65).
- **S3 — Evidence.** Issue #64: "Move the dev Docmost to `docmost/docmost:0.97.0`, pinned by digest (this supersedes #61), re-record the contract fixtures, and run the integration tests."
- **S4 — Supported versions.** Issue #64: "Add `"0.97.0"` to `SUPPORTED_DOCMOST_VERSIONS` and keep `0.96.0`, so instances that have not upgraded keep working."
- **S5 — Docs.** Issue #64: "Update the README compatibility table, `dev/docmost` docs, and the bug report placeholder."
- **S6 — Inherited constraints.** No AI attribution, no instance data, docs updated with behavior; push, PR, merge and repository settings only with explicit OK. Safety (issue #64): "No new tools or write paths. The version guard and `DOCMOST_ALLOW_UNTESTED_VERSION` keep their current behavior."

Assumptions (agent decisions): the 0.96.0 recorded fixtures stay and the contract tests run against both versions; 0.97.0 fixtures live in `tests/fixtures/v0_97_0/recorded`; `record_fixtures.py` writes to the directory of the version the local Docmost reports; the integration tests run only against the version in `compose.yaml` (0.97.0), so 0.96.0 keeps its evidence through its recorded fixtures.

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S1 | delegated explore (mapping trigger: upstream diff of 15 endpoints and the conversion code), parent writes the doc inline | done | c68f902, L5-L6 |
| T2 | S3, S4, S5 | inline | done | c68f902, review fixes, L6-L8 |
| T3 | S2 | inline | done | c68f902, L6 |

T1: `docs/docmost-api-v0.97.0.md` (delta against the 0.96.0 reference) plus any client fix the diff requires.
T2: `compose.yaml` digest and comments, `dev/docmost` docs, `record_fixtures.py` output by version, `v0_97_0/recorded` fixtures, contract tests over both versions, `SUPPORTED_DOCMOST_VERSIONS`, version assertions in tests, README table, bug report placeholder.
T3: integration tests for tabs (html round-trip, markdown read shape), loss matrix row, tabs in the server instructions.

High-risk: c68f902 touches item 5 (the dev Docmost image that CI's `integration` job runs). Its own checks are the local suite, a local integration run and the CI run; an independent verifier before the PR.

## Log

- **L1 (2026-11-06, user, verbatim):** "Okey, quiero que le demos soporte oficial, iniciemos el proceso!!"
- **L2 (2026-11-06, user, verbatim):** "Vale, pone ele aprobado y vamos allá!! Evaluemos si tambien hay que dar algun soporte adicional para el tema de tabs que mencionaste" (issue #64 labelled `status:approved`).
- **L3 (2026-11-06, user, verbatim):** "Si, vamos como dices" (option 1: docs and tests for tabs inside #64; the guard goes to issue #65, `status:needs-review`).
- **L4 (2026-11-06):** Prerequisite #66 (certifi PYSEC-2026-4320, which failed `audit` on every PR) merged as PR #67 (4a60146) on "Si! Y continua de inmediato". Tabs evidence (Docmost PR #2381): nodes `tabs` > `tab` (`data-tab-id`) > `tabLabel` + `tabPanel`, all `div[data-type]`; html round-trips; the markdown read renders each tab as `#### <label>` plus its content; markdown has no syntax to create tabs. Our outline lists only top-level headings and section editing rejects nested heading ids, so tabs are not reachable as sections.
- **L5 (2026-11-06, explorer):** All 46 commits of `v0.96.0...v0.97.0` reviewed (compare API caps at 300 files, so per commit). No breaking change. Changes: `format` defaults to `json` on create/update; sidebar items gain `updatedAt` (ignored); search `query` max 200 characters and highlights from the first 100,000 characters; client IP for throttling now trusts `X-Forwarded-For` only through private hops; markdown tables get a real header row and details become `<details markdown="1">`; new nodes tabs, integrationCard, integrationMention, subpages `sortBy`; `happy-dom` 20.8.9 to 21.0.4. Not verified: the private Enterprise submodule. Correction from the recorded fixture: content without `format` fails with 400 "Invalid content format" (text parsed as json), not accepted.
- **L6 (2026-11-06):** Evidence. Recorded `v0_97_0` fixtures: same files and fields as 0.96.0 except sidebar `updatedAt` and the `content_without_format` message. Integration against local 0.97.0: 27 passed (incl. the new tabs test). Live probes: table header row, `<details markdown="1">`, 201-character search returns `INVALID_INPUT` "query must be shorter than or equal to 200 characters". RED: `test_every_tested_docmost_version_is_supported` fails without the `compat.py` change (2 failed); GREEN suite 691 passed, 27 skipped; ruff, format, pyright clean. Untested-version unit tests now use `99.0.0`. Commit c68f902 (`feat(client): support Docmost 0.97.0`, Refs #64), about 315 authored lines plus 796 generated fixture lines. Follow-ups, not in scope: a client-side 200-character check for search; raising the MCP's `docmost-client` floor so upgrades pull 0.97.0 support.
- **L7 (2026-11-06, independent verifier):** S1-S6 met, no blockers. 7 upstream claims spot-checked at v0.97.0; compose digest equals the image index digest; contract tests 28 → 58 (each version); base 659 passed / head 691 passed; untested-version message differs only in the version list. Advisories: docstrings in `client.py`/`models.py` still said v0.96.0; the README row for `yugen-docmost-mcp` 0.1.2 relies on `docmost-client` 0.1.2, which the MCP's `>=0.1.0` floor does not force.
- **L8 (2026-11-06):** Native review granted by the user ("Revisar este cambio"), lens reliability: approved and acknowledged on f947f45. Findings: WARNING README compatibility row claims MCP 0.1.2 supports 0.97.0 without a floor; SUGGESTION pin the 200-character search limit. Fixed in the next commit: the table is keyed by `docmost-client` with a note to upgrade it; integration test `test_search_queries_are_limited_to_200_characters`; docstrings no longer name one version. Suite 691 passed, 28 skipped; integration 28 passed. Open decision for the user: raise the MCP's `docmost-client` floor to 0.1.2.

