/**
 * Fake-microphone fixture and page object.
 *
 * Chromium's fake audio device plays ONE file per browser launch (--use-file-for-fake-audio-capture),
 * so each test launches its own browser with the clip it needs: `const app = await openApp(mic.clip("en01"))`.
 * Tracing is started by hand on that context; when a test fails (or an expected-to-fail defect test fails
 * as expected) the trace and a screenshot are attached, so every DEFECTS.md entry has evidence.
 */
import fs from "node:fs";
import path from "node:path";
import { test as base, expect, type Locator, type Page } from "@playwright/test";
import { REPO } from "./fleet";
import { durationS, padded, CACHE, LEAD_S } from "../scripts/prepare-audio";

export interface Question {
  id: string; lang: "en" | "hi" | "mr"; text: string; expected_tool: string; acceptable_tools: string[];
  expected_args: Record<string, unknown>; key_fact: string; audio: string;
}
const QUESTIONS: Record<string, Question> = Object.fromEntries(
  fs.readFileSync(path.join(REPO, "evals/questions.jsonl"), "utf8").split("\n").filter(Boolean)
    .map((l) => JSON.parse(l) as Question).map((q) => [q.id, q]));
interface ExtraClip { id: string; lang: "en" | "hi" | "mr"; text: string; file: string }
const EXTRA: Record<string, ExtraClip> = Object.fromEntries(
  (JSON.parse(fs.readFileSync(path.join(REPO, "e2e/audio/clips.json"), "utf8")).clips as ExtraClip[]).map((c) => [c.id, c]));

export const mic = {
  /** A question from evals/questions.jsonl (the repo's synthetic eval set), with its expectations. */
  question: (id: string): Question => QUESTIONS[id] ?? (() => { throw new Error(`no question ${id}`); })(),
  /** Padded WAV for an eval question or an e2e/audio clip; returns the absolute path Chromium plays. */
  clip: (id: string): string => padded(QUESTIONS[id]?.audio ?? EXTRA[id]?.file ?? (() => { throw new Error(`no clip ${id}`); })()),
  extra: (id: string): ExtraClip => EXTRA[id],
  silence: (): string => path.join(CACHE, "silence.wav"),
  /** How long push-to-talk must be held: lead silence + speech + a little tail. */
  holdSeconds: (file: string): number => Math.min(durationS(file), LEAD_S + (durationS(file) - LEAD_S) * 0.6 + 1.5),
};

export interface Turn { lang: string; transcript: string; answer: string; tools: string[] }

export class VoiceApp {
  readonly talk: Locator; readonly ptt: Locator; readonly status: Locator; readonly turns: Locator;
  constructor(readonly page: Page) {
    this.talk = page.getByTestId("talk-button");
    this.ptt = page.getByTestId("ptt-button");
    this.status = page.getByTestId("status");
    this.turns = page.getByTestId("turn");
  }
  async open() {
    await this.page.goto("/");
    await expect(this.talk).toBeVisible();
    await expect(this.status).toHaveText("idle");
  }
  /** Live mode: WebRTC to the Pipecat pipeline. The fake mic starts playing as soon as the mic opens. */
  async startLive() {
    await this.talk.click();
    await expect(this.status).toHaveText(/live: speak any time|listening…|thinking…/, { timeout: 20_000 });
  }
  async stopLive() {
    if ((await this.talk.textContent())?.includes("Stop")) await this.talk.click();
    await expect(this.status).toHaveText("idle");
  }
  /**
   * Push-to-talk: hold the button while the fake mic plays the clip. This is the one deliberate fixed wait in
   * the suite: the clip plays in real time and there is nothing on the page to wait for until release.
   */
  async holdToTalk(seconds: number) {
    await this.ptt.hover();
    await this.page.mouse.down();
    await expect(this.status).toHaveText(/recording/);
    await this.page.waitForTimeout(seconds * 1000);
    await this.page.mouse.up();
  }
  /** The newest turn (the log prepends). Waits for it to appear, then reads it through the data-testid hooks. */
  async nextTurn(timeout = 60_000): Promise<Turn> {
    // 60 s: STT (Whisper small, 1 CPU) takes ~5-8 s per question on the build VPS, plus VAD end-of-speech.
    const t = this.turns.first();
    await expect(t).toBeVisible({ timeout });
    return {
      lang: (await t.getAttribute("data-lang")) ?? "",
      transcript: (await t.getByTestId("turn-transcript").innerText()).trim(),
      answer: (await t.getByTestId("turn-answer").innerText()).trim(),
      tools: JSON.parse((await t.getAttribute("data-tools")) ?? "[]") as string[],
    };
  }
}

export const test = base.extend<{ openApp: (micFile: string) => Promise<VoiceApp> }>({
  openApp: async ({ playwright, baseURL }, use, testInfo) => {
    const opened: { close: () => Promise<void>; page: Page }[] = [];
    await use(async (micFile: string) => {
      const browser = await playwright.chromium.launch({
        args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
          `--use-file-for-fake-audio-capture=${micFile}`, "--autoplay-policy=no-user-gesture-required"],
      });
      const context = await browser.newContext({ baseURL, permissions: ["microphone"] });
      // Playwright traces this context itself (config `trace`), so no manual tracing.start here.
      const page = await context.newPage();
      page.on("console", (m) => { if (m.type() === "error") testInfo.annotations.push({ type: "console-error", description: m.text() }); });
      opened.push({ close: () => browser.close(), page });
      const app = new VoiceApp(page);
      await app.open();
      return app;
    });
    const failed = testInfo.status === "failed" || testInfo.status === "timedOut";
    for (const [i, o] of opened.entries()) {
      if (failed) {
        // Also for test.fail() defect tests, so each DEFECTS.md entry has a screenshot next to its trace.
        const shot = testInfo.outputPath(`failure-${i}.png`);
        await o.page.screenshot({ path: shot, fullPage: true }).catch(() => {});
        await testInfo.attach(`screenshot-${i}`, { path: shot, contentType: "image/png" }).catch(() => {});
      }
      await o.close();
    }
  },
});
export { expect };
