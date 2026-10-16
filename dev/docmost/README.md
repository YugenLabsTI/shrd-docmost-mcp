# Local Docmost for development

A disposable Docmost 0.96.0 (with Postgres and Redis) bound to `127.0.0.1:3000`, used to
record contract fixtures and run integration tests. Never point these scripts at a
production instance.

```bash
# 1. Secrets for the containers (git-ignored)
printf "APP_SECRET=%s\nPOSTGRES_PASSWORD=%s\n" "$(openssl rand -hex 32)" "$(openssl rand -hex 16)" > dev/docmost/.env

# 2. Start Docmost
docker compose -f dev/docmost/compose.yaml --env-file dev/docmost/.env up -d

# 3. Create the admin, the agent user, spaces and sample pages
uv run python dev/docmost/bootstrap.py   # writes dev/docmost/.env.test (git-ignored)

# Reset everything
docker compose -f dev/docmost/compose.yaml --env-file dev/docmost/.env down -v
```

Seeded data:

| Space | Agent role | Pages |
|-------|------------|-------|
| `engineering` | reader | Runbook (with a child), Rich page (table, callout, tasks, details, colors) |
| `sandbox` | writer | Scratch |
| `ops` | none | Ops secrets |
| `general` | writer (Docmost adds every new member to the default space) | none |
