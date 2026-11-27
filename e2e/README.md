# End-to-end tests (Playwright)

Browser-level tests for the fleet voice agent: a synthetic speech clip is played into a real Chromium as the
microphone, the page talks to the real stack (Pipecat WebRTC → Whisper → offline rules router → Piper), and the
tests check what a user would see. A separate set drives Grafana through `make chaos`.

The suite needs **no Anthropic API key**: it runs against the offline rules router (`LLM_BACKEND=rules`), so
anyone can reproduce it. These tests were written with [Claude Code](https://claude.com/claude-code).

## How to run

```bash
make up                         # the whole stack; first start downloads ~780 MB of models
cd e2e && npm ci && npx playwright install --with-deps chromium
npx playwright test             # ~9-10 min, mostly waiting for a real 2-minute alert window
npx playwright show-report      # HTML report, with a trace for every test
```

On a host where you cannot install Chromium's system libraries (the build VPS), run it inside the official
Playwright image instead: `bash e2e/run-in-docker.sh` (same arguments as `npx playwright test`).

CI: [`.github/workflows/e2e.yml`](../.github/workflows/e2e.yml) brings the stack up with Docker Compose, runs the
suite, and uploads the HTML report always and the traces and screenshots when something fails.

## What is covered

| File | Tests | What it checks |
|---|---|---|
| `tests/01-voice.spec.ts` | 7 | Live WebRTC questions in **English, Hindi and Marathi** ("which devices are offline", a temperature, the status of pi 3), plus one push-to-talk (HTTP) turn |
| `tests/02-edge.spec.ts` | 8 | Silence (live and push-to-talk), a noisy clip (10 dB SNR), two questions no tool can answer (en, hi), the backend down before a live turn, before a push-to-talk turn, and in the middle of a live turn |
| `tests/03-observability.spec.ts` | 3 | `make chaos` on pi-4 → the DeviceSilent alert fires after the 120 s threshold and inside the rule's window; the dashboard shows pi-4 OFFLINE; the alerting UI lists DeviceSilent as Firing |

**How a voice turn is judged.** Speech-to-text varies, so no test compares sentences. Each turn must have a
transcript in the right script and language tag, a reply **in the same language** as the question (English has no
Devanagari; Hindi and Marathi are told apart by common function words, `fixtures/lang.ts`), the **key fact** (the
offline device is pi 3, a temperature reply names the device and a number in degrees), and a tool call that the
repo's eval set (`evals/questions.jsonl`) accepts for that question.

**A known fleet state.** Global setup freezes the simulator, forces pi-3 offline and waits (by polling
VictoriaMetrics, not sleeping) until it has been silent for more than 120 s while the other four report. Every
voice journey therefore has a fact known in advance. Teardown recovers the fleet and turns random flapping back on.

**Fleet control** uses exactly the commands behind `make freeze`, `make chaos` and `make recover`
(`docker compose exec -T fleet-sim python -m fleet_sim.chaos …`), so the tests exercise the same path a person would.

**Audio.** Chromium plays a 16-bit PCM WAV as the mic (`--use-file-for-fake-audio-capture`). The clips are the repo's
own synthetic Piper speech (`evals/audio/`) plus two out-of-scope questions made the same way
(`scripts/make_clips.py` → `audio/`, with a manifest). `scripts/prepare-audio.ts` adds 3 s of lead silence and 6 s of
tail: without the lead, the first words play before WebRTC connects ("Which devices are offline right now?" was
transcribed as "Questions are offline right now.").

**Determinism.** One worker, files in a fixed order (one voice pipeline, one simulated fleet). Waits are web-first
assertions or `expect.poll`. There are two deliberate fixed waits, each commented: holding the push-to-talk button
while the clip plays, and the 15 s window in which a silent live session must *not* produce a turn. Retries: 0
locally, 1 in CI.

## What is deliberately not covered, and why

- **The Claude (Anthropic API) backend.** The suite must run without a key. The rules router decides tools by
  keywords, so these tests check the voice pipeline and the UI, not LLM reasoning quality; the repo's eval
  (`make eval`, RESULTS.md) covers tool accuracy with the LLM.
- **Telegram voice notes from n8n.** They need a bot token; the alert path up to Grafana is covered here, and the
  repo's Podman CI job checks the n8n → `.ogg` path.
- **Real microphones, real voices, accents.** All speech is synthetic Piper TTS. Accuracy on human speech is not
  measured.
- **Browsers other than Chromium.** The fake-microphone flags are Chromium-specific.
- **Audio playback of the reply.** The tests see that a reply was produced (text and timings), not that it was
  audible; headless Chromium has no speakers.
- **Load and concurrency.** One user at a time, by design of the stack (1 CPU for the voice app).

## Known flaky or state-dependent tests

- `03-observability` › "the dashboard shows the device OFFLINE" and "the alerting UI lists DeviceSilent as Firing":
  **known flaky because of [DEF-001](DEFECTS.md#def-001)** (Grafana intermittently starved at its 320 MiB limit).
  They failed in run 1 and passed in runs 2 and 3. They are not marked `test.fail()`, because nothing measurable
  predicts when the defect hits; each run records Grafana's memory as a `grafana-memory` annotation instead.
- No voice or edge test needed a retry in the recorded runs.

## Defects found

See [DEFECTS.md](DEFECTS.md): 3 defects (1 High, 2 Medium). Tests that expose a deterministic defect are marked
`test.fail()` with the defect ID (DEF-002, DEF-003); the intermittent DEF-001 is tracked as a known flaky test
instead. The app was not changed to make any test pass.

### Patterns in the defects

- **Failure paths are where the bugs are.** All three defects sit on an unhappy path (resource limits, silence,
  a dead backend). The happy voice journeys passed in all three languages on every run.
- **The two input paths disagree.** Live (WebRTC) and push-to-talk (HTTP) handle the same situation differently:
  silence is ignored live but turned into an invented question by push-to-talk (DEF-002); a dead backend is reported
  by push-to-talk but hidden in live mode (DEF-003). A shared "no speech / no backend" policy would fix both.
- **"Nothing happened" is not reported as a state.** The UI has states for listening, thinking and error, but
  not for "heard nothing" or "could not connect" that survive the next status update.
- **Observability needs its own observability.** The alert evaluation kept working while the dashboard starved
  (DEF-001); a resource limit that is fine on a fresh start fails after half an hour, which a short smoke test
  would never catch.

## Results (measured on the build VPS)

2026-11-27, build VPS (2 vCPU / 8 GB shared), `bash e2e/run-in-docker.sh`, offline rules router, no API key.

| Run | Result | Suite time | DeviceSilent fired after `make chaos` | Notes |
|---|---|---|---|---|
| 1 | 16 failed | 5.6 min | 137 s | A harness bug (manual `tracing.start` clashed with Playwright's own tracing), fixed; the Grafana UI test exposed DEF-001 |
| 2 | 14 passed, 3 failed | 9.0 min | 132 s | Exposed DEF-002 and DEF-003; Grafana UI passed on a freshly recreated Grafana |
| 3 | 17 passed, 1 failed | 9.1 min | 132 s | The one failure was a `test.fail()` for DEF-001 that unexpectedly passed, which showed DEF-001 is intermittent |
| 4 (final, committed code) | **18 passed** (16 passing + 2 expected failures, DEF-002 and DEF-003) | **9.0 min** | **132 s** | |

- Global setup (fleet into a known state) took 135 s in every run: pi-3 has to cross the 120 s line.
- Each voice journey took 12–15 s end to end (browser launch, WebRTC connect, speech, Whisper on 1 CPU, reply).
- English, Hindi and Marathi journeys gave the right language and named pi 3 in runs 2, 3 and 4 (3 of 3).
- **GitHub Actions** (2026-11-27, [run 46023701490](https://github.com/malhar-sk/fleet-voice-agent/actions/runs/46023701490)):
  **18 passed in 8.5 min** (the whole job took 11 min, including bringing the stack up). The observability tests
  passed, so the 2-minute alert check stayed inside its window on a GitHub runner too; the exact firing time there
  was not recorded.
