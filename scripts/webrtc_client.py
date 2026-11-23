"""Scripted WebRTC client: plays WAV files into the live Pipecat pipeline, records the spoken reply.

No human microphone needed. For each file it opens a WebRTC connection to the app (like the browser
does), streams the audio in real time followed by silence, records the reply audio track and the
data-channel messages, and measures voice-to-voice latency AT THE CLIENT:
  end of user audio (last speech sample sent) -> first non-silent reply audio frame received.

  python -m scripts.webrtc_client --url http://127.0.0.1:17860 evals/audio/en01.wav evals/audio/hi01.wav
Outputs go to examples/webrtc/<name>.{reply.wav,json}.
"""
from __future__ import annotations

import argparse
import asyncio
import fractions
import json
import os
import time
import wave

import httpx
import numpy as np
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from av import AudioFrame

from voice.stt import resample
from voice.tts import read_wav

SR = 48000
FRAME = 960  # 20 ms


class FileTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, samples: np.ndarray, lead_silence_s=1.0, tail_silence_s=12.0):
        super().__init__()
        lead = np.zeros(int(lead_silence_s * SR), dtype=np.int16)
        tail = np.zeros(int(tail_silence_s * SR), dtype=np.int16)
        self.speech_start = len(lead)
        self.speech_end = len(lead) + len(samples)
        self.data = np.concatenate([lead, samples, tail])
        self.pos = 0
        self.t0 = None
        self.end_sent_at: float | None = None

    async def recv(self):
        if self.t0 is None:
            self.t0 = time.perf_counter()
        target = self.t0 + self.pos / SR
        delay = target - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        chunk = self.data[self.pos:self.pos + FRAME]
        if len(chunk) < FRAME:
            chunk = np.concatenate([chunk, np.zeros(FRAME - len(chunk), dtype=np.int16)])
        frame = AudioFrame.from_ndarray(chunk.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = SR
        frame.pts = self.pos
        frame.time_base = fractions.Fraction(1, SR)
        self.pos += FRAME
        if self.end_sent_at is None and self.pos >= self.speech_end:
            self.end_sent_at = time.perf_counter()
        return frame


async def run_one(url: str, wav_path: str, out_dir: str, timeout_s: float = 60) -> dict:
    x, sr = read_wav(wav_path)
    x48 = (np.clip(resample(x, sr, SR), -1, 1) * 32767).astype(np.int16)
    track = FileTrack(x48)
    pc = RTCPeerConnection()
    pc.addTransceiver(track, direction="sendrecv")
    pc.addTransceiver("video", direction="recvonly")
    dc = pc.createDataChannel("chat")
    messages, received = [], []
    first_audio_at = {"t": None}
    done = asyncio.Event()

    @dc.on("message")
    def on_msg(m):
        try:
            j = json.loads(m)
        except Exception:
            return
        msg = j.get("message", j.get("data", j)) if isinstance(j, dict) else j
        messages.append({"t": time.perf_counter(), "msg": msg})
        if isinstance(msg, dict) and msg.get("type") in ("turn", "error"):
            done.set()

    async def consume(remote):
        while True:
            try:
                f = await remote.recv()
            except Exception:
                return
            arr = f.to_ndarray().reshape(-1)
            if f.layout.name != "mono" and len(arr) == 2 * f.samples:
                arr = arr.reshape(-1, 2).mean(axis=1).astype(np.int16)
            now = time.perf_counter()
            if track.end_sent_at is not None:
                received.append((now, f.sample_rate, arr.astype(np.int16)))
                if first_audio_at["t"] is None and np.abs(arr).max() > 300:
                    first_audio_at["t"] = now

    tasks = []

    @pc.on("track")
    def on_track(remote):
        if remote.kind == "audio":
            tasks.append(asyncio.ensure_future(consume(remote)))

    await pc.setLocalDescription(await pc.createOffer())
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(url.rstrip("/") + "/api/offer",
                            json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})
        r.raise_for_status()
        ans = r.json()
    await pc.setRemoteDescription(RTCSessionDescription(sdp=ans["sdp"], type=ans["type"]))
    try:
        await asyncio.wait_for(done.wait(), timeout_s)
    except asyncio.TimeoutError:
        pass
    # the "turn" message is urgent; the reply audio is paced in real time, so wait for it
    t_wait = time.perf_counter()
    while first_audio_at["t"] is None and time.perf_counter() - t_wait < 15:
        await asyncio.sleep(0.05)
    if first_audio_at["t"] is not None:
        await asyncio.sleep(1.0)
        last_loud = first_audio_at["t"]
        while time.perf_counter() - last_loud < 1.2 and time.perf_counter() - first_audio_at["t"] < 30:
            await asyncio.sleep(0.2)
            loud = [t for t, _, a in received if np.abs(a).max() > 300]
            last_loud = loud[-1] if loud else last_loud
    await pc.close()
    for t in tasks:
        t.cancel()

    name = os.path.splitext(os.path.basename(wav_path))[0]
    os.makedirs(out_dir, exist_ok=True)
    turn = next((m["msg"] for m in messages if isinstance(m["msg"], dict) and m["msg"].get("type") == "turn"), None)
    if received:
        out_sr = received[0][1]
        pcm = np.concatenate([a for _, _, a in received])
        # trim leading silence before the reply
        loud = np.where(np.abs(pcm) > 300)[0]
        if len(loud):
            pcm = pcm[max(0, loud[0] - out_sr // 10): loud[-1] + out_sr // 5]
        with wave.open(os.path.join(out_dir, f"{name}.reply.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(out_sr); w.writeframes(pcm.tobytes())
    v2v = None
    if first_audio_at["t"] and track.end_sent_at:
        v2v = round((first_audio_at["t"] - track.end_sent_at) * 1000, 1)
    rec = {"input": wav_path, "transport": "WebRTC (Pipecat SmallWebRTCTransport, aiortc client)",
           "client_v2v_ms": v2v, "turn": turn,
           "reply_audio": os.path.join(out_dir, f"{name}.reply.wav") if received else None,
           "messages": [m["msg"] for m in messages]}
    with open(os.path.join(out_dir, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return rec


async def main_async(a):
    out = []
    for p in a.files:
        rec = await run_one(a.url, p, a.out)
        t = rec["turn"] or {}
        print(f"{os.path.basename(p)}: v2v(client)={rec['client_v2v_ms']} ms | heard: {t.get('transcript')!r} | "
              f"lang={t.get('lang')} | tools={[c['tool'] for c in t.get('tool_calls', [])]} | answer: {t.get('answer')!r}")
        out.append(rec)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--url", default="http://127.0.0.1:17860")
    ap.add_argument("--out", default="examples/webrtc")
    a = ap.parse_args()
    asyncio.run(main_async(a))


if __name__ == "__main__":
    main()
