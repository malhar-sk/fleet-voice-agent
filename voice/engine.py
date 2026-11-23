"""One voice turn: user audio -> STT -> agent (LLM + tools) -> TTS, with per-stage timings.

Used by the Pipecat pipeline, the push-to-talk HTTP endpoint, the scripted example run and the eval,
so every path measures the same code.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterator

import numpy as np

from agent.agent import AgentResult, FleetAgent, make_backend
from voice.stt import STTResult, WhisperSTT
from voice.tts import Chunk, PiperTTS

MIN_SPEECH_S = 0.3


@dataclass
class TurnResult:
    transcript: str
    lang: str
    answer: str
    stt: dict
    agent: dict
    tts: dict = field(default_factory=dict)
    timings_ms: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class VoiceEngine:
    def __init__(self, stt: WhisperSTT | None = None, tts: PiperTTS | None = None, agent: FleetAgent | None = None):
        self.stt = stt or WhisperSTT()
        self.tts = tts or PiperTTS().preload()
        self.agent = agent or FleetAgent(make_backend())
        self._lock = threading.Lock()   # one model run at a time (small CPU box)

    def understand(self, audio: np.ndarray, sr: int) -> tuple[STTResult, AgentResult | None]:
        stt = self.stt.transcribe(audio, sr)
        if len(stt.text.strip()) < 2:
            return stt, None
        return stt, self.agent.respond(stt.text, stt.lang)

    def turn_stream(self, audio: np.ndarray, sr: int, on_chunk: Callable[[Chunk], None] | None = None) -> TurnResult:
        """Run a turn; call on_chunk for each TTS sentence as soon as it is ready.

        Timings (all from the moment this is called = end of user audio):
          stt_ms, llm_ms (LLM wait, all rounds), tools_ms, agent_ms, tts_first_ms (synth of first sentence),
          v2v_first_audio_ms (end of user audio -> first reply audio ready), total_ms.
        """
        with self._lock:
            t0 = time.perf_counter()
            stt = self.stt.transcribe(audio, sr)
            t_stt = time.perf_counter()
            if len(stt.text.strip()) < 2:
                return TurnResult("", stt.lang, "", asdict(stt), {}, {}, {"stt_ms": round((t_stt - t0) * 1000, 1)})
            ar = self.agent.respond(stt.text, stt.lang)
            t_agent = time.perf_counter()
            first_at, chunks, total_samples, sr_out = None, 0, 0, 22050
            for c in self.tts.stream(ar.answer, ar.lang):
                if first_at is None:
                    first_at = time.perf_counter()
                chunks += 1
                total_samples += len(c.pcm) // 2
                sr_out = c.sample_rate
                if on_chunk:
                    on_chunk(c)
            t_end = time.perf_counter()
            first_at = first_at or t_end
            timings = {
                "stt_ms": round((t_stt - t0) * 1000, 1),
                "stt_detect_ms": stt.detect_ms,
                "stt_transcribe_ms": stt.transcribe_ms,
                "llm_ms": ar.llm_ms,
                "llm_api_ms": ar.llm_api_ms,
                "tools_ms": ar.tools_ms,
                "agent_ms": round((t_agent - t_stt) * 1000, 1),
                "tts_first_ms": round((first_at - t_agent) * 1000, 1),
                "tts_total_ms": round((t_end - t_agent) * 1000, 1),
                "v2v_first_audio_ms": round((first_at - t0) * 1000, 1),
                "total_ms": round((t_end - t0) * 1000, 1),
            }
            return TurnResult(stt.text, ar.lang, ar.answer, asdict(stt), ar.to_dict(),
                              {"chunks": chunks, "audio_s": round(total_samples / sr_out, 2), "sample_rate": sr_out},
                              timings)

    def turn(self, audio: np.ndarray, sr: int) -> tuple[TurnResult, bytes, int]:
        pcm_parts: list[bytes] = []
        holder = {"sr": 22050}

        def keep(c: Chunk):
            pcm_parts.append(c.pcm)
            holder["sr"] = c.sample_rate

        r = self.turn_stream(audio, sr, keep)
        return r, b"".join(pcm_parts), holder["sr"]
