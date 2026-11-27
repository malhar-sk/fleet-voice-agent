/**
 * Control the simulated fleet and the stack, using exactly the commands the Makefile runs
 * (`make freeze`, `make chaos DEVICE=… MINUTES=…`, `make recover DEVICE=…`), so the tests exercise the
 * same path a person would. They need the `docker` CLI and access to the Docker socket.
 */
import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect } from "@playwright/test";

export const REPO = path.resolve(__dirname, "..", "..");
const COMPOSE = ["compose", "-f", path.join(REPO, "docker-compose.yml")];
export const VM_URL = process.env.VM_URL ?? "http://127.0.0.1:18428";
export const APP_URL = process.env.APP_URL ?? "http://127.0.0.1:17860";
export const DEVICES = ["pi-1", "pi-2", "pi-3", "pi-4", "pi-5"];
/** agent/fleet_tools.py SILENT_AFTER_S and the DeviceSilent rule: OFFLINE when silent for more than 120 s. */
export const SILENT_AFTER_S = 120;

function compose(...args: string[]): string {
  return execFileSync("docker", [...COMPOSE, ...args], { encoding: "utf8", timeout: 120_000, stdio: ["ignore", "pipe", "pipe"] });
}
const chaos = (...args: string[]) => compose("exec", "-T", "fleet-sim", "python", "-m", "fleet_sim.chaos", ...args);

export const fleet = {
  /** make freeze: no random flapping or breach bursts, so answers are predictable. */
  freeze: () => chaos("random", "off"),
  /** make unfreeze */
  unfreeze: () => chaos("random", "on"),
  /** make chaos DEVICE=<device> MINUTES=<minutes> */
  offline: (device: string, minutes: number) => chaos("offline", device, "--minutes", String(minutes)),
  /** make recover DEVICE=<device|all> */
  recover: (device = "all") => chaos("recover", device),
  stopService: (svc: string) => compose("stop", svc),
  startService: (svc: string) => compose("start", svc),
};

/** Seconds since each device last reported, straight from VictoriaMetrics (same expression as the alert rule). */
export async function secondsSilent(): Promise<Record<string, number>> {
  const q = 'max by (device_id) (time() - tlast_over_time(device_uptime_seconds{job="fleet-sim"}[1d]))';
  const r = await fetch(`${VM_URL}/api/v1/query?query=${encodeURIComponent(q)}`);
  if (!r.ok) throw new Error(`VictoriaMetrics query failed: ${r.status}`);
  const j = (await r.json()) as { data: { result: { metric: { device_id: string }; value: [number, string] }[] } };
  return Object.fromEntries(j.data.result.map((x) => [x.metric.device_id, Number(x.value[1])]));
}

/** Waits (polling, no fixed sleep) until the app answers /health with the model loaded. */
export async function waitForAppHealthy(timeoutMs = 240_000): Promise<void> {
  // Cold start loads Whisper small + Piper voices on 1 CPU: about 30-90 s on the build VPS.
  await expect
    .poll(async () => {
      try {
        const r = await fetch(`${APP_URL}/health`);
        return r.ok && ((await r.json()) as { engine_loaded?: boolean }).engine_loaded === true;
      } catch {
        return false;
      }
    }, { timeout: timeoutMs, intervals: [2_000] })
    .toBe(true);
}
