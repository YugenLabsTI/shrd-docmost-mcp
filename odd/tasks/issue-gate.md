# Feature: every pull request links an approved issue

Objective: issues are triaged with `status:*` labels, and a required check refuses pull requests that do not link an issue labelled `status:approved`, for maintainers too; release-please and Dependabot are exempt.
Branch: `ci/issue-gate`, stacked on `docs/contributing` (PR #53). Delivery: single PR after #53 merges. Test runner: `uv run pytest` (dev/); workflows checked with actionlint and zizmor.

## Specs

- **S1 — Triage labels.** "¿Hay algo al respecto de que un issue necesite ser evaluado y que finalmente se le dé la etiqueta de aprobación o aprobado para desarrollar?" New issues start as `status:needs-review`; a maintainer moves them to `status:approved`, `status:needs-info` or `status:needs-design`.
- **S2 — Linked approved issue.** "O algo como que todo PR debe estar ligado a un issue?" A pull request must reference an issue with `Closes #N`, `Fixes #N`, `Resolves #N` or `Refs #N` (not inside an HTML comment), and every referenced issue must carry `status:approved`; otherwise the check fails and says why.
- **S3 — Applies to maintainers.** "Me gusta, porque hacemos de este un mejor producto, aunque también me aplique a mi". Only the release App and Dependabot are exempt.
- **S4 — Inherited constraints.** No AI attribution, no instance data, pinned actions, least privilege, docs updated with behavior; push, PR, merge and repository settings only with explicit OK.

Assumptions (agent decisions): the check runs on `pull_request_target` from the base branch's code and never checks out or runs the pull request's code, so a pull request cannot rewrite the check that judges it; exemption by exact login, not by account type; a label added to the issue later needs the check re-run (or the description edited); the `issue` check becomes required in the `main` ruleset after merge; no PR size limit for now.

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S2, S3 | inline | done | bb83cef, e4fa09a, L4-L6 |
| T2 | S1, S4 | inline | done | d25982a, L4 |
| T3 | S2 | user OK | pending | labels created, ruleset requires `issue` |

T1: `.github/scripts/check_issue_link.py` with tests in `dev/`, workflow `issue-link.yml`. T2: templates add `status:needs-review`, PR template `Closes #`, CONTRIBUTING flow. T3: create the labels, add `issue` to the required checks after merge.

High-risk: T1 (CI guard, `pull_request_target`, items 2 and 5). Independent verifier before the PR.

## Log

- **L1 (2026-10-18, user, verbatim):** "Hacele, abrí el PR y esta vez lo reviso porque quiero ver bien cómo quedaron las plantillas. ¿Hay algo al respecto de que un issue necesite ser evaluado y que finalmente se le dé la etiqueta de aprobación o aprobado para desarrollar? O algo como que todo PR debe estar ligado a un issue? No se, yo me guío bastante del repo de gentle-ai"
- **L2 (2026-10-18, user, verbatim):** "Me gusta, porque hacemos de este un mejor producto, aunque también me aplique a mi"
- **L3 (research):** gentle-ai uses labels `status:needs-review`, `status:approved` ("Approved for implementation — PRs can now be opened"), `status:needs-info`, `status:needs-design`, and `pr-check.yml` jobs "Check Issue Reference" (Closes/Fixes/Resolves/Refs #N, HTML comments ignored, fails closed on errors) and "Check Issue Has status:approved".
- **L4 (evidence):** RED: `dev/test_check_issue_link.py` failed to collect (script missing). GREEN: 30 passed; full suite 639 passed, 26 skipped; ruff, format and pyright clean; actionlint ok; zizmor no findings (dangerous-triggers ignored with reason). Probe against the GitHub API: `Closes #53` -> "#53 is a pull request, not an issue" (rc 1), `Refs #99999` -> "#99999 does not exist" (rc 1), no reference -> "This pull request links no issue." (rc 1). T2: issue forms add `status:needs-review`; PR template starts with `Closes #`; CONTRIBUTING "Issues first"; README ruleset paragraph names the `issue` check and the exempt list.
- **L5 (verification):** independent verifier: S1-S4 pass, no blockers. Confirmed on a live repository that a `pull_request_target` check run carries the PR head SHA and app 15368, so it can satisfy a required check; the token is read-only and the body only reaches the script as data; exemption by exact login; errors fail closed. Applied: A1 checkout uses the event's default ref (the default branch's latest commit, where the workflow file comes from since 2025-12-08) instead of `base.sha`; A3 references in fenced or inline code and after an unclosed `<!--` no longer count; A4 tests pin `fetch_from_github` (404/410 -> None; 401, 500, network errors raise). Pending (T3): create the four labels at merge (issue forms skip missing labels silently), then require `issue`. Accepted: A5, the runner image's python3 (3.12 on ubuntu-latest) must stay >= 3.10.
- **L6 (review):** native review (risk, resilience, readability, reliability) approved and acknowledged (lineage review-6fdcbd256bf164a4), no blockers. Applied after approval: a one-line ```code``` span no longer opens a fence that swallowed every later reference (RED: the previous parser returned [] for "```Closes #8``` inline\nCloses #7", now [7]); GitHub 5xx, 429, rate-limited 403 and network errors are retried 3 times (2 s, 4 s) and then fail with "Could not read the linked issues from GitHub ...; re-run this check." instead of a traceback; a clearer assertion in one test; README says how to recover when a broken check on main blocks its own fix. Accepted: code blocks indented four spaces still count (an approved issue is still required); the docs describe the required check, which T3 turns on right after the merge.
