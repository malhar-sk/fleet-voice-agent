"""Eval round 2 helpers: noise mixing at a target SNR, plan-only tool scoring, language confusion matrix."""
import numpy as np
import pytest

from evals import lang_confusion as lc
from evals import noise_sweep as ns

SR = 16000


def _speech_like(seed=0, sr=SR):
    rng = np.random.default_rng(seed)
    t = np.arange(int(1.5 * sr)) / sr
    x = 0.3 * np.sin(2 * np.pi * 220 * t) * (1 + 0.5 * np.sin(2 * np.pi * 3 * t)) + 0.01 * rng.standard_normal(len(t))
    pad = np.zeros(int(0.3 * sr))
    return np.concatenate([pad, x, pad])


def test_active_power_ignores_silent_padding():
    x = _speech_like()
    core = x[int(0.3 * SR): -int(0.3 * SR)]
    assert ns.active_power(x, SR) == pytest.approx(np.mean(core ** 2), rel=0.05)
    assert ns.active_power(x, SR) > np.mean(x ** 2)


@pytest.mark.parametrize("kind", ["white", "babble_fan"])
@pytest.mark.parametrize("snr", [20, 10, 5])
def test_mix_hits_target_snr(kind, snr):
    x = _speech_like()
    rng = np.random.default_rng(1)
    babble = [_speech_like(s) for s in range(3)]
    nz = ns.make_noise(kind, len(x), SR, rng, babble)
    n = ns.scale_noise(x, nz, SR, snr)
    measured = 10 * np.log10(ns.active_power(x, SR) / np.mean(n ** 2))
    assert measured == pytest.approx(snr, abs=0.01)
    y = ns.mix_at_snr(x, nz, SR, snr)
    # the mix is only ever scaled down, both parts equally, to avoid clipping (so the SNR is kept)
    g = min(1.0, 0.98 / np.abs(x + n).max())
    assert np.allclose(y, g * (x + n))
    assert np.abs(y).max() <= 0.981


def test_noise_is_deterministic_per_seed():
    a = ns.make_noise("babble_fan", 8000, SR, np.random.default_rng(7), [_speech_like(1)])
    b = ns.make_noise("babble_fan", 8000, SR, np.random.default_rng(7), [_speech_like(1)])
    assert np.array_equal(a, b)


def test_rules_plan_scoring_on_transcripts():
    from evals.run_eval import score_tools
    q = {"acceptable_tools": ["query_metric"], "expected_args": {"device": "pi-2", "metric": "temperature"}}
    ok = ns.plan_rules("What is the temperature of pi 2?", "en")
    assert score_tools(q, ok) == (True, True)
    wrong_dev = ns.plan_rules("What is the temperature of pi 4?", "en")
    assert score_tools(q, wrong_dev) == (True, False)
    assert score_tools(q, ns.plan_rules("hmm", "en")) == (False, False)


def test_confusion_matrix_and_markdown():
    rows = [{"lang": "en", "detected_lang": "en", "lang_probs": {"en": 0.9, "hi": 0.05, "mr": 0.05}},
            {"lang": "mr", "detected_lang": "hi", "lang_probs": {"en": 0.1, "hi": 0.6, "mr": 0.3}},
            {"lang": "mr", "detected_lang": "mr", "lang_probs": {"en": 0.5, "hi": 0.3, "mr": 0.2}}]
    final = lc.matrix(rows, lambda r: r["detected_lang"])
    assert final["mr"] == {"en": 0, "hi": 1, "mr": 1}
    raw = lc.matrix(rows, lambda r: lc.argmax_lang(r["lang_probs"]))
    assert raw["mr"] == {"en": 1, "hi": 1, "mr": 0}
    text = lc.md(final, "t")
    assert "accuracy 66.7% (2/3)" in text and "| mr | 0 | 1 | 1 | 50% |" in text
