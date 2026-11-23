"""Text-to-speech with Piper (offline ONNX voices) in English, Hindi and Marathi.

Voices (models/piper/, downloaded by scripts/download_models.py):
  en  en_US-lessac-medium   (reply voice)      en_US-amy-medium   (eval question voice)
  hi  hi_IN-pratham-medium  (reply voice)      hi_IN-rohan-medium (eval question voice)
  mr  mr_IN-google-medium   (9 speakers: reply speaker 0, eval questions speaker 4)
Piper's espeak-ng front end reads digits in each language (55 -> "पचपन" / "पंचावन्न"),
so answers keep numbers as digits.
"""
from __future__ import annotations

import io
import os
import re
import time
import wave
from dataclasses import dataclass
from typing import Iterator

import numpy as np

MODELS = os.environ.get("PIPER_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "piper"))

REPLY_VOICES = {"en": ("en_US-lessac-medium", None), "hi": ("hi_IN-pratham-medium", None), "mr": ("mr_IN-google-medium", 0)}
QUESTION_VOICES = {"en": ("en_US-amy-medium", None), "hi": ("hi_IN-rohan-medium", None), "mr": ("mr_IN-google-medium", 4)}

_SENT_SPLIT = re.compile(r"(?<=[.!?।])\s+")


@dataclass
class Chunk:
    pcm: bytes          # int16 mono
    sample_rate: int
    text: str


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text or "") if p.strip()]
    return parts or ([text.strip()] if text and text.strip() else [])


class PiperTTS:
    def __init__(self, voices: dict | None = None, models_dir: str = MODELS):
        self.voices_cfg = voices or REPLY_VOICES
        self.models_dir = models_dir
        self._loaded = {}

    def _voice(self, name: str):
        if name not in self._loaded:
            from piper import PiperVoice
            self._loaded[name] = PiperVoice.load(os.path.join(self.models_dir, f"{name}.onnx"))
        return self._loaded[name]

    def preload(self):
        for name, _ in self.voices_cfg.values():
            self._voice(name)
        return self

    def sample_rate(self, lang: str) -> int:
        return self._voice(self.voices_cfg.get(lang, self.voices_cfg["en"])[0]).config.sample_rate

    def stream(self, text: str, lang: str) -> Iterator[Chunk]:
        """Yield audio one sentence at a time (the first sentence is ready early)."""
        from piper import SynthesisConfig
        name, speaker = self.voices_cfg.get(lang, self.voices_cfg["en"])
        voice = self._voice(name)
        cfg = SynthesisConfig(speaker_id=speaker) if speaker is not None else None
        for sent in split_sentences(text):
            pcm = b"".join(c.audio_int16_bytes for c in voice.synthesize(sent, syn_config=cfg))
            yield Chunk(pcm=pcm, sample_rate=voice.config.sample_rate, text=sent)

    def synthesize(self, text: str, lang: str) -> tuple[bytes, int, dict]:
        t0 = time.perf_counter()
        first_ms, chunks, sr = None, [], 22050
        for c in self.stream(text, lang):
            if first_ms is None:
                first_ms = (time.perf_counter() - t0) * 1000
            chunks.append(c.pcm)
            sr = c.sample_rate
        total_ms = (time.perf_counter() - t0) * 1000
        pcm = b"".join(chunks)
        return pcm, sr, {"first_chunk_ms": round(first_ms or total_ms, 1), "total_ms": round(total_ms, 1),
                         "audio_s": round(len(pcm) / 2 / sr, 2)}


def pcm_to_wav(pcm: bytes, sr: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


def pcm_to_ogg_opus(pcm: bytes, sr: int, bitrate: int = 32000) -> bytes:
    """Encode to OGG/Opus (what Telegram wants for voice notes) with PyAV, no ffmpeg binary needed."""
    import av
    samples = np.frombuffer(pcm, dtype=np.int16)
    out = io.BytesIO()
    with av.open(out, mode="w", format="ogg") as container:
        stream = container.add_stream("libopus", rate=48000)
        stream.bit_rate = bitrate
        stream.layout = "mono"
        resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
        step = sr // 10
        for i in range(0, len(samples), step):
            block = samples[i:i + step]
            frame = av.AudioFrame.from_ndarray(block.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate = sr
            for rf in resampler.resample(frame):
                for packet in stream.encode(rf):
                    container.mux(packet)
        for rf in resampler.resample(None):
            for packet in stream.encode(rf):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return out.getvalue()


def read_wav(path_or_bytes) -> tuple[np.ndarray, int]:
    """Read a WAV (any int16/float sample format soundfile understands) to float32 mono."""
    import soundfile as sf
    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray)) else path_or_bytes
    data, sr = sf.read(src, dtype="float32", always_2d=True)
    return data.mean(axis=1), sr
