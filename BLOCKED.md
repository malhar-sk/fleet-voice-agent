# BLOCKED

## ~~CI workflow staged in ci/~~ RESOLVED 2026-11-23: token given workflow scope, file moved to `.github/workflows/ci.yml`

- **What:** GitHub rejects pushes that add files under `.github/workflows/` unless the token has the `workflow` scope.
  The build host's `gh` token has only `repo` (`gh auth status` → "Token scopes: 'repo'"). The previous project on this
  host was rejected for exactly this reason.
- **What I did:** committed the finished workflow at `ci/github-workflows/ci.yml` from the start, so no history
  rewrite or force-push is needed. It runs the unit tests with a fake VictoriaMetrics server and a mocked LLM (no
  secrets, no speech models), runs the n8n Code-node tests under Node 20, and validates `docker-compose.yml`. Exactly
  what it runs was checked locally in a clean Python 3.11 venv with only `requirements-ci.txt`: 66 passed.
- **Next step for a human (one command, from a machine whose git credentials can push workflows):**
  ```bash
  mkdir -p .github/workflows && git mv ci/github-workflows/ci.yml .github/workflows/ci.yml && git commit -m "Enable CI" && git push
  ```
  Or on github.com: *Add file → Create new file*, name it `.github/workflows/ci.yml`, and paste the contents.

## Not blocked, but not verifiable on this host (see RESULTS.md → NOT MEASURED)

- Telegram voice notes (no bot token): the n8n branch is built, and the "save to `alerts_out/`" mock branch is the one that ran.
- Anthropic API backend (no API key): unit-tested with a fake client. All measured LLM numbers used the `claude -p` CLI.
- Browser WebRTC on Windows / Docker Desktop: checked only with headless Chromium and an aiortc client on the Linux host.
