#!/usr/bin/env bash
# Run the suite inside the official Playwright image, for hosts without Chromium's system libraries
# (e.g. a shared server where you cannot apt-get). The stack must already be up (`make up`).
#   bash e2e/run-in-docker.sh                 # whole suite
#   bash e2e/run-in-docker.sh tests/01-voice.spec.ts --grep en01
# After the run it writes e2e/report/RUN_REPORT.md (scripts/make-report.mjs), whatever the result.
# The repo is mounted at the same path as on the host and the host's docker CLI + socket are passed in,
# so the fleet-control helpers (the same commands as `make chaos` / `make recover`) work inside the container.
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE=mcr.microsoft.com/playwright:v1.65.1-noble   # keep in step with @playwright/test in e2e/package.json
PLUGINS=/usr/libexec/docker/cli-plugins
[ -d "$PLUGINS" ] || PLUGINS=/usr/lib/docker/cli-plugins
exec docker run --rm --network host --ipc=host \
  -u "$(id -u):$(id -g)" --group-add "$(stat -c %g /var/run/docker.sock)" -e HOME=/tmp -e CI \
  -e APP_URL -e VM_URL -e GRAFANA_URL -e GRAFANA_USER -e GRAFANA_PASSWORD -e E2E_ALLOW_LLM \
  -v "$PWD:$PWD" -w "$PWD/e2e" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(command -v docker):/usr/bin/docker:ro" -v "$PLUGINS:/usr/libexec/docker/cli-plugins:ro" \
  "$IMAGE" sh -c 'npm ci --no-audit --no-fund --loglevel=error && { npx playwright test "$@"; rc=$?; node scripts/make-report.mjs; exit $rc; }' sh "$@"
