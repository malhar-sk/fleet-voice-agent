import { defineConfig } from "@playwright/test";

/**
 * One worker, files in order (01-voice, 02-edge, 03-observability):
 * - there is ONE voice pipeline (1 CPU) and ONE simulated fleet; parallel tests would fight over both
 *   and make timings meaningless;
 * - 02-edge stops and restarts the backend, and 03-observability takes pi-4 offline, so they run after
 *   the voice journeys, which rely on a known fleet state (pi-3 offline, everything else online).
 * Retries only in CI (flaky tests must be listed in README.md "Known flaky tests", not hidden).
 */
export default defineConfig({
  testDir: "./tests",
  globalSetup: "./fixtures/global-setup.ts",
  globalTeardown: "./fixtures/global-teardown.ts",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  // A voice turn on the 1-CPU app takes ~5-15 s (Whisper small on CPU), so the default 30 s is too tight;
  // the observability test sets its own, longer timeout.
  timeout: 120_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never" }], ["json", { outputFile: "test-results/results.json" }]],
  use: {
    baseURL: process.env.APP_URL ?? "http://127.0.0.1:17860",
    // "on", not "retain-on-failure": tests marked test.fail() for a known defect must keep their trace as evidence.
    trace: "on",
    screenshot: "only-on-failure",
  },
});
