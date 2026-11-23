"""Speech-to-text: faster-whisper `small` (multilingual, CPU int8) restricted to en / hi / mr.

Whisper's language ID picks from ~100 languages; we only accept English, Hindi and Marathi, so we
take its probabilities and choose the best of those three. Detection and transcription normally
run the encoder twice (about 3 s each on one CPU thread); `_EncodeOnceWhisper` caches the encoder
output so the 30 s window is encoded once per utterance.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import numpy as np

from agent.lang import resolve_lang

ALLOWED = ("en", "hi", "mr")
MODEL_DIR = os.environ.get("WHISPER_MODEL", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                         "models", "whisper-small"))
THREADS = int(os.environ.get("STT_THREADS", "1"))
MAX_NEW_TOKENS = int(os.environ.get("STT_MAX_TOKENS", "96"))
# Domain vocabulary as Whisper's initial prompt: biases decoding towards device names and fleet words.
USE_PROMPT = os.environ.get("STT_PROMPT", "1") == "1"
PROMPTS = {
    # no enumerations: a list like "pi-1, pi-2, ..." made Whisper loop ("pi-5, pi-5, pi-5, ...")
    "en": "Questions about the device fleet: is pi 3 offline? What is the temperature and memory? Payment SLA breaches.",
    "hi": "डिवाइस फ़्लीट के सवाल: क्या पाई 3 ऑफ़लाइन है? तापमान और मेमरी कितनी है? पेमेंट एसएलए उल्लंघन।",
    "mr": "उपकरणांबद्दल प्रश्न: पाई 3 ऑफलाइन आहे का? तापमान आणि मेमरी किती आहे? पेमेंट एसएलए उल्लंघने.",
}
# Whisper-small separates Hindi from Marathi poorly: on the dev set (evals/tune_stt.py) it never
# preferred Marathi for Marathi speech. So when the best of en/hi/mr is hi, we decode with the
# Marathi token anyway (the decoder still writes Hindi words in Devanagari) and let the text check
# in agent/lang.py pick hi vs mr. MR_RATIO=0 means "always"; dev set: 7/8 vs 5/8 for plain argmax.
MR_RATIO = float(os.environ.get("STT_MR_RATIO", "0.0"))


# English speech is detected with high confidence (dev set: P(en) > 0.99 for every English clip,
# <= 0.17 for Marathi clips that Whisper ranked as English). Below EN_MIN we treat it as Indic.
EN_MIN = float(os.environ.get("STT_EN_MIN", "0.5"))


def choose_lang(p: dict) -> str:
    best = max(p, key=p.get)
    if best == "en" and p["en"] < EN_MIN:
        best = "hi" if p.get("hi", 0) >= p.get("mr", 0) else "mr"
    if best == "hi" and p.get("mr", 0) >= MR_RATIO * p["hi"]:
        return "mr"
    return best


@dataclass
class STTResult:
    text: str
    lang: str                     # final language used for the reply (en/hi/mr)
    whisper_lang: str             # Whisper's restricted acoustic guess
    lang_probs: dict = field(default_factory=dict)
    detect_ms: float = 0.0
    transcribe_ms: float = 0.0
    total_ms: float = 0.0
    audio_s: float = 0.0


def _make_model_class():
    from faster_whisper import WhisperModel

    class _EncodeOnceWhisper(WhisperModel):
        """Reuse the language-detection encoder output for the first transcription window.

        Only used for utterances shorter than one 30 s window, where both passes see the same audio
        (they differ only in the zero padding at the end).
        """
        _reuse = None

        def encode(self, features):
            if self._reuse is not None:
                val, self._reuse = self._reuse, None
                return val
            return super().encode(features)

    return _EncodeOnceWhisper


class WhisperSTT:
    def __init__(self, model_dir: str = MODEL_DIR, threads: int = THREADS, beam_size: int = 1):
        cls = _make_model_class()
        self.model = cls(model_dir, device="cpu", compute_type="int8", cpu_threads=threads, num_workers=1)
        self.beam_size = beam_size

    def detect(self, audio: np.ndarray):
        """Restricted language ID. Returns (best of en/hi/mr, their probabilities, encoder output)."""
        from faster_whisper.audio import pad_or_trim
        fe = self.model.feature_extractor
        feats = fe(audio[: fe.n_samples])
        enc = self.model.encode(pad_or_trim(feats[..., : fe.nb_max_frames]))
        results = self.model.model.detect_language(enc)[0]
        probs = {tok[2:-2]: p for tok, p in results}
        allowed = {k: round(float(probs.get(k, 0.0)), 4) for k in ALLOWED}
        return choose_lang(allowed), allowed, enc

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, language: str | None = None) -> STTResult:
        """audio: float32 mono in [-1, 1]."""
        t0 = time.perf_counter()
        if sample_rate != 16000:
            audio = resample(audio, sample_rate, 16000)
        audio = audio.astype(np.float32)
        if language is None:
            wl, probs, enc = self.detect(audio)
            if len(audio) < self.model.feature_extractor.n_samples - 16000:
                self.model._reuse = enc
        else:
            wl, probs = language, {language: 1.0}
        t1 = time.perf_counter()
        try:
            segs, _ = self.model.transcribe(audio, language=wl, beam_size=self.beam_size, vad_filter=False,
                                            condition_on_previous_text=False, without_timestamps=True,
                                            # voice commands are short: no temperature fallback, bounded decode
                                            # (fallback once took 38 s re-decoding a hard clip)
                                            temperature=0.0, max_new_tokens=MAX_NEW_TOKENS,
                                            initial_prompt=PROMPTS.get(wl) if USE_PROMPT else None)
            text = collapse_repeats(" ".join(s.text.strip() for s in segs).strip())
        finally:
            self.model._reuse = None
        t2 = time.perf_counter()
        lang = resolve_lang(wl, text) if language is None else language
        return STTResult(text=text, lang=lang, whisper_lang=wl, lang_probs=probs,
                         detect_ms=round((t1 - t0) * 1000, 1), transcribe_ms=round((t2 - t1) * 1000, 1),
                         total_ms=round((t2 - t0) * 1000, 1), audio_s=round(len(audio) / 16000, 2))


def collapse_repeats(text: str) -> str:
    """Cut Whisper repetition loops (a phrase repeated 3+ times): 'pi-5, pi-5, pi-5, pi-5,' -> 'pi-5,'."""
    import re
    pattern = re.compile(r"((?:\S+[\s,]+){1,3}?)\1{2,}")
    prev = None
    while prev != text:
        prev = text
        text = pattern.sub(lambda m: m.group(1), text + " ").strip()
    return text.strip(" ,")


def resample(audio: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out or len(audio) == 0:
        return audio
    n_out = int(round(len(audio) * sr_out / sr_in))
    x_old = np.linspace(0, 1, num=len(audio), endpoint=False)
    x_new = np.linspace(0, 1, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def pcm16_to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
