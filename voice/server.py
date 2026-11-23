"""FastAPI app: web page, WebRTC signalling (Pipecat SmallWebRTC), push-to-talk, /tts for n8n.

  python -m voice.server            # http://localhost:7860 (in Docker: host port 17860)

Endpoints
  GET  /              web/index.html (Talk button)
  POST /api/offer     WebRTC SDP offer -> answer (starts a Pipecat pipeline per connection)
  PATCH /api/offer    trickle ICE candidates
  POST /api/turn      push-to-talk fallback: WAV upload -> JSON (transcript, answer, timings, reply WAV base64)
  POST /api/ask       text question -> agent answer (no audio)
  POST /tts           {"text", "lang", "format": "ogg"|"wav"} -> audio (used by the n8n alert workflow)
  GET  /health
"""
from __future__ import annotations

import asyncio
import base64
import os
import time
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from loguru import logger
from pydantic import BaseModel

from agent.agent import FleetAgent, make_backend, pick_backend_name
from agent.lang import detect_text_lang

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")

state: dict = {}


def get_engine():
    if "engine" not in state:
        from voice.engine import VoiceEngine
        t0 = time.time()
        state["engine"] = VoiceEngine(agent=FleetAgent(make_backend()))
        logger.info(f"voice engine ready in {time.time() - t0:.1f}s (LLM backend: {state['engine'].agent.backend.name})")
    return state["engine"]


def get_tts():
    if os.environ.get("TTS_ONLY") == "1":
        if "tts" not in state:
            from voice.tts import PiperTTS
            state["tts"] = PiperTTS().preload()
        return state["tts"]
    return get_engine().tts


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequestHandler
        state["webrtc"] = SmallWebRTCRequestHandler()
    except ImportError as e:  # CI installs only the light dependencies
        logger.warning(f"WebRTC disabled (pipecat not installed): {e}")
    if os.environ.get("PRELOAD", "1") == "1" and os.environ.get("TTS_ONLY") != "1":
        await asyncio.get_running_loop().run_in_executor(None, get_engine)
    yield
    if "webrtc" in state:
        await state["webrtc"].close()


app = FastAPI(title="fleet-voice-agent", lifespan=lifespan)


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"))


@app.get("/health")
def health():
    return {"status": "ok", "llm_backend": pick_backend_name(), "engine_loaded": "engine" in state}


@app.post("/api/offer")
async def offer(request: Request, background: BackgroundTasks):
    from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequest
    from voice.pipeline import run_bot

    body = await request.json()
    req = SmallWebRTCRequest.from_dict({k: v for k, v in body.items()
                                        if k in ("sdp", "type", "pc_id", "restart_pc", "request_data", "requestData")})
    engine = get_engine()

    async def on_connection(conn):
        background.add_task(run_bot, conn, engine)

    return await state["webrtc"].handle_web_request(req, on_connection)


@app.patch("/api/offer")
async def offer_patch(request: Request):
    from pipecat.transports.smallwebrtc.request_handler import IceCandidate, SmallWebRTCPatchRequest

    body = await request.json()
    cands = [IceCandidate(candidate=c["candidate"], sdp_mid=c.get("sdp_mid", c.get("sdpMid")),
                          sdp_mline_index=c.get("sdp_mline_index", c.get("sdpMLineIndex")))
             for c in body.get("candidates", [])]
    await state["webrtc"].handle_patch_request(SmallWebRTCPatchRequest(pc_id=body["pc_id"], candidates=cands))
    return {"status": "success"}


@app.post("/api/turn")
async def push_to_talk(audio: UploadFile):
    """Push-to-talk: works through SSH tunnels / Docker port mapping where WebRTC media can't."""
    from voice.tts import pcm_to_wav, read_wav

    data = await audio.read()
    try:
        x, sr = read_wav(data)
    except Exception as e:
        raise HTTPException(400, f"could not read audio (send WAV): {e}")
    engine = get_engine()
    result, pcm, out_sr = await asyncio.get_running_loop().run_in_executor(None, engine.turn, x, sr)
    return JSONResponse({**result.to_dict(), "audio_wav_b64": base64.b64encode(pcm_to_wav(pcm, out_sr)).decode() if pcm else None})


class Ask(BaseModel):
    question: str
    lang: str | None = None


@app.post("/api/ask")
async def ask(body: Ask):
    agent = state.get("engine").agent if "engine" in state else FleetAgent(make_backend())
    r = await asyncio.get_running_loop().run_in_executor(None, agent.respond, body.question, body.lang)
    return r.to_dict()


class TTSReq(BaseModel):
    text: str
    lang: str | None = None
    format: str = "ogg"


@app.post("/tts")
async def tts(body: TTSReq):
    from voice.tts import pcm_to_ogg_opus, pcm_to_wav

    if not body.text.strip():
        raise HTTPException(400, "empty text")
    lang = body.lang if body.lang in ("en", "hi", "mr") else detect_text_lang(body.text)
    engine_tts = get_tts()
    pcm, sr, info = await asyncio.get_running_loop().run_in_executor(None, engine_tts.synthesize, body.text, lang)
    if body.format == "wav":
        return Response(pcm_to_wav(pcm, sr), media_type="audio/wav",
                        headers={"X-TTS-Lang": lang, "X-TTS-Ms": str(info["total_ms"])})
    return Response(pcm_to_ogg_opus(pcm, sr), media_type="audio/ogg",
                    headers={"X-TTS-Lang": lang, "X-TTS-Ms": str(info["total_ms"]),
                             "Content-Disposition": 'attachment; filename="alert.ogg"'})


def main():
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "7860")), log_level="info")


if __name__ == "__main__":
    main()
