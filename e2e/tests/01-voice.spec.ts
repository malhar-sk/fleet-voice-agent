/**
 * Voice journeys: a synthetic speech clip is played into the page as the microphone, the app transcribes it,
 * picks a tool, answers, and speaks. Global setup has put the fleet in a known state: pi-3 OFFLINE
 * (silent > 2 min), pi-1/2/4/5 online, no random flapping.
 *
 * What is asserted for each turn (never exact sentences: speech-to-text varies):
 *   1. a transcript appears, in the right script, tagged with the right language;
 *   2. the reply is in the SAME language as the question;
 *   3. the reply contains the key fact (the offline device is pi 3; a metric reply names the device and a number);
 *   4. the tool the agent called is one the eval set accepts for that question.
 */
import { test, expect, mic } from "../fixtures/voice";
import { mentionsDevice, replyLanguage, script } from "../fixtures/lang";

const OFFLINE = "pi-3";

test.describe("live voice (WebRTC): which devices are offline?", () => {
  for (const id of ["en01", "hi01", "mr01"]) {
    const q = mic.question(id);
    test(`${id} [${q.lang}] "${q.text}"`, async ({ openApp }) => {
      const app = await openApp(mic.clip(id));
      await app.startLive();
      const turn = await app.nextTurn();
      await app.stopLive();

      test.info().annotations.push({ type: "turn", description: JSON.stringify(turn) });
      expect.soft(turn.transcript, "a transcript is shown").not.toBe("");
      expect.soft(script(turn.transcript), "transcript script").toBe(q.lang === "en" ? "latin" : "devanagari");
      expect.soft(turn.lang, "language the app detected").toBe(q.lang);
      expect.soft(replyLanguage(turn.answer), `reply language for: ${turn.answer}`).toBe(q.lang);
      expect.soft(mentionsDevice(turn.answer, OFFLINE), `reply names the offline device: ${turn.answer}`).toBe(true);
      expect(turn.tools.length, `exactly one tool call: ${turn.tools}`).toBe(1);
      expect(q.acceptable_tools, "the tool is one the eval set accepts").toContain(turn.tools[0]);
    });
  }
});

test.describe("live voice (WebRTC): device-specific questions", () => {
  test("en07 [en] temperature of pi 2: names the device and gives a number in degrees", async ({ openApp }) => {
    const q = mic.question("en07");
    const app = await openApp(mic.clip("en07"));
    await app.startLive();
    const turn = await app.nextTurn();
    await app.stopLive();
    expect.soft(turn.lang).toBe("en");
    expect.soft(turn.tools).toEqual([q.expected_tool]);
    expect.soft(mentionsDevice(turn.answer, "pi-2"), turn.answer).toBe(true);
    expect(turn.answer, "a temperature reading").toMatch(/\d+(\.\d+)?\s*degrees/);
  });

  for (const id of ["hi05", "mr05"]) {
    const q = mic.question(id);
    test(`${id} [${q.lang}] status of pi 3: reply says it is offline, in ${q.lang}`, async ({ openApp }) => {
      const app = await openApp(mic.clip(id));
      await app.startLive();
      const turn = await app.nextTurn();
      await app.stopLive();
      expect.soft(turn.lang).toBe(q.lang);
      expect.soft(replyLanguage(turn.answer), turn.answer).toBe(q.lang);
      expect.soft(turn.tools).toEqual([q.expected_tool]);
      expect.soft(mentionsDevice(turn.answer, OFFLINE), turn.answer).toBe(true);
      // the fleet state the user hears must match the state the dashboard shows: pi 3 is OFFLINE
      expect(turn.answer, "says offline (ऑफ़लाइन / ऑफलाइन)").toMatch(/ऑफ़लाइन|ऑफलाइन/);
    });
  }
});

test("push-to-talk fallback (HTTP) en01: same answer path without WebRTC", async ({ openApp }) => {
  const file = mic.clip("en01");
  const app = await openApp(file);
  await app.holdToTalk(mic.holdSeconds(file));
  await expect(app.status).toHaveText(/thinking…|idle/);
  const turn = await app.nextTurn();
  await expect(app.status).toHaveText("idle");
  expect.soft(turn.lang).toBe("en");
  expect.soft(replyLanguage(turn.answer)).toBe("en");
  expect(mentionsDevice(turn.answer, OFFLINE), turn.answer).toBe(true);
});
