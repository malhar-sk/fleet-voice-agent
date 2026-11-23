"""Tiny text language ID for en / hi / mr.

Whisper's acoustic language ID mixes up Hindi and Marathi (both Devanagari, many shared words),
so we decide between them from the text: function words that are specific to each language.
"""
from __future__ import annotations

import re

LANGS = ("en", "hi", "mr")
LANG_NAMES = {"en": "English", "hi": "Hindi", "mr": "Marathi"}

_MR = {
    "आहे", "आहेत", "नाही", "नाहीत", "किती", "कोणते", "कोणती", "कोणत्या", "कोणता", "सध्या", "मध्ये", "आणि",
    "गेल्या", "मिनिटांत", "मिनिटांपासून", "उपकरण", "उपकरणे", "उपकरणं", "झाले", "झाली", "सांगा", "होते", "होती",
    "चे", "ची", "चा", "च्या", "ला", "ते", "काय", "किंवा", "आता", "सगळे", "सर्व", "बंद", "पडले", "किती", "तापमान",
    "दाखवा", "कसे", "कसा", "कशी", "मेमरी", "वापर", "पेमेंट", "उल्लंघने", "उल्लंघन", "झालेत", "आहेस", "तुम्ही",
}
_HI = {
    "है", "हैं", "नहीं", "कितने", "कितना", "कितनी", "कौन", "कौनसे", "कौन से", "में", "का", "की", "के", "क्या",
    "पिछले", "बताओ", "बताइए", "बताएं", "और", "हो", "था", "थे", "अभी", "सभी", "उपकरण", "डिवाइस", "ऑफ़लाइन",
    "मिनट", "से", "को", "कैसा", "कैसी", "रहा", "रही", "रहे", "हुए", "हुआ", "भुगतान", "उल्लंघन", "दिखाओ", "चल",
}
# words that appear in both; don't let them decide
_SHARED = {"उपकरण", "उल्लंघन", "तापमान", "मेमरी", "पेमेंट", "बंद"}

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")
_TOKEN = re.compile(r"[ऀ-ॿ]+|[A-Za-z]+")


def detect_text_lang(text: str, default: str = "en") -> str:
    """Return 'en', 'hi' or 'mr' for a piece of text."""
    if not text or not text.strip():
        return default
    dev = len(_DEVANAGARI.findall(text))
    lat = len(_LATIN.findall(text))
    if dev == 0:
        return "en" if lat else default
    tokens = _TOKEN.findall(text)
    mr = sum(1 for t in tokens if t in _MR and t not in _SHARED)
    hi = sum(1 for t in tokens if t in _HI and t not in _SHARED)
    # Marathi suffixes glued to words: ...ांत, ...ची, ...च्या, ...ला
    mr += sum(1 for t in tokens if re.search(r"(ांत|ांना|ांची|ाची|ाचे|ाच्या|ामध्ये|ाला)$", t))
    if mr > hi:
        return "mr"
    if hi > mr:
        return "hi"
    return default if default in ("hi", "mr") else "hi"


def resolve_lang(whisper_lang: str | None, transcript: str) -> str:
    """Combine Whisper's acoustic guess with the text check (text wins for hi vs mr)."""
    text_lang = detect_text_lang(transcript, default=whisper_lang if whisper_lang in LANGS else "en")
    if text_lang == "en" and whisper_lang in ("hi", "mr") and not _DEVANAGARI.search(transcript or ""):
        # Hindi/Marathi speech transcribed in Latin letters: trust Whisper's guess
        return whisper_lang
    return text_lang
