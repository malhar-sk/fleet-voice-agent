"""Build the results tables from evals/results/*.jsonl -> evals/results/report.md (+ summary.json).

  python -m evals.report
"""
from __future__ import annotations

import glob
import json
import os

import numpy as np

from evals.metrics import check_fact, corpus_cer, corpus_wer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "evals", "results")
GROUPS = [("English", lambda r: r["lang"] == "en" and not r["noisy"]),
          ("Hindi", lambda r: r["lang"] == "hi" and not r["noisy"]),
          ("Marathi", lambda r: r["lang"] == "mr" and not r["noisy"]),
          ("**All clean (30)**", lambda r: not r["noisy"]),
          ("Noisy variants (5)", lambda r: r["noisy"]),
          ("All (35)", lambda r: True)]


def load(tag):
    """Load a results file and re-score the key fact with the CURRENT checker (answers are not re-generated)."""
    p = os.path.join(RESULTS, f"{tag}.jsonl")
    if not os.path.exists(p):
        return None
    rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    for r in rows:
        r["fact_ok_at_run"] = r["fact_ok"]
        if "error" not in r["truth"]:
            r["fact_ok"], r["fact_note"] = check_fact(r["key_fact"], r["answer"], r["truth"])
    return rows


def pct(xs, q):
    xs = [x for x in xs if x is not None]
    return float(np.percentile(xs, q)) if xs else float("nan")


def acc(rows, key):
    return sum(1 for r in rows if r[key]) / len(rows) if rows else float("nan")


def f_pct(x):
    return "-" if x != x else f"{100 * x:.0f}%"


def f_s(ms):
    return "-" if ms != ms else f"{ms / 1000:.2f} s"


def voice_table(rows):
    lines = ["| Group | n | WER | CER | Lang ID | Tool choice | Tool + args | Answer correct | V2V p50 | V2V p95 | STT p50 | LLM p50 | TTS first p50 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    summary = {}
    for name, f in GROUPS:
        g = [r for r in rows if f(r)]
        if not g:
            continue
        t = lambda k: [r["timings_ms"].get(k) for r in g]
        w = corpus_wer([r["reference"] for r in g], [r["transcript"] for r in g])
        c = corpus_cer([r["reference"] for r in g], [r["transcript"] for r in g])
        s = {"n": len(g), "wer": w, "cer": c, "lang_id": acc(g, "lang_ok"), "tool": acc(g, "tool_ok"),
             "tool_args": acc(g, "tool_args_ok"), "fact": acc(g, "fact_ok"),
             "v2v_p50_ms": pct(t("v2v_first_audio_ms"), 50), "v2v_p95_ms": pct(t("v2v_first_audio_ms"), 95),
             "stt_p50_ms": pct(t("stt_ms"), 50), "llm_p50_ms": pct(t("llm_ms"), 50),
             "llm_api_p50_ms": pct(t("llm_api_ms"), 50), "tts_first_p50_ms": pct(t("tts_first_ms"), 50),
             "stt_p95_ms": pct(t("stt_ms"), 95), "llm_p95_ms": pct(t("llm_ms"), 95)}
        summary[name.strip("*")] = s
        lines.append(f"| {name} | {s['n']} | {s['wer']:.3f} | {s['cer']:.3f} | {f_pct(s['lang_id'])} | {f_pct(s['tool'])} | "
                     f"{f_pct(s['tool_args'])} | {f_pct(s['fact'])} | {f_s(s['v2v_p50_ms'])} | {f_s(s['v2v_p95_ms'])} | "
                     f"{f_s(s['stt_p50_ms'])} | {f_s(s['llm_p50_ms'])} | {f_s(s['tts_first_p50_ms'])} |")
    return "\n".join(lines), summary


def text_table(rows):
    lines = ["| Group | n | Tool choice | Tool + args | Answer correct | LLM p50 | LLM p95 |", "|---|---|---|---|---|---|---|"]
    summary = {}
    for name, f in GROUPS[:4]:
        g = [r for r in rows if f(r)]
        if not g:
            continue
        llm = [r["timings_ms"].get("llm_ms") for r in g]
        s = {"n": len(g), "tool": acc(g, "tool_ok"), "tool_args": acc(g, "tool_args_ok"), "fact": acc(g, "fact_ok"),
             "llm_p50_ms": pct(llm, 50), "llm_p95_ms": pct(llm, 95)}
        summary[name.strip("*")] = s
        lines.append(f"| {name} | {s['n']} | {f_pct(s['tool'])} | {f_pct(s['tool_args'])} | {f_pct(s['fact'])} | "
                     f"{f_s(s['llm_p50_ms'])} | {f_s(s['llm_p95_ms'])} |")
    return "\n".join(lines), summary


def webrtc_table():
    files = sorted(glob.glob(os.path.join(ROOT, "evals", "results", "webrtc", "*.json")))
    recs = [json.load(open(f, encoding="utf-8")) for f in files]
    recs = [r for r in recs if r.get("client_v2v_ms")]
    if not recs:
        return None, None
    v = [r["client_v2v_ms"] for r in recs]
    srv = [r["turn"]["timings_ms"]["v2v_first_audio_ms"] for r in recs if r.get("turn")]
    s = {"n": len(recs), "client_v2v_p50_ms": pct(v, 50), "client_v2v_p95_ms": pct(v, 95),
         "server_v2v_p50_ms": pct(srv, 50), "files": [os.path.basename(f) for f in files]}
    t = ("| Path | n | V2V p50 | V2V p95 | server-side p50 (from VAD stop) |\n|---|---|---|---|---|\n"
         f"| Browser-equivalent WebRTC client (aiortc → Pipecat SmallWebRTC) | {s['n']} | {f_s(s['client_v2v_p50_ms'])} | "
         f"{f_s(s['client_v2v_p95_ms'])} | {f_s(s['server_v2v_p50_ms'])} |")
    return t, s


def main():
    out, summary = [], {}
    for tag, title in [("voice_claude_cli", "Voice run: Claude (claude-haiku-5-5 via claude CLI)"),
                       ("voice_anthropic", "Voice run: Claude via Anthropic API"),
                       ("voice_rules", "Voice run: offline rules router (no LLM)")]:
        rows = load(tag)
        if rows:
            t, s = voice_table(rows)
            changed = sum(1 for r in rows if r["fact_ok"] != r["fact_ok_at_run"])
            note = (f"Key-fact re-scored with the current checker: {changed} verdict(s) differ from the run-time score "
                    f"(run-time answer-correct, all 35: {sum(r['fact_ok_at_run'] for r in rows)}/{len(rows)}).")
            out += [f"### {title}", "", f"File: `evals/results/{tag}.jsonl`", "", t, "", note, ""]
            summary[tag] = s
    for tag, title in [("text_claude_cli", "Text-only (oracle transcripts = the script), Claude via CLI"),
                       ("transcripts_rules", "Rules router on the same Whisper transcripts as the Claude voice run"),
                       ("transcripts_rules_fuzzy", "Rules router + fuzzy keyword match (added AFTER seeing the row above: optimistic)")]:
        rows = load(tag)
        if rows:
            t, s = text_table(rows)
            out += [f"### {title}", "", f"File: `evals/results/{tag}.jsonl`", "", t, ""]
            summary[tag] = s
    t, s = webrtc_table()
    if t:
        out += ["### Voice-to-voice over WebRTC (client-measured)", "", t, ""]
        summary["webrtc"] = s
    md = "\n".join(out)
    open(os.path.join(RESULTS, "report.md"), "w", encoding="utf-8").write(md)
    json.dump(summary, open(os.path.join(RESULTS, "summary.json"), "w"), indent=2)
    print(md)


if __name__ == "__main__":
    main()
