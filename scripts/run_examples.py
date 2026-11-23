"""Scripted end-to-end run over recorded audio files (no microphone), in-process.

  python -m scripts.run_examples [--backend claude_cli] [files...]
For each WAV: STT -> agent (LLM + tools) -> TTS. Writes examples/offline/<name>.json (transcript,
language, tool calls with results, answer, timings) and <name>.reply.wav.
The WebRTC version of the same run is scripts/webrtc_client.py (needs the app running).
"""
from __future__ import annotations

import argparse
import json
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

from agent.agent import FleetAgent, make_backend  # noqa: E402
from voice.engine import VoiceEngine  # noqa: E402
from voice.tts import pcm_to_wav, read_wav  # noqa: E402

DEFAULT = ["evals/audio/en01.wav", "evals/audio/en07.wav", "evals/audio/hi01.wav", "evals/audio/hi09.wav",
           "evals/audio/mr01.wav", "evals/audio/mr05.wav"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", default=DEFAULT)
    ap.add_argument("--backend", default=None)
    ap.add_argument("--out", default="examples/offline")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    engine = VoiceEngine(agent=FleetAgent(make_backend(a.backend)))
    for p in a.files:
        x, sr = read_wav(p)
        r, pcm, osr = engine.turn(x, sr)
        name = os.path.splitext(os.path.basename(p))[0]
        if pcm:
            with open(os.path.join(a.out, f"{name}.reply.wav"), "wb") as f:
                f.write(pcm_to_wav(pcm, osr))
        rec = {"input": p, "input_is_synthetic_speech": True, **r.to_dict(),
               "reply_audio": os.path.join(a.out, f"{name}.reply.wav") if pcm else None}
        with open(os.path.join(a.out, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        print(f"{name}: [{r.lang}] {r.transcript!r} -> {[t['tool'] for t in r.agent.get('tool_calls', [])]} -> {r.answer!r} "
              f"(v2v {r.timings_ms.get('v2v_first_audio_ms')} ms)")


if __name__ == "__main__":
    main()
