import pytest

from agent import rules
from agent.lang import detect_text_lang, resolve_lang


@pytest.mark.parametrize("text,lang", [
    ("Which devices are offline?", "en"),
    ("अभी कौन से डिवाइस ऑफ़लाइन हैं?", "hi"),
    ("पाई 3 का तापमान क्या है?", "hi"),
    ("सध्या कोणती उपकरणे ऑफलाइन आहेत?", "mr"),
    ("गेल्या 10 मिनिटांत किती पेमेंट उल्लंघने झाली?", "mr"),
    ("पाई 2 ची स्थिती काय आहे?", "mr"),
])
def test_detect_text_lang(text, lang):
    assert detect_text_lang(text) == lang


def test_resolve_lang_prefers_text_for_devanagari():
    assert resolve_lang("hi", "सध्या कोणती उपकरणे ऑफलाइन आहेत?") == "mr"
    assert resolve_lang("mr", "Which devices are offline?") == "en"


@pytest.mark.parametrize("q,tool,args", [
    ("Which devices are offline?", "list_offline_devices", {}),
    ("How many devices are online?", "list_devices", {}),
    ("What is the temperature of pi-4?", "query_metric", {"device": "pi-4", "metric": "temperature", "minutes": 10}),
    ("How is pi 2 doing?", "device_status", {"name": "pi-2"}),
    ("Any payment SLA breaches in the last 15 minutes?", "sla_breaches", {"minutes": 15}),
    ("अभी कौन से डिवाइस ऑफ़लाइन हैं?", "list_offline_devices", {}),
    ("पाई 3 का तापमान क्या है?", "query_metric", {"device": "pi-3", "metric": "temperature", "minutes": 10}),
    ("पाई पाच ची मेमरी किती आहे?", "query_metric", {"device": "pi-5", "metric": "memory", "minutes": 10}),
    ("गेल्या 10 मिनिटांत किती पेमेंट उल्लंघने झाली?", "sla_breaches", {"minutes": 10}),
])
def test_rules_plan(q, tool, args):
    calls = rules.plan(q)
    assert calls and calls[0]["tool"] == tool and calls[0]["args"] == args


def test_rules_unknown():
    assert rules.plan("tell me a joke") == []
    assert "only" in rules.answer([], "en")


def test_rules_answers_contain_facts():
    res = {"total_devices": 5, "offline_count": 1, "offline_after_seconds": 120,
           "offline": [{"device": "pi-3", "silent_for_seconds": 245, "silent_for_minutes": 4.1}]}
    for lang in ("en", "hi", "mr"):
        a = rules.answer([{"tool": "list_offline_devices", "result": res}], lang)
        assert "pi 3" in a and "4" in a
