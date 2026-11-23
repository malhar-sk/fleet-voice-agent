import pytest

from evals.metrics import check_fact, mentions_device, normalize, numbers_in, wer
from voice.stt import choose_lang, collapse_repeats


def test_normalize_devanagari_and_pi():
    assert normalize("पाई-३ का तापमान क्या है?") == "pi 3 का तापमान क्या है"
    assert normalize("Pi-3, offline!") == "pi 3 offline"
    assert normalize("pi three") == "pi 3"
    assert normalize("फ़्लीट") == normalize("फ्लीट")


def test_wer_basic():
    assert wer("Which devices are offline?", "which devices are offline") == 0.0
    assert wer("a b c d", "a x c d") == pytest.approx(0.25)


@pytest.mark.parametrize("text", ["pi 3 is offline", "पाई 3 बंद है", "पि 3 अभी अफलाइन है", "Pi-3 is down"])
def test_mentions_device(text):
    assert mentions_device(text, "pi-3")


def test_mixed_script_device_name_is_not_accepted():
    assert not mentions_device("पi 3 बंद पडले आहे", "pi-3")


def test_numbers_ignore_device_ids():
    assert numbers_in("pi 3 is at 55 degrees") == [55.0]


def test_check_fact_kinds():
    off = {"offline": [{"device": "pi-3", "silent_for_seconds": 300}], "offline_count": 1, "total_devices": 5}
    assert check_fact("offline_list", "Only pi 3 is offline.", off)[0]
    assert not check_fact("offline_list", "All devices are online.", off)[0]
    fleet = {"online_count": 4, "offline_count": 1, "total": 5,
             "devices": [{"device": "pi-3", "status": "OFFLINE"}] + [{"device": f"pi-{i}", "status": "ONLINE"} for i in (1, 2, 4, 5)]}
    assert check_fact("online_count", "4 of 5 devices are online.", fleet)[0]
    assert check_fact("online_count", "सभी चालू हैं, सिर्फ़ pi 3 ऑफ़लाइन है", fleet)[0]
    assert check_fact("device_state", "pi 3 ऑफलाइन आहे", {"status": "OFFLINE"})[0]
    assert not check_fact("device_state", "pi 5 is offline", {"status": "ONLINE"})[0]
    m = {"metric": "temperature", "latest": 55.4, "avg": 55.0, "min": 54.0, "max": 57.0}
    assert check_fact("metric_value", "about 55 degrees", m)[0]
    assert not check_fact("metric_value", "about 70 degrees", m)[0]
    assert check_fact("sla_count", "There were 3 breaches.", {"sla_breaches": 3, "minutes": 10})[0]
    assert check_fact("sla_count", "No breaches in the last 5 minutes.", {"sla_breaches": 0, "minutes": 5})[0]


def test_choose_lang_policy():
    assert choose_lang({"en": 0.99, "hi": 0.0, "mr": 0.0}) == "en"
    assert choose_lang({"en": 0.17, "hi": 0.12, "mr": 0.03}) == "mr"   # low-confidence English -> Indic -> mr decode
    assert choose_lang({"en": 0.0, "hi": 0.97, "mr": 0.001}) == "mr"   # MR_RATIO=0: decode hi/mr with the Marathi token


def test_collapse_repeats():
    assert collapse_repeats("गेल्या, pi-5, pi-5, pi-5, pi-5,") == "गेल्या, pi-5"
    assert collapse_repeats("pi 3 pi 3 is down") == "pi 3 pi 3 is down"
