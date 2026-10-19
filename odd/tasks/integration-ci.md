# Feature: integration tests in CI against a disposable Docmost

Objective: a CI job `integration` starts the disposable Docmost from `dev/docmost`, seeds it and runs the integration tests on every pull request and push to `main` (issue #56).
Branch: `ci/integration-tests` from `main`. Delivery: single PR with `Closes #56`. Test runner: `uv run pytest`; the job itself is proven by a local run of its steps and by CI; workflows checked with actionlint and zizmor.

## Specs

- **S1 — The job.** Issue #56: "A CI job `integration` that runs the same setup as `dev/docmost/README.md`": "Generate throwaway `APP_SECRET` and `POSTGRES_PASSWORD` in the runner and start Docmost 0.96.0, Postgres and Redis with `dev/docmost/compose.yaml` (bound to `127.0.0.1`)", "Wait until Docmost answers, then run `dev/docmost/bootstrap.py`", "Run `DOCMOST_INTEGRATION=1 uv run pytest -m integration` with the generated `.env.test`", "Always tear down with `docker compose down -v`."
- **S2 — Rollout.** "Runs on every pull request and push to `main`, but is not a required check at first; it becomes required once it has proven stable." "The Docmost, Postgres and Redis images are pinned by digest, and Dependabot proposes their updates." The Docmost version matrix is a later, separate issue.
- **S3 — Safety.** "Everything is disposable and local to the runner: no repository secrets, no real instance, nothing persisted, so it runs the same on pull requests from forks. The job's token is read-only."
- **S4 — Inherited constraints.** No AI attribution, no instance data, pinned actions, least privilege, docs updated with behavior; push, PR, merge and repository settings only with explicit OK.

Assumptions (agent decisions): the job fails when any integration test is skipped, so a missing variable cannot turn it green; it is not added to the release job's `needs` while it is not required; container logs are printed on failure (the data is disposable).

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S1-S4 | inline | done locally, CI run pending | 6f4b294, fix commit, L4-L5 |

T1: digests in `compose.yaml`, Docker Compose updates in `dependabot.yml`, job `integration` in `ci.yml`, docs (`dev/docmost/README.md`, CONTRIBUTING, README).

High-risk: T1 (CI, item 5). Its own checks are a local run of the job's steps, actionlint, zizmor and the CI run; an independent verifier before the PR.

## Log

- **L1 (2026-10-18, user, verbatim):** "Llévate esas indicaciones a engram! Y si, vamos con el issue"
- **L2 (2026-10-18, user, verbatim):** "Listo, aprobado!" (issue #56 labelled `status:approved`).
- **L3 (2026-10-18):** Image index digests (multi-arch) read with `docker buildx imagetools inspect`: docmost/docmost:0.96.0 `sha256:b56947fc…`, postgres:18 `sha256:74935e72…`, redis:8 `sha256:2c2dff79…`.
- **L4 (2026-10-18):** Local checks: actionlint ok; zizmor no findings; `uv run pytest` 659 passed, 26 skipped; the skip guard exits 1 on a real junit file with 26 skipped. No local run of the job's steps: port 3000 on the maintainer's machine is held by an SSH tunnel, so nothing was sent to it. Native assess: `high`, `review_due` true (high_risk).
- **L5 (2026-10-18, independent verifier):** S2-S4 met; S1 partial. Blocker B1: Docmost 0.96.0 throttles `AuthController` at 10 requests per 60 s per IP (`throttle.module.ts`, confirmed by the parent); seeding logs in twice and the tests 10 times, so the last tests would get HTTP 429. Fix: wait 65 s after seeding. Advisories fixed: health `curl --max-time 5`; logs and teardown run only when `dev/docmost/.env` exists; compose comment now says README step 1 creates `.env`. Open: Dependabot listing `/dev/docmost` is confirmed on its first run; B1 is proven only by the CI run.
