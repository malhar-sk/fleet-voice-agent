# Defects found by the e2e suite

Each entry was reproduced on the build VPS (2 vCPU / 8 GB, shared; stack from `docker-compose.yml` at the
commit under test, offline rules router, no API key). Tests that expose a defect are marked `test.fail()` with the
defect ID, so the suite stays green while the bug is open and turns red the day it is fixed (an "unexpected pass"),
which is the signal to remove the marker. **No application code was changed to make a test pass.**

Severity scale: **High** = a core user journey is broken or misleading; **Medium** = a journey works but the
user is left without feedback or with wrong information in an edge case; **Low** = cosmetic or a workaround is obvious.

| ID | Title | Severity | Test |
|---|---|---|---|
| [DEF-001](#def-001) | Grafana dashboard and alert UI intermittently never load: the 320 MiB memory limit starves Grafana 13.3 | High | `03-observability` › dashboard / alerting UI (known flaky, not `test.fail`: intermittent) |
| [DEF-002](#def-002) | Push-to-talk turns silence into a made-up Marathi question (with a broken character) and answers it | Medium | `02-edge` › push-to-talk with a silent mic |
| [DEF-003](#def-003) | Live mode with the backend down shows no error: the message is overwritten by "idle" immediately | Medium | `02-edge` › live mode when the backend is down |

---

## DEF-001

**Grafana dashboard and alert UI intermittently never load: the 320 MiB memory limit starves Grafana 13.3**

- **Severity:** High. The dashboard is the main way a person sees the fleet; with the shipped config every panel
  stays empty. Alerting itself still works (the DeviceSilent rule fired 137 s after `make chaos`, inside its window).
- **Component:** `docker-compose.yml` → `grafana.mem_limit: 320m` with image `grafana/grafana:13.3.0`.

**Steps to reproduce**
1. `make up` (or `docker compose up -d`) with the repo's `docker-compose.yml`.
2. Log in to Grafana at http://127.0.0.1:13000 (admin / admin, skip the password change).
3. Open the "Device Fleet (simulated) + Payment SLA" dashboard.

**Expected:** the nine panels show data within a few seconds (the per-device table lists pi-1 … pi-5 as ONLINE/OFFLINE).

**Actual:** every panel stays empty with a loading bar; the toolbar keeps showing "Cancel" (queries in flight).
After 60 s the "Fleet: status per device" region still contains only its heading. The alert list page can take
more than 30 s to fire its load event.

**Evidence**
- `docker stats`: grafana at **315.3 MiB / 320 MiB**, ~53 % CPU while idle on the dashboard.
- cgroup `memory.events` inside the container: **`max 435178`** (the limit was hit 435k times; `oom_kill 0`, so it is
  throttled, not killed).
- One dashboard query through `POST /api/ds/query` took **20.2 s**; Grafana's log shows `/api/ds/query` and
  `/api/annotations` taking 9.7–13.8 s and returning 401 with `Failed to run post auth hook … permissions.sync.forbidden`
  for the logged-in browser session. The dashboard refreshes every 10 s, so its 9 queries never complete.
- **Control experiment** (runtime only, no repo change): `docker update --memory 768m fleet-voice-agent-grafana-1`
  → the same dashboard rendered fully in **4.5 s**, and Grafana settled at **321.7 MiB**, i.e. just above the
  shipped limit. The container was then recreated with the shipped 320 MiB.
- Screenshots: [`evidence/DEF-001-dashboard-320MiB.png`](evidence/DEF-001-dashboard-320MiB.png) (empty panels) and
  [`evidence/DEF-001-dashboard-768MiB.png`](evidence/DEF-001-dashboard-768MiB.png) (control); traces from the
  failing tests are in the Playwright report of each run (`test-results/03-observability-*/trace.zip`).

**Notes for whoever fixes it:** raising `mem_limit` (the control used 768 MiB; Grafana used ~322 MiB unconstrained)
fixes the symptom. The compose header's memory budget (≈ 2.85 GB) would need updating too.

**Intermittent.** Seen in run 1 and in four consecutive probes over ~30 min (Grafana at 315 MiB, 20 s queries, 401s);
not seen in runs 2 and 3, including one test that ran while Grafana was at ≥ 95 % of its limit. No measurable
precondition predicted it, so the two Grafana UI tests are **not** marked `test.fail()` (they would "unexpectedly
pass" at random). They assert the correct behaviour, are listed as known flaky in [README.md](README.md#known-flaky-or-state-dependent-tests),
and record Grafana's cgroup memory as a `grafana-memory` annotation on every run, so a failure can be matched to
this entry from the report.

---

## DEF-002

**Push-to-talk turns silence into a made-up Marathi question (with a broken character) and answers it**

- **Severity:** Medium. The user said nothing, yet the log shows a question they never asked, in a language they
  did not use, and a spoken answer. For an assistant that is trusted to report fleet state, inventing input is the
  wrong failure mode; the live (WebRTC) path does not do this, because its VAD never starts a turn on silence.
- **Component:** `POST /api/turn` (push-to-talk path): Whisper small transcribes a clip with no speech, and nothing
  checks for "no speech" before language detection and the agent run.

**Steps to reproduce**
1. Open http://127.0.0.1:17860 with a microphone that records silence (the test uses Chromium's fake mic with
   `e2e/.cache/audio/silence.wav`, 16-bit zeros).
2. Hold **Hold to talk** for 3 s and release.
3. Or, without a browser: `curl -F "audio=@silence.wav" http://127.0.0.1:17860/api/turn` with 3 s of zeros.

**Expected:** a visible "nothing heard" / "no speech detected" message, no agent call, no spoken reply. The page
already has an `(nothing heard)` placeholder for an empty transcript.

**Actual:** transcript `"अपने \ufffd"` (Hindi "your" plus the Unicode replacement character), language tagged
**mr**, no tool call, and the Marathi "I can only answer questions about the fleet…" reply is spoken. Same result
**3 out of 3** times through the API (2026-11-27). The `\ufffd` comes from the server's transcript, not the page,
which suggests a multi-byte Devanagari character is being cut in half when tokens are decoded.

**Evidence:** [`evidence/DEF-002-ptt-silence.png`](evidence/DEF-002-ptt-silence.png); trace in the run's
`test-results/02-edge-silence-push-to-ta-*/trace.zip`; API output above.

---

## DEF-003

**Live mode with the backend down shows no error: the message is overwritten by "idle" immediately**

- **Severity:** Medium. Pressing **Talk** while the server is unreachable looks like nothing happened (the status
  flashes "connecting…" and returns to "idle"), so the user cannot tell a dead backend from a click that missed.
  Push-to-talk in the same situation does show an error, so the two paths behave differently.
- **Component:** `web/index.html`, the Talk button handler:
  `try { await startLive(); } catch (e) { setStatus("error: " + e.message); stopLive(); }`, and `stopLive()` ends
  with `setStatus("idle")`, so the error text is replaced in the same tick.

**Steps to reproduce**
1. Open http://127.0.0.1:17860, then stop the backend: `docker compose stop voice-app`.
2. Click **🎙️ Talk (live, WebRTC)**.

**Expected:** a visible error such as "error: Failed to fetch" (or "backend unreachable"), and the Talk button back
in its normal state.

**Actual:** the status shows "connecting…" for about 1 s and then "idle"; no error is ever visible. The Playwright
call log records the status as `connecting…` ×3 then `idle` ×41 over 20 s.

**Evidence:** [`evidence/DEF-003-live-backend-down.png`](evidence/DEF-003-live-backend-down.png); trace in the
run's `test-results/02-edge-backend-down-live-*/trace.zip`.
