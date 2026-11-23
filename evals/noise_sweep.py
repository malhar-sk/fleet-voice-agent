"""Eval round 2: noise robustness sweep. ALL AUDIO IS SYNTHETIC (Piper speech + generated noise).

  python -m evals.noise_sweep                  # make audio (if missing) -> STT -> rules tool choice -> report
  (without --claude, results go to rows_rules_only.jsonl / report_rules_only.md, so the committed Claude run stays)
  python -m evals.noise_sweep --claude         # also Claude (claude_cli) tool choice on the 10 dB sets + clean

The 30 clean question clips (evals/audio/{en,hi,mr}NN.wav) are mixed with two noise types that are
generated here (nothing is downloaded):
  white       Gaussian white noise
  babble_fan  "cafe + fan": 3 overlapping SYNTHETIC dev-set utterances (evals/audio/dev, never in the eval
              set) as babble, plus a fan: low-passed brown noise and a 120 Hz blade tone with 2 harmonics
              and slow amplitude wobble. Babble and fan have equal power.
at SNR 20, 10 and 5 dB. SNR is speech power over noise power, where speech power is measured over the
active frames only (20 ms frames within 35 dB of the loudest frame), so the 0.3 s silent padding does
not make the SNR look worse than it is. Seeds are fixed, so the audio is reproducible;
the files go to evals/audio/noise_sweep/ (gitignored) with sha256s in evals/results/noise_sweep/manifest.json.

Per clip we run the same STT as the app (faster-whisper small int8, 1 thread, restricted en/hi/mr
language policy) and then the agent's PLANNING step only: which tools would be called with which
arguments. Tool choice is decided entirely by that step for both backends (rules: rules.plan;
claude_cli: the first "plan" call of the 2-step protocol), so the answer call is skipped to save
LLM calls. Everything is cached:
  STT     evals/results/noise_sweep/stt.jsonl, keyed by audio sha256 + model + settings
  Claude  .cache/llm (the agent's own disk cache, same key as the app: model + prompt)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time

os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np  # noqa: E402

from evals.metrics import corpus_cer, corpus_wer  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO_OUT = os.path.join(ROOT, "evals", "audio", "noise_sweep")
OUT = os.path.join(ROOT, "evals", "results", "noise_sweep")
SNRS = [20, 10, 5]
NOISES = ["white", "babble_fan"]
LANGS = [("en", "English"), ("hi", "Hindi"), ("mr", "Marathi")]


def load_questions():
    return [json.loads(l) for l in open(os.path.join(ROOT, "evals/questions.jsonl"), encoding="utf-8")
            if l.strip() and not json.loads(l).get("noise")]


# ---------- noise generation ----------

def active_power(x: np.ndarray, sr: int, floor_db: float = 35.0) -> float:
    """Mean power over 20 ms frames within floor_db of the loudest frame (speech-active power)."""
    f = max(1, int(0.02 * sr))
    n = len(x) // f
    if n == 0:
        return float(np.mean(x ** 2))
    p = np.mean(x[: n * f].reshape(n, f) ** 2, axis=1)
    keep = p >= p.max() * 10 ** (-floor_db / 10)
    return float(p[keep].mean())


def white_noise(n: int, rng) -> np.ndarray:
    return rng.standard_normal(n)


def fan_noise(n: int, sr: int, rng) -> np.ndarray:
    brown = np.cumsum(rng.standard_normal(n))
    brown -= np.convolve(brown, np.ones(sr // 20) / (sr // 20), mode="same")   # remove drift (high-pass ~20 Hz)
    k = max(1, sr // 2000)                                                       # crude low-pass
    brown = np.convolve(brown, np.ones(k) / k, mode="same")
    t = np.arange(n) / sr
    wobble = 1 + 0.2 * np.sin(2 * np.pi * 0.7 * t + rng.uniform(0, 6.28))
    tone = sum(a * np.sin(2 * np.pi * 120 * h * t + rng.uniform(0, 6.28)) for h, a in ((1, 1.0), (2, 0.5), (3, 0.25)))
    brown /= np.sqrt(np.mean(brown ** 2)) + 1e-12
    tone /= np.sqrt(np.mean(tone ** 2)) + 1e-12
    return wobble * (0.7 * brown + 0.3 * tone)


def babble_noise(n: int, sources: list[np.ndarray], rng) -> np.ndarray:
    out = np.zeros(n)
    for _ in range(3):
        s = sources[rng.integers(len(sources))]
        s = np.tile(s, int(np.ceil(n / len(s))) + 1)
        off = rng.integers(0, len(s) - n)
        out += s[off: off + n]
    return out


def make_noise(kind: str, n: int, sr: int, rng, babble_src) -> np.ndarray:
    if kind == "white":
        return white_noise(n, rng)
    if kind == "babble_fan":
        b, f = babble_noise(n, babble_src, rng), fan_noise(n, sr, rng)
        b /= np.sqrt(np.mean(b ** 2)) + 1e-12
        f /= np.sqrt(np.mean(f ** 2)) + 1e-12
        return b + f
    raise ValueError(kind)


def scale_noise(clean: np.ndarray, noise: np.ndarray, sr: int, snr_db: float) -> np.ndarray:
    """Scale noise so that active speech power / noise power = snr_db."""
    return noise * np.sqrt(active_power(clean, sr) / (np.mean(noise ** 2) * 10 ** (snr_db / 10)))


def mix_at_snr(clean: np.ndarray, noise: np.ndarray, sr: int, snr_db: float) -> np.ndarray:
    out = clean + scale_noise(clean, noise, sr, snr_db)
    return out / max(1.0, np.abs(out).max() / 0.98)      # only scale down if it would clip (keeps the SNR)


def clip_path(qid: str, noise: str, snr) -> str:
    if noise == "clean":
        return os.path.join(ROOT, "evals", "audio", f"{qid}.wav")
    return os.path.join(AUDIO_OUT, f"{noise}_{snr}db", f"{qid}.wav")


def make_audio(qs) -> dict:
    from evals.make_audio import write_wav
    from voice.tts import read_wav
    dev = sorted(os.listdir(os.path.join(ROOT, "evals", "audio", "dev")))
    babble_src = []
    for f in dev:
        x, sr_b = read_wav(os.path.join(ROOT, "evals", "audio", "dev", f))
        babble_src.append(x.astype(np.float64))
    manifest = {}
    for ni, noise in enumerate(NOISES):
        for si, snr in enumerate(SNRS):
            for qi, q in enumerate(qs):
                p = clip_path(q["id"], noise, snr)
                x, sr = read_wav(os.path.join(ROOT, q["audio"]))
                assert sr == sr_b, "babble sources and questions must share a sample rate"
                if not os.path.exists(p):
                    rng = np.random.default_rng(1000 * ni + 100 * si + qi)
                    nz = make_noise(noise, len(x), sr, rng, babble_src)
                    write_wav(p, mix_at_snr(x.astype(np.float64), nz, sr, snr), sr)
                manifest[os.path.relpath(p, ROOT)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    os.makedirs(OUT, exist_ok=True)
    json.dump({"note": "SYNTHETIC: Piper speech + generated noise (evals/noise_sweep.py). Regenerate with "
                       "`python -m evals.noise_sweep --audio-only`.", "files": manifest},
              open(os.path.join(OUT, "manifest.json"), "w"), indent=1)
    return manifest


# ---------- STT (cached) ----------

def stt_settings() -> dict:
    from voice import stt
    return {"model": os.path.basename(stt.MODEL_DIR.rstrip("/")), "threads": stt.THREADS, "prompt": stt.USE_PROMPT,
            "mr_ratio": stt.MR_RATIO, "en_min": stt.EN_MIN, "max_tokens": stt.MAX_NEW_TOKENS}


def run_stt(conditions, qs) -> list[dict]:
    cache_path = os.path.join(OUT, "stt.jsonl")
    cache = {}
    if os.path.exists(cache_path):
        for l in open(cache_path, encoding="utf-8"):
            r = json.loads(l)
            cache[r["cache_id"]] = r
    settings = stt_settings()
    model = None
    rows = []
    with open(cache_path, "a", encoding="utf-8") as fh:
        for noise, snr in conditions:
            for q in qs:
                p = clip_path(q["id"], noise, snr)
                sha = hashlib.sha256(open(p, "rb").read()).hexdigest()
                key = hashlib.sha256(json.dumps([sha, settings], sort_keys=True).encode()).hexdigest()[:24]
                if key not in cache:
                    if model is None:
                        from voice.stt import WhisperSTT
                        from voice.tts import read_wav
                        model = WhisperSTT()
                        model.transcribe(*read_wav(os.path.join(ROOT, "evals/audio/dev/dev_en1.wav")))  # warm-up
                    from voice.tts import read_wav
                    x, sr = read_wav(p)
                    r = model.transcribe(x, sr)
                    rec = {"cache_id": key, "audio_sha256": sha, "settings": settings, "transcript": r.text,
                           "detected_lang": r.lang, "whisper_lang": r.whisper_lang, "lang_probs": r.lang_probs,
                           "stt_ms": r.total_ms, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fh.flush()
                    cache[key] = rec
                    print(f"  stt {noise:<10} {snr!s:>5} {q['id']}: {r.lang} {r.total_ms:.0f} ms {r.text[:60]!r}", flush=True)
                c = cache[key]
                rows.append({"id": q["id"], "lang": q["lang"], "noise": noise, "snr_db": snr, "reference": q["text"],
                             "audio": os.path.relpath(p, ROOT), **{k: c[k] for k in (
                                 "transcript", "detected_lang", "whisper_lang", "lang_probs", "stt_ms", "audio_sha256")}})
    return rows


# ---------- tool choice (planning step only) ----------

def plan_rules(text, lang):
    from agent import rules
    return rules.plan(text)


class ClaudePlanner:
    """Only the first ('plan') call of the claude_cli 2-step protocol, through the agent's own disk cache."""

    def __init__(self):
        from agent.agent import ClaudeCLIBackend
        self.b = ClaudeCLIBackend(use_cache=True)
        self.calls = self.hits = 0

    def __call__(self, text, lang):
        from agent import prompts
        from agent.agent import _extract_json
        raw, cached = self.b._cached_complete(prompts.cli_plan_system(), prompts.user_turn(text, lang))
        self.calls += 1
        self.hits += int(cached)
        try:
            return _extract_json(raw).get("calls") or []
        except (ValueError, json.JSONDecodeError):
            return []


def score(rows, qs_by_id, planner, name):
    from evals.run_eval import score_tools
    for r in rows:
        calls = planner(r["transcript"], r["detected_lang"])
        q = qs_by_id[r["id"]]
        r[f"{name}_calls"] = calls
        r[f"{name}_tool_ok"], r[f"{name}_args_ok"] = score_tools(q, calls)


# ---------- report ----------

def _pct(xs):
    return f"{100 * sum(xs) / len(xs):.0f}%" if xs else "–"


def report(rows, sfx: str = "") -> str:
    conds = [("clean", "clean")] + [(n, s) for n in NOISES for s in SNRS]
    lines = ["| Noise | SNR | Lang | n | WER | CER | Lang ID | Tool choice (rules) | Tool+args (rules) | Tool choice (Claude) | Tool+args (Claude) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    summary = []
    for noise, snr in conds:
        for lang, lname in LANGS + [("all", "**All**")]:
            g = [r for r in rows if r["noise"] == noise and r["snr_db"] == snr and (lang == "all" or r["lang"] == lang)]
            if not g:
                continue
            w = corpus_wer([r["reference"] for r in g], [r["transcript"] for r in g])
            c = corpus_cer([r["reference"] for r in g], [r["transcript"] for r in g])
            has_claude = all("claude_tool_ok" in r for r in g)
            ent = {"noise": noise, "snr_db": snr, "lang": lang, "n": len(g), "wer": round(w, 3), "cer": round(c, 3),
                   "lang_id": sum(r["detected_lang"] == r["lang"] for r in g) / len(g),
                   "rules_tool": sum(r["rules_tool_ok"] for r in g) / len(g),
                   "rules_args": sum(r["rules_args_ok"] for r in g) / len(g),
                   "claude_tool": sum(r["claude_tool_ok"] for r in g) / len(g) if has_claude else None,
                   "claude_args": sum(r["claude_args_ok"] for r in g) / len(g) if has_claude else None}
            summary.append(ent)
            lines.append(f"| {noise} | {snr if snr == 'clean' else str(snr) + ' dB'} | {lname} | {len(g)} | {w:.3f} | {c:.3f} | "
                         f"{_pct([r['detected_lang'] == r['lang'] for r in g])} | {_pct([r['rules_tool_ok'] for r in g])} | "
                         f"{_pct([r['rules_args_ok'] for r in g])} | "
                         f"{_pct([r['claude_tool_ok'] for r in g]) if has_claude else 'not run'} | "
                         f"{_pct([r['claude_args_ok'] for r in g]) if has_claude else 'not run'} |")
    json.dump(summary, open(os.path.join(OUT, f"summary{sfx}.json"), "w"), indent=1)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--claude", action="store_true", help="Claude (claude_cli) tool choice on clean + 10 dB sets")
    ap.add_argument("--audio-only", action="store_true")
    a = ap.parse_args()
    qs = load_questions()
    qs_by_id = {q["id"]: q for q in qs}
    t0 = time.time()
    make_audio(qs)
    if a.audio_only:
        return
    conditions = [("clean", "clean")] + [(n, s) for n in NOISES for s in SNRS]
    rows = run_stt(conditions, qs)
    score(rows, qs_by_id, plan_rules, "rules")
    meta = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)), "stt": stt_settings(), "n_clips": len(rows),
            "command": "python -m evals.noise_sweep" + (" --claude" if a.claude else "")}
    if a.claude:
        cp = ClaudePlanner()
        sub = [r for r in rows if r["snr_db"] in ("clean", 10)]
        score(sub, qs_by_id, cp, "claude")
        meta["claude"] = {"model": cp.b.model, "plan_calls": cp.calls, "cache_hits": cp.hits,
                          "new_llm_calls": cp.calls - cp.hits}
        print(f"claude plan calls: {cp.calls} ({cp.hits} from cache)")
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sfx = "" if a.claude else "_rules_only"     # a rules-only re-run never overwrites the committed Claude results
    with open(os.path.join(OUT, f"rows{sfx}.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    json.dump(meta, open(os.path.join(OUT, f"meta{sfx}.json"), "w"), indent=2)
    table = report(rows, sfx)
    open(os.path.join(OUT, f"report{sfx}.md"), "w", encoding="utf-8").write(
        "# Noise sweep (SYNTHETIC speech + generated noise)\n\n" + json.dumps(meta) + "\n\n" + table + "\n")
    print(table)


if __name__ == "__main__":
    main()
