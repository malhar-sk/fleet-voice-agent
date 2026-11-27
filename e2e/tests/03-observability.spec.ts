/**
 * Observability path: `make chaos` takes pi-4 offline; Grafana must (1) fire DeviceSilent within the rule's window,
 * (2) show pi-4 OFFLINE on the dashboard, and (3) list the alert as Firing in its alerting UI.
 *
 * The rule (grafana/provisioning/alerting/rules.yml): silent for MORE than 120 s, evaluated every 10 s, `for: 0s`.
 * The simulator pushes every 5 s and VictoriaMetrics answers with a 5 s latency offset, so counted from the chaos
 * command the alert should fire after ~120 s and by about 120 + 10 + 5 + 5 = 140 s. The test allows up to 180 s
 * (a loaded CI runner) and records the measured time; it also fails if the alert fires before 115 s.
 *
 * Selectors come from Grafana 13.3's accessibility tree as observed on the running stack: each panel is a
 * region named after its title; the per-device table is a grid of rows ("pi-4 OFFLINE …"); the alert list is a
 * tree with a "DeviceSilent" item holding an image named after its state ("Firing").
 */
import { execFileSync } from "node:child_process";
import { test, expect, type Page } from "@playwright/test";
import { fleet, SILENT_AFTER_S } from "../fixtures/fleet";

const GRAFANA = process.env.GRAFANA_URL ?? "http://127.0.0.1:13000";
const USER = process.env.GRAFANA_USER ?? "admin", PASSWORD = process.env.GRAFANA_PASSWORD ?? "admin";
const DEVICE = "pi-4";
const LATEST_S = 180, EARLIEST_S = SILENT_AFTER_S - 5;

/**
 * DEF-001 (intermittent): Grafana 13.3 runs right at its shipped 320 MiB limit, and at times every dashboard query
 * stalls. No measurable precondition predicted it reliably (run 3 rendered fine at >= 95 % of the limit), so these
 * UI tests assert the CORRECT behaviour, are listed as known flaky in README.md, and record Grafana's cgroup memory
 * on every run so a failure can be matched to DEF-001 from the report.
 */
function recordGrafanaMemory() {
  try {
    const id = execFileSync("docker", ["compose", "-f", `${__dirname}/../../docker-compose.yml`, "ps", "-q", "grafana"], { encoding: "utf8" }).trim();
    const read = (f: string) => Number(execFileSync("docker", ["exec", id, "cat", `/sys/fs/cgroup/${f}`], { encoding: "utf8" }).trim());
    const used = Math.round(read("memory.current") / 2 ** 20), limit = Math.round(read("memory.max") / 2 ** 20);
    test.info().annotations.push({ type: "grafana-memory", description: `${used} / ${limit} MiB (DEF-001 if this test fails)` });
  } catch (e) {
    test.info().annotations.push({ type: "grafana-memory", description: `not readable: ${(e as Error).message.slice(0, 80)}` });
  }
}

async function login(page: Page) {
  // waitUntil "commit": a memory-starved Grafana can take > 30 s to fire the load event (see DEF-001)
  await page.goto(`${GRAFANA}/login`, { waitUntil: "commit", timeout: 60_000 });
  await page.getByLabel("Email or username").fill(USER);
  await page.locator('input[name="password"]').fill(PASSWORD); // getByLabel("Password") also matches "Show password"
  await page.getByRole("button", { name: "Log in" }).click();
  const skip = page.getByRole("button", { name: "Skip" }); // first login with the default password offers a change
  await expect(skip.or(page.getByRole("link", { name: "Dashboards" }).first())).toBeVisible({ timeout: 60_000 });
  if (await skip.isVisible()) await skip.click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 60_000 });
}

async function deviceSilentFiring(request: import("@playwright/test").APIRequestContext): Promise<boolean> {
  const r = await request.get(`${GRAFANA}/api/prometheus/grafana/api/v1/alerts`, {
    headers: { Authorization: "Basic " + Buffer.from(`${USER}:${PASSWORD}`).toString("base64") }, timeout: 60_000 });
  expect(r.ok(), `Grafana alerts API: ${r.status()}`).toBe(true);
  const alerts = ((await r.json()).data?.alerts ?? []) as { labels: Record<string, string>; state: string }[];
  return alerts.some((a) => a.labels.alertname === "DeviceSilent" && a.labels.device_id === DEVICE && /alerting|firing/i.test(a.state));
}

test.describe.serial(`make chaos ${DEVICE} → Grafana`, () => {
  test.describe.configure({ timeout: 6 * 60_000 }); // a real 2-minute alert window plus a slow UI
  test.use({ viewport: { width: 1600, height: 1000 } });
  test.afterAll(() => fleet.recover(DEVICE));

  test("DeviceSilent fires after the 120 s threshold and within the rule's window", async ({ request }) => {
    expect(await deviceSilentFiring(request), `${DEVICE} must not be alerting before the test starts`).toBe(false);
    const t0 = Date.now();
    fleet.offline(DEVICE, 10);
    let firedAt = 0;
    // Poll every 5 s and record WHEN it first fires (no fixed sleep over the window).
    await expect.poll(async () => {
      const firing = await deviceSilentFiring(request);
      if (firing && !firedAt) firedAt = (Date.now() - t0) / 1000;
      return firing;
    }, { timeout: LATEST_S * 1000, intervals: [5_000], message: `DeviceSilent for ${DEVICE} within ${LATEST_S} s` }).toBe(true);
    test.info().annotations.push({ type: "measured", description: `DeviceSilent fired ${firedAt.toFixed(0)} s after make chaos` });
    console.log(`[observability] DeviceSilent for ${DEVICE} fired ${firedAt.toFixed(0)} s after make chaos`);
    expect(firedAt, "not before the 120 s threshold").toBeGreaterThanOrEqual(EARLIEST_S);
  });

  test("the dashboard shows the device OFFLINE", async ({ page }) => {
    recordGrafanaMemory();
    await login(page);
    await page.goto(`${GRAFANA}/d/fleet-voice?orgId=1&from=now-15m&to=now`, { waitUntil: "commit", timeout: 60_000 });
    const table = page.getByRole("region", { name: "Fleet: status per device" });
    await expect(table.getByRole("row", { name: new RegExp(`^${DEVICE} OFFLINE`) })).toBeVisible({ timeout: 60_000 });
    // pi-3 (global setup) and pi-4 (this file) are both silent for > 2 min
    await expect(page.getByRole("region", { name: "Devices OFFLINE (silent > 2 min)" })).toContainText(/\b2\b/);
    await page.screenshot({ path: test.info().outputPath("dashboard.png"), fullPage: true });
  });

  test("the alerting UI lists DeviceSilent as Firing", async ({ page }) => {
    recordGrafanaMemory();
    await login(page);
    await page.goto(`${GRAFANA}/alerting/list?search=DeviceSilent`, { waitUntil: "commit", timeout: 60_000 });
    const rule = page.getByRole("treeitem", { name: "DeviceSilent" });
    await expect(rule.getByRole("img", { name: "Firing" })).toBeVisible({ timeout: 60_000 });
    await page.screenshot({ path: test.info().outputPath("alert-list.png"), fullPage: true });
  });
});
