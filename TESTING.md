# TESTING

Copy-paste steps for a **Windows laptop with Docker Desktop, Git and Python**. Commands are for **PowerShell**.
Each step says what you should see. Linux/macOS users can run the same `docker compose` commands, or use the
`make` targets shown at the end.

Default ports (high on purpose, because the build server is shared; you can change them in `.env`):

| What | URL |
|---|---|
| Grafana | http://localhost:13000 (admin / admin) |
| Voice app | http://localhost:17860 |
| n8n | http://localhost:15678 |
| VictoriaMetrics | http://localhost:18428 |

To use the URLs from the project brief (`localhost:3000` and `localhost:7860`), set `GRAFANA_PORT=3000` and
`APP_PORT=7860` in `.env` before step 2.

---

### 0. Get the code

```powershell
git clone https://github.com/malhar-sk/fleet-voice-agent.git
cd fleet-voice-agent
copy .env.example .env
```
You should see a `fleet-voice-agent` folder with `docker-compose.yml`, `README.md` and a new `.env`. The repo is private,
so Git may ask you to sign in to GitHub.

Optional: open `.env` and fill in `ANTHROPIC_API_KEY` (answers then come from Claude with native tool use). Without it, the
app uses the offline keyword router, which works but gives template answers and is weaker in Hindi and Marathi
(see RESULTS.md). `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are optional too.

### 1. Start everything, then see 5 devices in Grafana

```powershell
docker compose up -d --build
docker compose ps
```
The first run builds the app image (about 5–10 min), then the `voice-app` container downloads about 780 MB of speech
models into `.\models` (Whisper small + 5 Piper voices). Follow it with `docker compose logs -f voice-app` until you see
`models ready` and `voice engine ready` (Ctrl+C to stop following). `docker compose ps` should list
`victoriametrics`, `grafana`, `fleet-sim`, `n8n` and `voice-app` as Up, with voice-app **(healthy)**. If the download
took longer than the healthcheck allows, voice-app may show "unhealthy" even though it works. Check with
`curl.exe http://localhost:17860/health`, which should return `{"status":"ok",...}`.

Open **http://localhost:13000**, log in with `admin` / `admin` (you can skip the password change). The home dashboard is
**"Device Fleet (simulated) + Payment SLA"**. You should see:
- the table "Fleet: status per device" with **pi-1 … pi-5**, each **ONLINE** in green, with CPU temperature, memory and uptime
- "Devices online" = **5** (the simulator randomly drops a device for 1–5 min now and then, so you may occasionally see 4)
- payment panels: SLA breaches (last 5 min), queue depth, and sent/acked/breaches per minute

### 2. Talk to it: English, then Hindi

Open **http://localhost:17860** in **Chrome** and click **🎙️ Talk (live, WebRTC)**. Allow the microphone when Chrome asks.
The status should change to "live: speak any time". Then say:

- "**Which devices are offline?**"
- then in Hindi: "**अभी कौन से डिवाइस ऑफ़लाइन हैं?**" (*abhi kaun se device offline hain?*)

You should see a card for each question with what it heard, `[en]` or `[hi]`, the answer, the tool used
(`list_offline_devices`) and the timings. You should also hear the answer in the same language, about 5–10 s after you
stop speaking (CPU-only speech recognition is the slow part). Marathi works too: "सध्या कोणती उपकरणे ऑफलाइन आहेत?".

**If live mode connects but you hear nothing within about 20 s:** WebRTC audio sometimes can't get from a container
through Docker Desktop's network. Click **⏹ Stop**, then **press and hold "Hold to talk (fallback)"** while you speak and
release when you finish. That sends the clip over plain HTTP to the same pipeline, and the answer plays from the page.
(Both modes were tested in headless Chromium on the Linux build host, see `examples/browser/`. They were not tested on
Windows.)

If you use the app over an SSH tunnel to a remote server instead of locally, forward the port
(`ssh -L 17860:localhost:17860 user@server`) and use **Hold to talk**, because WebRTC media doesn't pass through SSH tunnels.

### 3. Chaos: knock pi-2 offline and get the voice alert

```powershell
docker compose exec fleet-sim python -m fleet_sim.chaos offline pi-2 --minutes 10
```
You should see `pi-2 forced OFFLINE for 10 min`. **Wait about 2½ minutes**: the rule fires after 120 s of silence and is
checked every 10 s. Then:

```powershell
dir alerts_out
Get-Content alerts_out\alerts.log -Tail 1
```
You should see a new file like `2026-…_pi-2.ogg`, and a log line whose `text` is
`Alert: pi 2 has been offline for 2 minutes.` plus `"delivered":"file"`. Drag the `.ogg` into a Chrome tab (or open it
in VLC) to hear it. In Grafana, the table shows pi-2 **OFFLINE** in red, and *Alerting → Alert rules* shows
`DeviceSilent` firing for pi-2. On the build host this took 138 s from chaos to the saved `.ogg`.

**Telegram instead of a file:** put your bot token and chat id in `.env` (`TELEGRAM_BOT_TOKEN=…`,
`TELEGRAM_CHAT_ID=…`; message your bot once, then read the chat id from
`https://api.telegram.org/bot<TOKEN>/getUpdates`). Then run `docker compose up -d n8n` and repeat the chaos command with
`pi-4`. The voice note should arrive in Telegram. This path was **not** tested because the build host had no token.
Set `ALERT_LANG=hi` or `mr` in `.env` to get alerts in Hindi or Marathi.

To see the workflow, open http://localhost:15678. n8n asks you to create a local owner account the first time. The
workflow "Fleet voice alert" and its executions are listed there.

Bring the device back:
```powershell
docker compose exec fleet-sim python -m fleet_sim.chaos recover all
```

### 4. Eval: the latency and accuracy table

Run it inside the app container (nothing to install on Windows):
```powershell
docker compose exec voice-app python -m evals.make_audio
docker compose exec voice-app python -m evals.run_eval
docker compose exec voice-app python -m evals.report
```
- `make_audio` should print `eval audio already present …`. The 45 synthetic clips (30 questions, 5 noisy variants,
  10 dev clips) are committed, because Piper isn't deterministic and these are the exact clips behind RESULTS.md.
  `--force` regenerates them.
- `run_eval` first sets the scenario: random flapping off, pi-3 forced offline, 3 SLA breaches. It **waits about 2½ min**
  until pi-3 counts as OFFLINE, then prints one line per question, like
  `[1/35] en01 lang en✓ tool ✓ fact ✓ wer 0.0 v2v … | 'Which devices are offline right now?' -> '…'`.
  Expect about 5–10 min in total. With an API key it uses Claude (`voice_anthropic`); without one, the rules router
  (`voice_rules`).
- `report` prints markdown tables per language: WER, CER, language-ID accuracy, tool-choice accuracy, answer
  correctness, voice-to-voice p50/p95 and per-stage timings. The committed results from the build host (Claude via CLI)
  are in `evals/results/voice_claude_cli.jsonl` and are summarised in `RESULTS.md`.

### 5. Unit tests (no Docker, no models)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements-ci.txt
.venv\Scripts\python -m pytest -q tests -m "not live and not models"
```
You should see `66 passed, 5 deselected`. If Node.js isn't installed, the 3 n8n Code-node tests are skipped instead.

Live tests (they start VictoriaMetrics + fleet-sim and force pi-4 offline, about 1–2 min):
```powershell
.venv\Scripts\python -m pytest -q tests -m live
```
You should see `4 passed`.

### 6. Stop

```powershell
docker compose down          # stop, keep data
docker compose down -v       # stop and delete metrics/Grafana/n8n volumes
```

---

## Linux / macOS / WSL shortcuts

```bash
make up                         # docker compose up -d --build
make chaos DEVICE=pi-2          # force a device offline (MINUTES=10 by default)
make recover DEVICE=all
make test                       # unit tests (needs .venv: python3.11 -m venv .venv && .venv/bin/pip install -r requirements-ci.txt)
make test-live
# eval on the host (full deps + models):
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python scripts/download_models.py
make eval-audio && make eval    # LLM backend: auto = API key, else `claude` CLI if logged in, else rules
make examples                   # scripted end-to-end run over 6 clips -> examples/offline/
```

Scripted checks that need no microphone (the app must be running on port 17860):
```bash
.venv/bin/python -m scripts.webrtc_client evals/audio/en01.wav evals/audio/hi01.wav    # real WebRTC session
.venv/bin/python -m scripts.alert_timeline --device pi-2                               # chaos -> voice-note timeline
```
