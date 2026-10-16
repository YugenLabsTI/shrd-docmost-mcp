# Live smoke test setup

Prepares the configuration for a smoke test against the real Docmost instance. Nothing
here contacts Docmost.

```bash
uv run python dev/live/init_env.py          # creates dev/live/.env.live (git-ignored)
                                            # and an empty password file in ~/.config
# fill in both files
uv run python dev/live/init_env.py --check  # validates them offline
```

| Variable | What to put |
|----------|-------------|
| `DOCMOST_BASE_URL` | Instance URL (`https://` only) |
| `DOCMOST_EMAIL` | Dedicated agent account (password login, no MFA or SSO) |
| `DOCMOST_PASSWORD_FILE` | Prefilled path; write only the password into that file |
| `DOCMOST_LIVE_READ_SPACE` | A real space where the account is a **reader** |
| `DOCMOST_LIVE_SANDBOX_SPACE` | A sandbox space created for the test, where it is a **writer** |
| `DOCMOST_ALLOWED_SPACES` | Exactly the two spaces above, comma-separated |
| `DOCMOST_READ_ONLY` | Keep `1` |

Docmost adds every new member to the default space as a writer: remove the account from
it, or rely on `DOCMOST_ALLOWED_SPACES`, which `--check` requires to list only the two
test spaces.
