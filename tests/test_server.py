"""FastAPI endpoints with the offline rules backend + fake VictoriaMetrics (no speech models)."""
import os

import pytest
from fastapi.testclient import TestClient

os.environ["PRELOAD"] = "0"
os.environ["LLM_BACKEND"] = "rules"

from voice import server  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAVE_MODELS = os.path.exists(os.path.join(ROOT, "models", "piper", "en_US-lessac-medium.onnx"))


@pytest.fixture
def client(fake_vm):
    with TestClient(server.app) as c:
        yield c


def test_health_and_index(client):
    assert client.get("/health").json()["status"] == "ok"
    r = client.get("/")
    assert r.status_code == 200 and "Talk" in r.text


def test_ask_text(client):
    r = client.post("/api/ask", json={"question": "which devices are offline?"}).json()
    assert r["tool_calls"][0]["tool"] == "list_offline_devices" and "pi 3" in r["answer"]


def test_tts_rejects_empty(client):
    assert client.post("/tts", json={"text": "  "}).status_code == 400


@pytest.mark.models
@pytest.mark.skipif(not HAVE_MODELS, reason="Piper voices not downloaded")
def test_tts_ogg(client):
    os.environ["TTS_ONLY"] = "1"
    try:
        r = client.post("/tts", json={"text": "pi 3 मिनट से ऑफ़लाइन है।", "lang": "hi"})
    finally:
        os.environ.pop("TTS_ONLY")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/ogg" and r.content[:4] == b"OggS"
