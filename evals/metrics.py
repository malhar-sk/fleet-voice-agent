"""Scoring helpers for the voice eval: text normalisation, WER/CER, key-fact checks."""
from __future__ import annotations

import re
import unicodedata

import jiwer

NUM_WORDS = {
    # English
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "fifteen": 15, "no": 0, "none": 0,
    # Hindi
    "शून्य": 0, "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "छः": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
    "पंद्रह": 15,
    # Marathi
    "दोन": 2, "पाच": 5, "सहा": 6, "नऊ": 9, "पंधरा": 15,
}
_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
# spellings Whisper / TTS use for the device prefix "pi"
_PI = re.compile(r"\b(pi|pie|pai|py|पाई|पाय|पी|पि|पई|पए|पै)\s*[-‐]?\s*(\d+)", re.IGNORECASE)


def normalize(text: str) -> str:
    """Lowercase, strip punctuation and nukta, Devanagari digits -> ASCII, number words -> digits,
    'पाई 3' / 'Pi-3' / 'pi three' -> 'pi 3'. Applied identically to reference and hypothesis."""
    t = unicodedata.normalize("NFC", text or "").lower()
    t = t.replace("़", "")                 # nukta: फ़ -> फ, ड़ -> ड
    t = t.replace("ँ", "ं")           # chandrabindu -> anusvara
    t = t.translate(_DEV_DIGITS)
    t = re.sub(r"[^\w\sऀ-ॿ-]", " ", t)
    t = re.sub(r"[।॥]", " ", t)
    words = []
    for w in t.replace("-", " ").split():
        words.append(str(NUM_WORDS[w]) if w in NUM_WORDS and w not in ("no", "none") else w)
    t = " ".join(words)
    t = _PI.sub(lambda m: f"pi {m.group(2)}", t)
    return re.sub(r"\s+", " ", t).strip()


def wer(ref: str, hyp: str) -> float:
    r, h = normalize(ref), normalize(hyp)
    if not r:
        return 0.0 if not h else 1.0
    return jiwer.wer(r, h if h else "<empty>")


def cer(ref: str, hyp: str) -> float:
    r, h = normalize(ref), normalize(hyp)
    if not r:
        return 0.0 if not h else 1.0
    return jiwer.cer(r, h if h else "<empty>")


def corpus_wer(refs: list[str], hyps: list[str]) -> float:
    r = [normalize(x) for x in refs]
    h = [normalize(x) or "<empty>" for x in hyps]
    return jiwer.wer(r, h) if r else float("nan")


def corpus_cer(refs, hyps) -> float:
    r = [normalize(x) for x in refs]
    h = [normalize(x) or "<empty>" for x in hyps]
    return jiwer.cer(r, h) if r else float("nan")


def numbers_in(text: str) -> list[float]:
    t = normalize(text)
    t = re.sub(r"pi \d+", " ", t)              # device ids are not facts
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]


def mentions_device(text: str, dev: str) -> bool:
    n = dev.split("-")[-1]
    return re.search(rf"\bpi {n}\b", normalize(text)) is not None


OFFLINE_WORDS = ["offline", "down", "silent", "not reporting", "ऑफलाइन", "ऑफ़लाइन", "ऑफ लाइन", "बंद", "चुप", "शांत",
                 "नहीं भेज", "डाउन", "बन्द"]
ONLINE_WORDS = ["online", "up and running", "running", "fine", "healthy", "ऑनलाइन", "चालू", "सुरू", "ठीक", "व्यवस्थित",
                "चल रहा", "काम कर"]


def _norm_words(ws):
    return [normalize(w) for w in ws]


def check_fact(kind: str, answer: str, truth: dict) -> tuple[bool, str]:
    """Is the key fact present in the answer? Returns (ok, explanation)."""
    a = normalize(answer)
    nums = numbers_in(answer)
    if kind == "offline_list":
        offline = [o["device"] for o in truth["offline"]]
        if not offline:
            ok = any(w in a for w in _norm_words(["all", "none", "no device", "सभी", "सर्व", "कोई नहीं", "कोणतेही नाही"]))
            return ok, "expected: no device offline"
        missing = [d for d in offline if not mentions_device(answer, d)]
        return not missing, f"expected offline: {offline}; missing: {missing}"
    if kind == "online_count":
        n = truth["online_count"]
        ok = n in [int(x) for x in nums if x == int(x)]
        if not ok and truth["offline_count"] > 0:
            # "all except pi 3" style answers also carry the fact
            off = [d["device"] for d in truth["devices"] if d["status"] == "OFFLINE"]
            ok = all(mentions_device(answer, d) for d in off) and any(w in a for w in _norm_words(OFFLINE_WORDS))
        return ok, f"expected online count {n} (of {truth['total']})"
    if kind == "device_state":
        st = truth["status"]
        words = OFFLINE_WORDS if st == "OFFLINE" else ONLINE_WORDS
        ok = any(normalize(w) in a for w in words)
        if st == "ONLINE" and any(normalize(w) in a for w in ["offline", "ऑफलाइन"]) and not any(normalize(w) in a for w in ["online", "ऑनलाइन"]):
            ok = False
        return ok, f"expected status {st}"
    if kind == "metric_value":
        vals = [truth.get(k) for k in ("latest", "avg", "min", "max") if truth.get(k) is not None]
        tol = 1.5 if truth.get("metric") == "temperature" else 3.0
        ok = any(abs(n - v) <= tol for n in nums for v in vals)
        return ok, f"expected ~{vals} ±{tol}"
    if kind == "sla_count":
        b = truth["sla_breaches"]
        ok = any(abs(n - b) <= 1 for n in nums)
        if b == 0 and not ok:
            ok = any(normalize(w) in a for w in ["no ", "zero", "none", "कोई नहीं", "नहीं", "नाही", "कोणतेही", "एकही"])
        return ok, f"expected {b} breaches in {truth['minutes']} min (±1)"
    raise ValueError(kind)
