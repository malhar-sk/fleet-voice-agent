# RESULTS

This file lists only numbers that were actually measured. For each one it gives the command, the date and
the dataset size. All runs were on 2026-11-23 (UTC), on the build host: a shared 2 vCPU / 8 GB VPS, CPU only,
with faster-whisper on **1 thread** (`OMP_NUM_THREADS=1`, `STT_THREADS=1`) because other services share the box.
Raw per-question records are in `evals/results/*.jsonl`. The tables below are generated into `evals/results/report.md`
by `python -m evals.report`.

> **All eval audio is synthetic speech.** It was generated with Piper TTS (`python -m evals.make_audio`): English
> `en_US-amy`, Hindi `hi_IN-rohan`, Marathi `mr_IN-google` speaker 4. These differ from the reply voices. Real
> human speech, especially accented or code-mixed speech, will score worse than this. All fleet data is synthetic
> too (`fleet-sim`).

## Headline numbers

| Metric | Value | Dataset | Command |
|---|---|---|---|
| **p50 voice-to-voice latency** (end of user audio → first reply audio chunk ready, in-process) | **8.02 s** (p95 9.72 s) | 30 clean questions | `python -m evals.run_eval --backend claude_cli` |
| p50 voice-to-voice over **WebRTC**, measured at the client (includes the 0.6 s VAD end-of-speech wait and the transport) | **8.78 s** (p95 10.48 s) | 9 clips (3 per language) | `python -m scripts.webrtc_client --out evals/results/webrtc evals/audio/{en01,en05,en09,hi01,hi05,hi09,mr01,mr05,mr09}.wav` |
| **Tool-choice accuracy** (voice → Whisper → Claude) | **96.7 %** (29/30) | 30 clean questions | same as row 1 |
| **Hindi speech-to-text WER** | **0.338** (CER 0.117) | 10 Hindi clips | same as row 1 |

LLM: `claude-haiku-5-5`. The build host has no `ANTHROPIC_API_KEY`, so every LLM number comes from the
logged-in `claude -p` CLI (backend `claude_cli`), which uses 2 calls per turn (plan the tool calls, then answer).

## Voice run: per language (Claude via CLI)

Run 03:39–03:43 UTC. Scenario set by the eval itself: random flapping off, pi-3 forced offline (past the 120 s
limit), 3 SLA breaches injected. File: `evals/results/voice_claude_cli.jsonl`.

| Group | n | WER | CER | Lang ID | Tool choice | Tool + args | Answer correct | V2V p50 | V2V p95 | STT p50 | LLM p50 | TTS first p50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| English | 10 | 0.000 | 0.000 | 100% | 100% | 100% | 100% | 8.12 s | 9.37 s | 3.65 s | 4.24 s | 0.27 s |
| Hindi | 10 | 0.338 | 0.117 | 100% | 100% | 100% | 100% | 7.46 s | 9.36 s | 4.07 s | 3.19 s | 0.17 s |
| Marathi | 10 | 0.603 | 0.236 | 80% | 90% | 90% | 90% | 8.19 s | 9.45 s | 4.24 s | 3.70 s | 0.23 s |
| **All clean (30)** | 30 | 0.282 | 0.109 | 93% | 97% | 97% | 97% | 8.02 s | 9.72 s | 4.00 s | 3.56 s | 0.23 s |
| Noisy variants (5) | 5 | 0.367 | 0.129 | 100% | 100% | 100% | 100% | 7.42 s | 8.44 s | 4.00 s | 3.39 s | 0.20 s |
| All (35) | 35 | 0.292 | 0.111 | 94% | 97% | 97% | 97% | 7.98 s | 9.66 s | 4.00 s | 3.45 s | 0.23 s |

How each column is measured:
- **WER/CER**: corpus-level, computed with `jiwer` after the same normalisation on both sides: lowercase, strip punctuation
  and nukta, Devanagari digits and number words → digits, "पाई 3 / Pi-3 / pi three" → "pi 3". See `evals/metrics.py`.
- **Lang ID**: the language the reply was spoken in matches the question's language.
- **Tool choice**: the agent called an acceptable tool for the question (`acceptable_tools` in `evals/questions.jsonl`).
  **Tool + args** also requires the right device, and the right metric for `query_metric`.
- **Answer correct**: the key fact is in the spoken answer. The ground truth comes from calling the *expected* tool right
  after the answer, so the agent's own (possibly wrong) call can't make itself look right. Kinds of fact: offline device
  named, online count, ONLINE/OFFLINE word, metric value within ±1.5 °C / ±3 %, breach count ±1.
- **Re-scoring disclosure**: after the run I fixed the key-fact checker to accept "पि 3", a Devanagari spelling of "pi 3"
  that Claude used. That changed 2 verdicts (mr01, hi01_noisy). The run-time score was 32/35, and 34/35 after
  re-scoring. The answers themselves were not regenerated. A mixed-script "पi 3" is still scored as wrong.
- **V2V (in-process)**: from the moment the full question audio is handed to the engine until the first TTS sentence is
  synthesised. It does *not* include VAD's end-of-speech wait. The WebRTC row above does.

The misses (all Marathi): mr06 and mr10 were heard as Hindi, so the answer was correct but in Hindi. On mr08, Whisper
garbled the device name ("पाई पाई प्ष्ची"), so Claude asked which device was meant and called no tool.

### Where the time goes (p50, clean 30)

| Stage | p50 | Notes |
|---|---|---|
| STT (faster-whisper small int8, 1 thread) | 4.00 s | Dominated by one encoder pass over Whisper's fixed 30 s window. Language detection reuses that pass. Without the reuse, the transcription step alone took about 3 s more (M3 smoke tests on the same English sentence, "Which devices are offline right now?": `stt_transcribe_ms` 3569 ms before vs 490 ms after; n=1 each, indicative only). |
| LLM (2 × `claude -p`) | 3.56 s | The CLI's own reported API time p50 is 2.75 s, so about 0.8 s per turn is CLI process start-up. |
| Tools (VictoriaMetrics queries) | ~0.03 s | |
| TTS first sentence (Piper) | 0.23 s | Answers are spoken one sentence at a time. |

## Text-only (oracle transcripts): is the LLM or the STT losing points?

The exact script text goes straight to the agent, with no audio involved. Run 03:44–03:46 UTC, with the same scenario
still active. Command: `python -m evals.run_eval --backend claude_cli --mode text --no-scenario`.

| Group | n | Tool choice | Tool + args | Answer correct | LLM p50 | LLM p95 |
|---|---|---|---|---|---|---|
| English | 10 | 100% | 100% | 100% | 3.19 s | 4.48 s |
| Hindi | 10 | 100% | 100% | 100% | 3.35 s | 4.75 s |
| Marathi | 10 | 100% | 100% | 90% | 4.11 s | 4.69 s |
| **All clean (30)** | 30 | 100% | 100% | 97% | 3.46 s | 4.75 s |

On clean text, Claude picks the right tool every time. The one miss is mr02, where it wrote the device as "पi 3"
(mixed script). So the voice-run misses come from speech recognition.

## Baseline: offline rules router (no LLM), on the same Whisper transcripts

This is the fallback the Docker app uses when there is no API key.
Command: `python -m evals.run_eval --backend rules --mode transcripts --from evals/results/voice_claude_cli.jsonl --no-scenario`.

| Group | n | Tool choice | Tool + args | Answer correct |
|---|---|---|---|---|
| English | 10 | 100% | 100% | 100% |
| Hindi | 10 | 70% | 70% | 70% |
| Marathi | 10 | 60% | 60% | 50% |
| **All clean (30)** | 30 | 77% | 77% | 73% |

After seeing this table, I added fuzzy keyword matching to the router (Whisper writes "ऑफ़लाइन" as "अफलाइ" or
"अप्लाइ"). Re-run on the **same** transcripts (`--tag transcripts_rules_fuzzy`), it gets 90 % tool choice and 90 %
answers correct. That number is **optimistic**, because the change was made after looking at this eval set.

## Docker default config (no API key): voice run with the rules router, inside the container

This is what the app does out of the box without `ANTHROPIC_API_KEY`: the rules router with fuzzy matching, run inside
the `voice-app` image (`cpus: 1.0`, 1 STT thread). Run 04:14–04:20 UTC. Command:
`docker compose stop voice-app && docker compose run --rm voice-app python -m evals.run_eval` (backend auto → rules).
File: `evals/results/voice_rules.jsonl`. The Whisper transcripts were identical to the host run (same WER).

| Group | n | Lang ID | Tool choice | Answer correct | V2V p50 | V2V p95 | STT p50 | TTS first p50 |
|---|---|---|---|---|---|---|---|---|
| English | 10 | 100% | 100% | 100% | 4.54 s | 5.49 s | 4.09 s | 0.48 s |
| Hindi | 10 | 100% | 90% | 90% | 5.23 s | 6.55 s | 4.86 s | 0.53 s |
| Marathi | 10 | 80% | 80% | 80% | 5.17 s | 6.32 s | 4.58 s | 0.59 s |
| **All clean (30)** | 30 | 93% | 90% | 90% | 5.11 s | 6.55 s | 4.47 s | 0.54 s |
| Noisy variants (5) | 5 | 100% | 100% | 100% | 4.84 s | 5.34 s | 4.17 s | 0.66 s |

This is faster, because there are no LLM calls, but the accuracy is **optimistic**: the fuzzy matching was added after
looking at this eval set's transcripts (see the previous section; before it, the rules router got 77 %).

## Voice-to-voice over WebRTC (client-measured)

`scripts/webrtc_client.py` is an aiortc client that does what the browser does. It sends a WAV in real time over
WebRTC to the Pipecat `SmallWebRTCTransport` pipeline, records the reply track, and measures from the last speech
sample it sent to the first non-silent reply frame it received. Server on the build host with `LLM_BACKEND=claude_cli`,
run 03:49 UTC. Files: `evals/results/webrtc/*.json` plus the reply WAVs.

| Path | n | V2V p50 | V2V p95 | Server-side p50 (from VAD stop) |
|---|---|---|---|---|
| WebRTC client → Pipecat SmallWebRTC | 9 | 8.78 s | 10.48 s | 8.32 s |

## Real browser check (headless Chromium)

`scripts/browser_check.py` ran in the official Playwright image. It loaded `web/index.html` from the Dockerised app
and used Chrome's fake microphone (`evals/audio/hi01.wav`). Both modes produced an answered turn: **live WebRTC**
(first turn 12.0 s after clicking Talk) and **Hold to talk** (HTTP). The app container had no API key, so this used
the rules router. This was a functional check, not a latency benchmark. Output: `examples/browser/`.

## M1: chaos makes a device go OFFLINE in Grafana

`make chaos DEVICE=pi-3` ran at 02:43:20Z. Grafana's `DeviceSilent` alert for pi-3 became **Alerting at 02:45:30Z**
(130 s; the threshold is 120 s, evaluated every 10 s). The query through Grafana's datasource proxy showed pi-3 OFFLINE
(last seen 186.7 s ago) and the other 4 ONLINE. Record: `examples/m1_grafana_status.json`
(command: `python3 scripts/verify_m1.py`). Screenshot from a later run (pi-3 offline during the eval):
`examples/grafana_dashboard.png`.

## M4: `make chaos` → voice alert timeline

Command: `python -m scripts.alert_timeline --device pi-2` (03:31:37Z start). Record: `examples/m4_alert_timeline.json`.

| t (s) | Event |
|---|---|
| 0.0 | `make chaos DEVICE=pi-2` (device goes silent) |
| 127.1 | pi-2 OFFLINE in VictoriaMetrics (silent 121 s > 120 s) |
| 133.2 | Grafana `DeviceSilent` alert = Alerting |
| 137.5 | n8n webhook received Grafana's notification |
| **138.1** | Voice note saved: `alerts_out/…_pi-2.ogg` (Opus, 48 kHz, 2.9 s) |

Transcribing the voice note back with Whisper gives "Alert, pi 2 has been offline for two minutes."
Sample: `examples/alerts/pi-2_offline_alert.ogg`.
The SLA rule takes the same path. With 3 breaches injected by the eval scenario, `PaymentSLABreaches` fired and n8n
saved "Alert: 3 payment SLA breaches in the last 5 minutes." (`examples/alerts/sla_breaches_alert.ogg`, 04:04:15Z).
**Telegram delivery: NOT MEASURED.** `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are empty on the build host, so the
workflow took its "not configured" branch, saved the `.ogg` and logged it to `alerts_out/alerts.log`. The Telegram
branch (`sendVoice`, multipart) is built but has never run.

## Marathi speech output

Marathi answers were spoken **in Marathi** with the offline Piper voice `mr_IN-google-medium` (CC BY-SA 4.0 data). No
Hindi fallback was needed. When Whisper mis-detects Marathi as Hindi (2 of 10 clips), the answer comes back in Hindi.

## STT language policy (tuned on a separate dev set, not the eval set)

`python -m evals.tune_stt` uses 10 dev clips (`evals/dev_questions.jsonl`), and the output is in
`evals/results/dev_tuning.txt`. Whisper-small almost never prefers Marathi for Marathi speech. Plain argmax over en/hi/mr
got 5/8 hi+mr clips into the right language. Decoding every hi/mr clip with the Marathi token, adding a domain prompt and
letting a word-list check pick hi or mr got **8/8**, with dev CER 0.214 (was 0.312). That policy is the default
(`STT_MR_RATIO=0`, `STT_EN_MIN=0.5`, `STT_PROMPT=1`).

## Tests

| Suite | Result | Command |
|---|---|---|
| Unit (fake VictoriaMetrics HTTP server, mocked LLM, n8n Code node run in Node) | 66 passed, 5 deselected | `make test` |
| Live (starts VictoriaMetrics + fleet-sim with Docker; chaos → offline → recover) | 4 passed | `make test-live` |
| Needs models (`-m models`, Piper `/tts` returns Ogg/Opus) | 1 passed | `.venv/bin/python -m pytest -m models` |

## NOT MEASURED (and why)

- **Real human speech.** All audio is synthetic, and there was no microphone on the build host.
- **Anthropic API backend latency.** There is no API key on the host. The CLI-reported API time (p50 2.75 s per turn for
  2 calls) is a hint at what the native tool-use backend would cost, not a measurement of it.
- **Telegram voice notes.** No bot token (see M4).
- **The Windows / Docker Desktop browser path.** There was no Windows machine. WebRTC from a browser into a container
  behind Docker Desktop's NAT may not connect; "Hold to talk" (HTTP) is the fallback.
- **Faster STT settings** (more threads, `base` model, GPU). Kept at 1 thread on purpose on this shared server.
- **Barge-in or interruption handling.** It isn't implemented (half-duplex turns).
