"""The n8n workflow: structure, and the sentence-building Code node run under Node.js with a fake Grafana payload."""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF = json.load(open(os.path.join(ROOT, "n8n", "workflows", "voice_alert.json"), encoding="utf-8"))
NODES = {n["name"]: n for n in WF["nodes"]}


def test_graph_is_wired():
    c = WF["connections"]
    assert c["Grafana webhook"]["main"][0][0]["node"] == "Build sentence"
    assert c["Build sentence"]["main"][0][0]["node"] == "TTS (voice app /tts)"
    yes, no = c["Telegram configured?"]["main"]
    assert yes[0]["node"] == "Telegram sendVoice" and no[0]["node"] == "Save .ogg to alerts_out"
    assert NODES["Grafana webhook"]["parameters"]["path"] == "voice-alert"
    assert "/tts" in NODES["TTS (voice app /tts)"]["parameters"]["url"]
    assert "sendVoice" in NODES["Telegram sendVoice"]["parameters"]["url"]


def test_grafana_contact_point_points_at_n8n():
    cp = open(os.path.join(ROOT, "grafana/provisioning/alerting/contact_points.yml")).read()
    assert "http://n8n:5678/webhook/voice-alert" in cp


def _run_build(payload, lang="en"):
    code = NODES["Build sentence"]["parameters"]["jsCode"]
    harness = f"""
const $input = {{ first: () => ({{ json: {{ body: {json.dumps(payload)} }} }}) }};
const $env = {{ ALERT_LANG: {json.dumps(lang)} }};
const result = (function() {{ {code} }})();
console.log(JSON.stringify(result));
"""
    out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, check=True)
    return [r["json"] for r in json.loads(out.stdout)]


PAYLOAD = {"status": "firing", "alerts": [
    {"status": "firing", "labels": {"alertname": "DeviceSilent", "device_id": "pi-3", "kind": "device_silent"},
     "values": {"B": 245, "C": 1}, "startsAt": "2026-11-23T03:00:00Z"},
    {"status": "resolved", "labels": {"alertname": "DeviceSilent", "device_id": "pi-1"}, "values": {"B": 3}},
    {"status": "firing", "labels": {"alertname": "PaymentSLABreaches", "kind": "sla_breach"}, "values": {"B": 3}},
]}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("lang,needle", [("en", "pi 3 has been offline for 4 minutes"), ("hi", "4 मिनट से ऑफ़लाइन"),
                                         ("mr", "4 मिनिटांपासून ऑफलाइन")])
def test_build_sentence(lang, needle):
    items = _run_build(PAYLOAD, lang)
    assert len(items) == 2                       # resolved alerts are skipped
    assert needle in items[0]["text"] and items[0]["lang"] == lang
    assert items[0]["filename"].endswith("_pi-3.ogg")
    assert "3" in items[1]["text"] and items[1]["alertname"] == "PaymentSLABreaches"
