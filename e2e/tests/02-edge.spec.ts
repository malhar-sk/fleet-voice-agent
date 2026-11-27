/**
 * Edge cases. The bar for each one: the page never goes blank or hangs, and the user can see what happened
 * (a message, a reply that says why, or a clear "nothing heard"), and can try again.
 */
import { test, expect, mic } from "../fixtures/voice";
import { mentionsDevice, replyLanguage } from "../fixtures/lang";
import { fleet, waitForAppHealthy } from "../fixtures/fleet";

test.describe("silence", () => {
  test("live mode with a silent mic: stays ready, invents no turn, can be stopped", async ({ openApp }) => {
    const app = await openApp(mic.silence());
    await app.startLive();
    // Asserting that something does NOT happen needs a window of time; 15 s is longer than any real turn took
    // (5-12 s), so a turn invented from silence would have shown up by then.
    await app.page.waitForTimeout(15_000);
    await expect(app.turns).toHaveCount(0);
    await expect(app.status).toHaveText(/live: speak any time|listening…/);
    await app.stopLive();
  });

  test("push-to-talk with a silent mic: the user is told nothing was heard", async ({ openApp }) => {
    test.fail(true, "DEF-002 (e2e/DEFECTS.md#def-002): silence is transcribed as 'अपने �', tagged Marathi, and answered");
    const app = await openApp(mic.silence());
    await app.holdToTalk(3);
    // Either a turn saying "(nothing heard)" or a visible status message; never a silent return to idle.
    await expect(app.turns.first().or(app.status.filter({ hasText: /error|nothing|no speech/i }))).toBeVisible({ timeout: 60_000 });
    const shown = (await app.turns.count()) ? await app.turns.first().innerText() : await app.status.innerText();
    expect(shown).toMatch(/nothing heard|no speech|error/i);
  });
});

test("noisy clip (en01 + pink noise, babble and hum at 10 dB SNR): still names the offline device", async ({ openApp }) => {
  const app = await openApp(mic.clip("en01_noisy"));
  await app.startLive();
  const turn = await app.nextTurn();
  await app.stopLive();
  test.info().annotations.push({ type: "turn", description: JSON.stringify(turn) });
  expect.soft(turn.lang).toBe("en");
  expect(mentionsDevice(turn.answer, "pi-3"), turn.answer).toBe(true);
});

test.describe("questions no tool can answer", () => {
  for (const id of ["en_oos_weather", "hi_oos_cricket"]) {
    const c = mic.extra(id);
    test(`${id} [${c.lang}] "${c.text}": says what it can answer, calls no tool, same language`, async ({ openApp }) => {
      const app = await openApp(mic.clip(id));
      await app.startLive();
      const turn = await app.nextTurn();
      await app.stopLive();
      test.info().annotations.push({ type: "turn", description: JSON.stringify(turn) });
      expect.soft(turn.tools, "no fleet tool for an off-topic question").toEqual([]);
      expect.soft(replyLanguage(turn.answer), turn.answer).toBe(c.lang);
      // The reply must steer the user back to what it CAN do, not make something up.
      expect(turn.answer, "mentions the fleet / devices").toMatch(/fleet|device|फ़्लीट|डिवाइस|उपकरण/i);
      expect(turn.answer, "does not invent a weather or score answer").not.toMatch(/°|degrees|runs|रन|डिग्री/);
    });
  }
});

test.describe("backend down", () => {
  // These stop the voice-app container, so they restore it afterwards and wait until it is healthy again.
  test.afterEach(async () => {
    fleet.startService("voice-app");
    await waitForAppHealthy();
  });

  test("live mode when the backend is down: a visible error and the button resets", async ({ openApp }) => {
    test.fail(true, "DEF-003 (e2e/DEFECTS.md#def-003): the error is written to the status and overwritten with 'idle' in the same tick");
    const app = await openApp(mic.clip("en01"));
    fleet.stopService("voice-app");
    await app.talk.click();
    await expect(app.status).toHaveText(/error|failed/i, { timeout: 20_000 });
    await expect(app.talk).toHaveText(/Talk/);
    await expect(app.page.locator("h1")).toHaveText("Fleet voice agent"); // page still rendered, not blank
  });

  test("push-to-talk when the backend is down: a visible error, not a stuck 'thinking…'", async ({ openApp }) => {
    const file = mic.clip("en01");
    const app = await openApp(file);
    fleet.stopService("voice-app");
    await app.holdToTalk(mic.holdSeconds(file));
    await expect(app.status).toHaveText(/error|failed/i, { timeout: 20_000 });
  });

  test("backend dies in the middle of a live turn: the user is told, the page does not hang", async ({ openApp }) => {
    const app = await openApp(mic.clip("en01"));
    await app.startLive();
    await expect(app.status).toHaveText(/listening…|thinking…/, { timeout: 20_000 });
    fleet.stopService("voice-app");
    // WebRTC notices a dead peer through ICE consent checks, which can take ~30 s in Chromium.
    await expect(app.status).toHaveText(/error|failed|disconnected/i, { timeout: 45_000 });
  });
});
