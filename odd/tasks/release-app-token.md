# Feature: release PRs run CI without a manual approval

Objective: release-please opens and updates the release PR with a GitHub App token, so the PR's own pull_request CI runs without approval and the dispatch workaround goes away.
Branch: `ci/release-app-token` (from `main` f6e9602). Delivery: single PR (small). Checks: actionlint, zizmor; no pytest coverage for workflows.

## Specs

- **S1 — No approval per release.** "Después de eso quiero que hagamos el arreglo que dijiste para que no se repita cada release". The fix proposed earlier: "Que release-please use un token de GitHub App, así su PR dispara la CI normal y `release-pr-ci` deja de hacer falta. El costo es crear y rotar la App."
- **S2 — Inherited constraints.** No AI attribution, no instance data in the repo, pinned actions, least-privilege permissions, docs updated with behavior; push, PR and merge only with explicit OK.

Assumptions (agent decisions): an organization-owned GitHub App installed on this repository only, with Contents, Pull requests and Issues read/write; its client ID in an environment variable and its private key in an environment secret of a new `release` environment limited to `main`, so only the release job can read them; the token is requested with only those permissions; no fallback to `GITHUB_TOKEN` (a missing App fails the release job instead of silently bringing the approval back); Publish is still started by the release job with `GITHUB_TOKEN`.

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S1, S2 | inline | done | 54b985a, 67d9742, L3, L4 |
| T2 | S1 | user | pending | App created, environment `release` with variable and secret |

T1: release job requests the App token and passes it to release-please; remove `release-pr-ci` and the dispatch comment; README maintainers section. T2: the user creates the App (org admin) and stores its credentials; then merge.

High-risk: T1 (CI/release, item 5). Independent verifier before the PR.

## Log

- **L1 (2026-10-18, user, verbatim):** "Si dale! Después de eso quiero que hagamos el arreglo que dijiste para que no se repita cada release"
- **L2 (research):** GitHub changelog 2026-06-11, "Bot-created pull requests can run workflows if approved": PRs created by `github-actions[bot]` now run workflows only after a user with write access approves. Approving run 39139106546 through `POST /actions/runs/{id}/approve` unblocked PR #51. Repository fork approval policy: `first_time_contributors`. The user is an organization admin. `actions/create-github-app-token` v3.3.0 (commit 64ab729a6294000f5aa4a4bc0b73d1f32bc45510) takes `client-id` (`app-id` deprecated) and `permission-*` inputs.
- **L3 (verification):** independent verifier: S1 pass; S2 pass after B1. Confirmed both pins and their inputs, release-please uses `token` for every PR, label, tag and release call, the release job's GITHUB_TOKEN calls work read-only, a missing client ID or key fails the App step (no fallback), and a PR opened with an App token from a same-repo branch runs without approval (GITHUB_TOKEN docs). B1 fixed: the comments in ci.yml and publish.yml no longer say the dispatch exists because GITHUB_TOKEN tags start no workflows (Publish listens only to workflow_dispatch). A1 applied: the README says to limit `release` to `main` before storing the key (GitHub creates a missing environment unprotected). Accepted: each push to main adds a `release` deployment record (`deployment: false` not adopted, its interaction with branch policies unconfirmed); a broken App turns every release job red, by design.
- **L4 (review):** native review (risk, resilience, readability) approved and acknowledged (lineage review-54bcf34540cd2a41), no blockers. Suggestions: name the fix commit in the task table (applied); a preflight that explains a missing App credential before the action's own error (not adopted: the action already fails with "The 'client-id' ... must be set to a non-empty string", and the README names the variable and secret).
