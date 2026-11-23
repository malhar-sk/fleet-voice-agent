"""Offline fallback "LLM": keyword intent router + answer templates in en/hi/mr.

Used when no LLM is reachable (for example in Docker with no ANTHROPIC_API_KEY), so the voice
demo still works end to end. It is NOT a language model. RESULTS.md reports it separately.
"""
from __future__ import annotations

import re

from agent.fleet_tools import ToolError, normalize_device

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

INTENT_WORDS = {
    "offline": ["offline", "down", "dead", "silent", "not reporting", "unreachable", "ऑफ़लाइन", "ऑफलाइन", "बंद",
                "ऑफ लाइन", "ऑफ़ लाइन", "डाउन"],
    "sla": ["sla", "breach", "payment", "payments", "mt103", "gateway", "queue", "पेमेंट", "भुगतान", "उल्लंघन",
            "एसएलए", "गेटवे", "पेमेंट्स"],
    "temperature": ["temperature", "temp", "hot", "heat", "तापमान", "गरम", "टेम्परेचर"],
    "memory": ["memory", "ram", "मेमरी", "मेमोरी", "रैम"],
    "cpu": ["cpu", "load", "सीपीयू", "processor"],
    "uptime": ["uptime", "running for", "since boot", "अपटाइम", "रीबूट", "reboot"],
    "list": ["how many", "all devices", "list", "fleet", "online", "devices", "कितने", "किती", "सभी", "सर्व",
             "ऑनलाइन", "डिवाइस", "उपकरणे", "उपकरण"],
}
_DEVICE_RE = re.compile(r"(?:pi|पाई|पी|पाय|device|डिवाइस|उपकरण)\s*[-_ ]?\s*([0-9०-९]+|one|two|three|four|five|एक|दो|दोन|तीन|चार|पांच|पाँच|पाच)",
                        re.IGNORECASE)
_MINUTES_RE = re.compile(r"([0-9०-९]+)\s*(?:min|minutes|mins|मिनट|मिनिट|मिनिटां|मिनिटे|मिनिटांत)", re.IGNORECASE)


FUZZY_MIN = 0.72


def _fuzzy_token_match(text: str, words) -> bool:
    """Whisper often misspells loanwords in Devanagari (ऑफ़लाइन -> अफलाइ / अप्लाइ). Compare tokens of 4+
    characters against single-word keywords with a similarity ratio instead of exact substrings."""
    from difflib import SequenceMatcher
    toks = [t for t in re.findall(r"[\u0900-\u097F]{4,}", text.replace("\u093c", ""))]
    keys = [w.replace("\u093c", "") for w in words if " " not in w and re.search(r"[\u0900-\u097F]", w) and len(w) >= 4]
    return any(SequenceMatcher(None, t, k).ratio() >= FUZZY_MIN for t in toks for k in keys)


def _has(text: str, words) -> bool:
    t = text.lower()
    return any(w in t for w in words) or _fuzzy_token_match(text, words)


def find_device(text: str) -> str | None:
    m = _DEVICE_RE.search(text)
    if not m:
        return None
    try:
        return normalize_device(m.group(1))
    except ToolError:
        return None


def find_minutes(text: str) -> int | None:
    m = _MINUTES_RE.search(text)
    return int(m.group(1).translate(_DEV_DIGITS)) if m else None


def plan(text: str) -> list[dict]:
    """Pick tool calls for a question (deterministic)."""
    dev = find_device(text)
    minutes = find_minutes(text)
    for metric in ("temperature", "memory", "cpu", "uptime"):
        if _has(text, INTENT_WORDS[metric]) and dev:
            return [{"tool": "query_metric", "args": {"device": dev, "metric": metric, "minutes": minutes or 10}}]
    if _has(text, INTENT_WORDS["sla"]):
        return [{"tool": "sla_breaches", "args": {"minutes": minutes or 5}}]
    if dev:
        return [{"tool": "device_status", "args": {"name": dev}}]
    if _has(text, INTENT_WORDS["offline"]):
        return [{"tool": "list_offline_devices", "args": {}}]
    if _has(text, INTENT_WORDS["list"]):
        return [{"tool": "list_devices", "args": {}}]
    return []


def _mins(seconds: float) -> int:
    return max(1, int(round(seconds / 60)))


def _spoken_dev(d: str) -> str:
    return d.replace("-", " ")


def _join(items: list[str], lang: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    conj = {"en": "and", "hi": "और", "mr": "आणि"}[lang]
    return ", ".join(items[:-1]) + f" {conj} " + items[-1]


T = {
    "none_offline": {"en": "All {total} devices are online right now.",
                     "hi": "अभी सभी {total} डिवाइस ऑनलाइन हैं।",
                     "mr": "सध्या सर्व {total} उपकरणे ऑनलाइन आहेत."},
    "some_offline": {"en": "{n} of {total} devices are offline: {names}. {first} has been silent for {m} minutes.",
                     "hi": "{total} में से {n} डिवाइस ऑफ़लाइन हैं: {names}। {first} {m} मिनट से बंद है।",
                     "mr": "{total} पैकी {n} उपकरणे ऑफलाइन आहेत: {names}. {first} {m} मिनिटांपासून बंद आहे."},
    "fleet": {"en": "{online} of {total} devices are online{off}.",
              "hi": "{total} में से {online} डिवाइस ऑनलाइन हैं{off}।",
              "mr": "{total} पैकी {online} उपकरणे ऑनलाइन आहेत{off}."},
    "fleet_off": {"en": ", and {names} is offline", "hi": ", और {names} ऑफ़लाइन है", "mr": ", आणि {names} ऑफलाइन आहे"},
    "dev_online": {"en": "{d} is online, at {t} degrees with {mem} percent memory used.",
                   "hi": "{d} ऑनलाइन है, तापमान {t} डिग्री और मेमरी {mem} प्रतिशत है।",
                   "mr": "{d} ऑनलाइन आहे, तापमान {t} अंश आणि मेमरी {mem} टक्के आहे."},
    "dev_offline": {"en": "{d} is offline; it has been silent for {m} minutes.",
                    "hi": "{d} ऑफ़लाइन है, यह {m} मिनट से चुप है।",
                    "mr": "{d} ऑफलाइन आहे, ते {m} मिनिटांपासून बंद आहे."},
    "metric": {"en": "{d} {metric} is {v}{unit} now, averaging {avg}{unit} over the last {mins} minutes.",
               "hi": "{d} का {metric} अभी {v}{unit} है, पिछले {mins} मिनट का औसत {avg}{unit} है।",
               "mr": "{d} चे {metric} सध्या {v}{unit} आहे, गेल्या {mins} मिनिटांची सरासरी {avg}{unit} आहे."},
    "metric_silent": {"en": "{d} has sent no {metric} readings in the last {mins} minutes.",
                      "hi": "{d} ने पिछले {mins} मिनट में कोई {metric} डेटा नहीं भेजा।",
                      "mr": "{d} ने गेल्या {mins} मिनिटांत कोणतेही {metric} रीडिंग पाठवले नाही."},
    "sla": {"en": "There were {b} payment SLA breaches in the last {mins} minutes, out of {sent} messages sent.",
            "hi": "पिछले {mins} मिनट में {sent} मैसेज में से {b} पेमेंट SLA उल्लंघन हुए।",
            "mr": "गेल्या {mins} मिनिटांत {sent} संदेशांपैकी {b} पेमेंट SLA उल्लंघने झाली."},
    "unknown": {"en": "I can only answer questions about the device fleet and the payment gateway.",
                "hi": "मैं सिर्फ़ डिवाइस फ़्लीट और पेमेंट गेटवे के बारे में बता सकता हूँ।",
                "mr": "मी फक्त उपकरणांच्या ताफ्याबद्दल आणि पेमेंट गेटवेबद्दल सांगू शकतो."},
    "error": {"en": "Sorry, I could not get that: {e}.", "hi": "माफ़ कीजिए, यह जानकारी नहीं मिली: {e}।",
              "mr": "माफ करा, ही माहिती मिळाली नाही: {e}."},
}
METRIC_NAMES = {
    "temperature": {"en": "temperature", "hi": "तापमान", "mr": "तापमान"},
    "memory": {"en": "memory use", "hi": "मेमरी", "mr": "मेमरी वापर"},
    "cpu": {"en": "CPU use", "hi": "सीपीयू", "mr": "सीपीयू वापर"},
    "uptime": {"en": "uptime", "hi": "अपटाइम", "mr": "अपटाइम"},
}
UNIT_WORDS = {
    "°C": {"en": " degrees", "hi": " डिग्री", "mr": " अंश"},
    "%": {"en": " percent", "hi": " प्रतिशत", "mr": " टक्के"},
    "s": {"en": " seconds", "hi": " सेकंड", "mr": " सेकंद"},
}


def answer(calls_and_results: list[dict], lang: str) -> str:
    lang = lang if lang in ("en", "hi", "mr") else "en"
    if not calls_and_results:
        return T["unknown"][lang]
    c = calls_and_results[0]
    tool, r = c["tool"], c["result"]
    if "error" in r:
        return T["error"][lang].format(e=r["error"])
    if tool == "list_offline_devices":
        if r["offline_count"] == 0:
            return T["none_offline"][lang].format(total=r["total_devices"])
        names = [_spoken_dev(o["device"]) for o in r["offline"]]
        first = r["offline"][0]
        return T["some_offline"][lang].format(n=r["offline_count"], total=r["total_devices"],
                                             names=_join(names, lang), first=_spoken_dev(first["device"]),
                                             m=_mins(first["silent_for_seconds"]))
    if tool == "list_devices":
        off = [_spoken_dev(d["device"]) for d in r["devices"] if d["status"] == "OFFLINE"]
        off_s = T["fleet_off"][lang].format(names=_join(off, lang)) if off else ""
        return T["fleet"][lang].format(online=r["online_count"], total=r["total"], off=off_s)
    if tool == "device_status":
        d = _spoken_dev(r["device"])
        if r["status"] == "OFFLINE":
            return T["dev_offline"][lang].format(d=d, m=_mins(r["last_seen_seconds_ago"]))
        return T["dev_online"][lang].format(d=d, t=round(r["cpu_temperature_c"] or 0), mem=round(r["memory_percent"] or 0))
    if tool == "query_metric":
        d = _spoken_dev(r["device"])
        mname = METRIC_NAMES[r["metric"]][lang]
        if "latest" not in r:
            return T["metric_silent"][lang].format(d=d, metric=mname, mins=r["minutes"])
        unit = UNIT_WORDS[r["unit"]][lang]
        v, avg = r["latest"], r["avg"]
        if r["metric"] == "uptime":
            unit = {"en": " minutes", "hi": " मिनट", "mr": " मिनिटे"}[lang]
            v, avg = _mins(v), _mins(avg)
        else:
            v, avg = round(v), round(avg)
        return T["metric"][lang].format(d=d, metric=mname, v=v, avg=avg, unit=unit, mins=r["minutes"])
    if tool == "sla_breaches":
        return T["sla"][lang].format(b=r["sla_breaches"], mins=r["minutes"], sent=r["messages_sent"])
    return T["unknown"][lang]
