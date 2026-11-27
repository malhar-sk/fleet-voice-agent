/**
 * Puts the stack into a KNOWN state before any test runs:
 *   - the app is healthy (Whisper + Piper loaded) and LLM_BACKEND resolves to the offline rules router
 *     (no Anthropic key needed, so anyone can reproduce the run);
 *   - the fleet is frozen (no random flapping), pi-3 is forced offline, every other device is online;
 *   - pi-3 has been silent for MORE than 120 s, so the app and Grafana both call it OFFLINE.
 * Then every voice journey has a key fact we know in advance: "pi 3" is the offline device.
 */
import { expect } from "@playwright/test";
import { APP_URL, DEVICES, SILENT_AFTER_S, fleet, secondsSilent, waitForAppHealthy } from "./fleet";
import { makeSilence } from "../scripts/prepare-audio";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export default async function globalSetup() {
  makeSilence();
  await waitForAppHealthy();
  const health = (await (await fetch(`${APP_URL}/health`)).json()) as { llm_backend: string };
  if (health.llm_backend !== "rules" && !process.env.E2E_ALLOW_LLM) {
    throw new Error(`The suite expects the offline rules router (no ANTHROPIC_API_KEY); the app reports '${health.llm_backend}'. ` +
      "Unset the key and restart voice-app, or set E2E_ALLOW_LLM=1 to run against the LLM anyway.");
  }

  fleet.freeze();
  for (const d of DEVICES.filter((d) => d !== "pi-3")) fleet.recover(d);
  fleet.offline("pi-3", 120); // long enough for the whole run; global teardown recovers it

  // pi-3 must cross the 120 s line and the others must be reporting again. Polling, not a sleep:
  // this takes ~0 s when pi-3 is already silent (a previous run) and up to ~2.5 min from scratch.
  const t0 = Date.now();
  await expect
    .poll(async () => {
      const s = await secondsSilent();
      const othersOnline = DEVICES.filter((d) => d !== "pi-3").every((d) => (s[d] ?? Infinity) < 30);
      return othersOnline && (s["pi-3"] ?? 0) > SILENT_AFTER_S + 10;
    }, { timeout: 240_000, intervals: [5_000], message: "pi-3 offline (>130 s silent) and pi-1,2,4,5 online" })
    .toBe(true);
  console.log(`[global-setup] fleet ready in ${((Date.now() - t0) / 1000).toFixed(0)} s: pi-3 offline, others online, random flapping off`);

  // Facts about this run, for e2e/report/RUN_REPORT.md (scripts/make-report.mjs). Written under .cache because
  // Playwright empties test-results/ when the run starts.
  const e2e = path.resolve(__dirname, "..");
  const pw = JSON.parse(fs.readFileSync(path.join(e2e, "node_modules/@playwright/test/package.json"), "utf8")).version;
  fs.mkdirSync(path.join(e2e, ".cache"), { recursive: true });
  fs.writeFileSync(path.join(e2e, ".cache", "run-env.json"), JSON.stringify({
    llm_backend: health.llm_backend,
    host: `${os.cpus().length} CPU, ${Math.round(os.totalmem() / 2 ** 30)} GB RAM, ${os.platform()} ${os.release()}${process.env.CI ? " (CI)" : ""}`,
    playwright: pw,
    node: process.version,
    fleet: `pi-3 forced offline and silent > 130 s after ${((Date.now() - t0) / 1000).toFixed(0)} s of setup; pi-1, 2, 4, 5 online; random flapping off`,
  }, null, 1));
}
