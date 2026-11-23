"""M4 check: `make chaos` -> Grafana alert -> n8n -> voice note, with a timeline.

  python -m scripts.alert_timeline --device pi-2
Forces the device offline, then polls VictoriaMetrics (device age), Grafana (alert state) and
alerts_out/alerts.log (n8n's delivery log) until the voice note appears. Writes
examples/m4_alert_timeline.json and copies the .ogg to examples/alerts/.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime, timezone

from agent import fleet_tools as ft

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAFANA = os.environ.get("GRAFANA_URL", "http://127.0.0.1:13000")
AUTH = base64.b64encode(f"admin:{os.environ.get('GRAFANA_ADMIN_PASSWORD', 'admin')}".encode()).decode()


def iso(t=None):
    return datetime.fromtimestamp(t or time.time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def grafana_state(dev):
    req = urllib.request.Request(GRAFANA + "/api/prometheus/grafana/api/v1/alerts", headers={"Authorization": "Basic " + AUTH})
    with urllib.request.urlopen(req, timeout=5) as r:
        alerts = json.load(r)["data"]["alerts"]
    for a in alerts:
        if a["labels"].get("alertname") == "DeviceSilent" and a["labels"].get("device_id") == dev:
            return a["state"]
    return None


def log_lines():
    p = os.path.join(ROOT, "alerts_out", "alerts.log")
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="pi-2")
    ap.add_argument("--timeout", type=float, default=300)
    a = ap.parse_args()
    dev = a.device
    ft.set_client(ft.VMClient(os.environ.get("VM_URL", "http://127.0.0.1:18428")))
    before = len(log_lines())
    events = []
    t0 = time.time()
    out = subprocess.run(["make", "chaos", f"DEVICE={dev}", "MINUTES=6"], cwd=ROOT, capture_output=True, text=True)
    events.append({"t": iso(t0), "s": 0.0, "event": f"make chaos DEVICE={dev} (device forced silent)", "detail": out.stdout.strip().splitlines()[1:2]})
    seen_offline = seen_alert = None
    delivered = None
    while time.time() - t0 < a.timeout:
        now = time.time()
        st = ft.device_status(dev)
        if seen_offline is None and st["status"] == "OFFLINE":
            seen_offline = now
            events.append({"t": iso(now), "s": round(now - t0, 1), "event": f"{dev} OFFLINE in VictoriaMetrics (silent {st['last_seen_seconds_ago']} s > 120 s)"})
        gs = grafana_state(dev)
        if seen_alert is None and gs and gs.lower() == "alerting":
            seen_alert = now
            events.append({"t": iso(now), "s": round(now - t0, 1), "event": "Grafana DeviceSilent alert state = Alerting"})
        new = [l for l in log_lines()[before:] if l.get("device") == dev]
        if new:
            delivered = new[0]
            saved = datetime.fromisoformat(delivered["savedAt"].replace("Z", "+00:00")).timestamp()
            recv = datetime.fromisoformat(delivered["receivedAt"].replace("Z", "+00:00")).timestamp()
            events.append({"t": delivered["receivedAt"], "s": round(recv - t0, 1), "event": "n8n webhook received the Grafana notification"})
            events.append({"t": delivered["savedAt"], "s": round(saved - t0, 1),
                           "event": f"voice note saved: alerts_out/{delivered['filename']} (Telegram not configured)"})
            break
        time.sleep(2)
    rec = {"device": dev, "started": iso(t0), "events": sorted(events, key=lambda e: e["s"]), "delivered": delivered}
    if delivered:
        src = os.path.join(ROOT, "alerts_out", delivered["filename"])
        os.makedirs(os.path.join(ROOT, "examples", "alerts"), exist_ok=True)
        dst = os.path.join(ROOT, "examples", "alerts", f"{dev}_offline_alert.ogg")
        shutil.copy(src, dst)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate:format=duration",
                                "-of", "json", dst], capture_output=True, text=True)
        rec["ogg"] = {"path": os.path.relpath(dst, ROOT), "ffprobe": json.loads(probe.stdout or "{}")}
        try:
            from voice.stt import WhisperSTT
            from voice.tts import read_wav
            wav = dst[:-4] + ".wav"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", dst, "-ar", "16000", "-ac", "1", wav], check=True)
            x, sr = read_wav(wav)
            res = WhisperSTT().transcribe(x, sr)
            rec["ogg"]["whisper_transcript_of_voice_note"] = res.text
            os.remove(wav)
        except Exception as e:  # transcription is a bonus check
            rec["ogg"]["whisper_transcript_of_voice_note"] = f"(not checked: {e})"
        rec["total_seconds_chaos_to_voice_note"] = rec["events"][-1]["s"]
    with open(os.path.join(ROOT, "examples", "m4_alert_timeline.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    for e in rec["events"]:
        print(f"+{e['s']:6.1f}s  {e['t']}  {e['event']}")
    print("voice note:", rec.get("ogg"))
    return 0 if delivered else 1


if __name__ == "__main__":
    raise SystemExit(main())
