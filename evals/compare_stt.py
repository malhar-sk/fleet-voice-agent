"""Eval round 2: compare Whisper models for speech-to-text, mainly Marathi. ALL AUDIO IS SYNTHETIC (Piper).

  python -m evals.compare_stt --model whisper-small whisper-medium --langs mr
  python -m evals.compare_stt --model whisper-medium --langs en hi       # regression check on the other languages

Each model runs in its own child process (so peak RSS is per model), CPU int8, 1 thread, through the
app's own WhisperSTT class (same en/hi/mr language policy, same domain prompt). For every clip we
record two decodes:
  auto      the full app path: restricted language ID -> decode -> hi/mr word check (what users get)
  forced_mr decode with language="mr" given (Marathi clips only): an upper bound on what a perfect
            language ID would give with this model
Seconds per clip = wall time of WhisperSTT.transcribe (language ID + decode) after one warm-up clip.

Memory guard: the child refuses to load a model if MemAvailable < 1 GB + the model file size, and a
watchdog stops it if MemAvailable drops under 1 GB while running (written to BLOCKED.md by the parent).
Results: evals/results/stt_compare/<model>.jsonl (+ report.md); a model/clip/settings result is reused
if it is already there.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import threading
import time

os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "evals", "results", "stt_compare")
MIN_FREE_MB = 1024


def mem_available_mb() -> int:
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable:"):
            return int(l.split()[1]) // 1024
    return 10 ** 6


def load_questions(langs):
    qs = [json.loads(l) for l in open(os.path.join(ROOT, "evals/questions.jsonl"), encoding="utf-8") if l.strip()]
    return [q for q in qs if not q.get("noise") and q["lang"] in langs]


def child(model: str, langs: list[str]):
    """Runs in a separate process: load one model, transcribe, append rows to the jsonl."""
    model_dir = os.path.join(ROOT, "models", model)
    size_mb = os.path.getsize(os.path.join(model_dir, "model.bin")) // 2 ** 20
    if mem_available_mb() < MIN_FREE_MB + size_mb:
        print(f"LOWMEM before load: MemAvailable {mem_available_mb()} MB < {MIN_FREE_MB} + {size_mb} MB", flush=True)
        sys.exit(3)

    def watchdog():
        while True:
            if mem_available_mb() < MIN_FREE_MB:
                print(f"LOWMEM during run: MemAvailable {mem_available_mb()} MB", flush=True)
                os._exit(3)
            time.sleep(1)
    threading.Thread(target=watchdog, daemon=True).start()

    from evals.metrics import cer, wer
    from voice.stt import WhisperSTT
    from voice.tts import read_wav
    path = os.path.join(OUT, f"{model}.jsonl")
    done = set()
    if os.path.exists(path):
        done = {(r["id"], r["mode"]) for r in (json.loads(l) for l in open(path, encoding="utf-8"))}
    todo = [(q, m) for q in load_questions(langs) for m in (["auto", "forced_mr"] if q["lang"] == "mr" else ["auto"])
            if (q["id"], m) not in done]
    if not todo:
        print(f"{model}: all cached")
        return
    t = time.perf_counter()
    stt = WhisperSTT(model_dir=model_dir, threads=int(os.environ.get("STT_THREADS", "1")))
    load_s = time.perf_counter() - t
    x, sr = read_wav(os.path.join(ROOT, "evals/audio/dev/dev_mr1.wav"))
    stt.transcribe(x, sr)  # warm-up, not scored
    with open(path, "a", encoding="utf-8") as fh:
        for q, mode in todo:
            x, sr = read_wav(os.path.join(ROOT, q["audio"]))
            t = time.perf_counter()
            r = stt.transcribe(x, sr, language="mr" if mode == "forced_mr" else None)
            sec = time.perf_counter() - t
            rec = {"model": model, "id": q["id"], "lang": q["lang"], "mode": mode, "reference": q["text"],
                   "transcript": r.text, "detected_lang": r.lang, "whisper_lang": r.whisper_lang,
                   "lang_probs": r.lang_probs, "sec": round(sec, 3), "audio_s": r.audio_s,
                   "wer": round(wer(q["text"], r.text), 4), "cer": round(cer(q["text"], r.text), 4),
                   "load_s": round(load_s, 1), "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024,
                   "threads": int(os.environ.get("STT_THREADS", "1")),
                   "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            print(f"  {model} {q['id']} {mode:<9} {sec:5.1f}s wer {rec['wer']:.2f} {r.lang} {r.text[:60]!r}", flush=True)
    print(f"{model}: peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB, load {load_s:.1f}s")


def report() -> str:
    import numpy as np
    from agent import rules
    from evals.metrics import corpus_cer, corpus_wer
    from evals.run_eval import score_tools
    qs = {q["id"]: q for q in load_questions(["en", "hi", "mr"])}
    lines = ["| Model | Clips | Decode | n | WER | CER | Lang ID (final) | Tool choice (rules, on these transcripts) "
             "| s/clip mean | s/clip p50 | s/clip max | Peak RSS |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for f in sorted(os.listdir(OUT)):
        if not f.endswith(".jsonl"):
            continue
        rows = [json.loads(l) for l in open(os.path.join(OUT, f), encoding="utf-8")]
        for lang in ("mr", "hi", "en"):
            for mode in ("auto", "forced_mr"):
                g = [r for r in rows if r["lang"] == lang and r["mode"] == mode]
                if not g:
                    continue
                s = [r["sec"] for r in g]
                lines.append(
                    f"| {g[0]['model']} | {lang} | {mode} | {len(g)} | "
                    f"{corpus_wer([r['reference'] for r in g], [r['transcript'] for r in g]):.3f} | "
                    f"{corpus_cer([r['reference'] for r in g], [r['transcript'] for r in g]):.3f} | "
                    f"{100 * sum(r['detected_lang'] == lang for r in g) / len(g):.0f}% | "
                    f"{sum(score_tools(qs[r['id']], rules.plan(r['transcript']))[0] for r in g)}/{len(g)} | {np.mean(s):.2f} s | "
                    f"{np.median(s):.2f} s | {max(s):.2f} s | {max(r['peak_rss_mb'] for r in g)} MB |")
    return "\n".join(lines)


def main():
    if "--report-only" in sys.argv:
        print(report())
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", nargs="+", default=["whisper-small", "whisper-medium"])
    ap.add_argument("--langs", nargs="+", default=["mr"])
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    if a.child:
        child(a.model[0], a.langs)
        return
    for m in a.model:
        print(f"== {m} (MemAvailable {mem_available_mb()} MB)", flush=True)
        p = subprocess.run([sys.executable, "-m", "evals.compare_stt", "--child", "--model", m, "--langs", *a.langs],
                           cwd=ROOT, env={**os.environ, "OMP_NUM_THREADS": "1", "STT_THREADS": "1"})
        if p.returncode == 3:
            with open(os.path.join(ROOT, "BLOCKED.md"), "a", encoding="utf-8") as fh:
                fh.write(f"\n## STT comparison: {m} stopped for low memory ({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())})\n\n"
                         f"- MemAvailable fell under {MIN_FREE_MB} MB (shared server), so `python -m evals.compare_stt "
                         f"--model {m}` was stopped. Partial rows are in `evals/results/stt_compare/{m}.jsonl`.\n"
                         f"- Next step: re-run that command when the server has more free memory (results are cached).\n")
            print(f"{m}: stopped for low memory, noted in BLOCKED.md")
        elif p.returncode:
            print(f"{m}: failed with exit code {p.returncode}")
    table = report()
    open(os.path.join(OUT, "report.md"), "w", encoding="utf-8").write(
        "# STT model comparison (SYNTHETIC speech, CPU int8, 1 thread)\n\n" + table + "\n")
    print(table)


if __name__ == "__main__":
    main()
