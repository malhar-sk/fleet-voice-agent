"""Voice eval: 30 questions (10 en / 10 hi / 10 mr) + 5 noisy variants, all SYNTHETIC SPEECH.

  python -m evals.run_eval                       # voice run with the default LLM backend (auto)
  python -m evals.run_eval --mode text           # oracle transcripts: the script text goes straight to the agent
  python -m evals.run_eval --backend rules --mode transcripts --from evals/results/voice_claude_cli.jsonl
  python -m evals.run_eval --limit 3 --no-scenario   # quick smoke test

Scenario (set unless --no-scenario; needs `docker compose up -d victoriametrics fleet-sim`):
random flapping off, every device recovered, pi-3 forced offline, 3 SLA breaches injected, then wait
until pi-3 has been silent > 120 s so it really counts as OFFLINE.

Per question we record transcript, detected language, tool calls (+results), answer and stage timings.
Ground truth for the key fact is fetched right after the answer by calling the EXPECTED tool with the
EXPECTED arguments (not the agent's own call), so wrong tool arguments can't look correct.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time

os.environ.setdefault("OMP_NUM_THREADS", "1")

from agent import fleet_tools as ft  # noqa: E402
from agent.agent import FleetAgent, make_backend  # noqa: E402
from evals.metrics import check_fact, cer, wer  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "evals", "results")
OFFLINE_DEVICE = "pi-3"
INJECT_BREACHES = 3


def load_questions(path="evals/questions.jsonl"):
    return [json.loads(l) for l in open(os.path.join(ROOT, path), encoding="utf-8") if l.strip()]


def chaos(*args):
    """Drive the simulator. Inside the voice-app container (no docker CLI) write the shared chaos file."""
    if os.environ.get("CHAOS_FILE") and shutil.which("docker") is None:
        from fleet_sim import chaos as chaos_mod
        chaos_mod.main(["--file", os.environ["CHAOS_FILE"], *args])
        return ""
    return subprocess.run(["docker", "compose", "exec", "-T", "fleet-sim", "python", "-m", "fleet_sim.chaos", *args],
                          cwd=ROOT, capture_output=True, text=True, check=True).stdout


def set_scenario():
    print("scenario: freezing random flapping, recovering all, forcing pi-3 offline, injecting 3 breaches")
    chaos("random", "off")
    chaos("recover", "all")
    time.sleep(12)  # every device reports again
    chaos("offline", OFFLINE_DEVICE, "--minutes", "90")
    chaos("breaches", str(INJECT_BREACHES))
    t0 = time.time()
    while time.time() - t0 < 300:
        st = ft.device_status(OFFLINE_DEVICE)
        if st["status"] == "OFFLINE":
            break
        time.sleep(5)
    off = ft.list_offline_devices()
    print(f"scenario ready after {time.time() - t0:.0f}s: offline={[o['device'] for o in off['offline']]}")
    return {"offline": [o["device"] for o in off["offline"]], "breaches_injected": INJECT_BREACHES,
            "set_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def truth_for(q):
    tool = q["expected_tool"]
    args = dict(q["expected_args"])
    if q["key_fact"] == "online_count":
        tool, args = "list_devices", {}
    if q["key_fact"] == "offline_list":
        tool, args = "list_offline_devices", {}
    if q["key_fact"] == "device_state":
        tool = "device_status"
    if q["key_fact"] == "metric_value":
        tool = "query_metric"
        args.setdefault("minutes", 10)
    return ft.call_tool(tool, args)


def score_tools(q, calls):
    names = [c["tool"] for c in calls]
    tool_ok = any(n in q["acceptable_tools"] for n in names)
    exp = q["expected_args"]
    args_ok = tool_ok
    if tool_ok and exp:
        want_dev = exp.get("name") or exp.get("device")
        want_metric = exp.get("metric")
        args_ok = False
        for c in calls:
            if c["tool"] not in q["acceptable_tools"]:
                continue
            a = c.get("args") or {}
            dev = a.get("name") or a.get("device")
            try:
                dev = ft.normalize_device(str(dev)) if dev else None
            except ft.ToolError:
                dev = None
            dev_ok = (want_dev is None) or dev == want_dev
            met = a.get("metric")
            try:
                met = ft.normalize_metric(met) if met else None
            except ft.ToolError:
                met = None
            met_ok = (want_metric is None) or c["tool"] != "query_metric" or met == want_metric
            if dev_ok and met_ok:
                args_ok = True
    return tool_ok, args_ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default=None, help="auto | claude_cli | anthropic | rules")
    ap.add_argument("--mode", default="voice", choices=["voice", "text", "transcripts"])
    ap.add_argument("--from", dest="from_file", default=None, help="for --mode transcripts: a voice results file")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--no-scenario", action="store_true")
    ap.add_argument("--use-cache", action="store_true", help="reuse cached LLM answers (latency then meaningless)")
    a = ap.parse_args()
    ft.set_client(ft.VMClient(os.environ.get("VM_URL", "http://127.0.0.1:18428")))

    qs = load_questions()
    if a.mode != "voice":
        qs = [q for q in qs if not q.get("noise")]     # noisy variants only matter for audio
    if a.limit:
        qs = qs[: a.limit]
    backend = make_backend(a.backend, use_cache=a.use_cache)
    agent = FleetAgent(backend)
    tag = a.tag or f"{a.mode}_{backend.name}"
    scenario = None if a.no_scenario else set_scenario()

    engine = None
    if a.mode == "voice":
        from voice.engine import VoiceEngine
        t = time.time()
        engine = VoiceEngine(agent=agent)
        print(f"models loaded in {time.time() - t:.1f}s")
        # warm-up (first ONNX/CT2 call is slower); not scored
        from voice.tts import read_wav
        x, sr = read_wav(os.path.join(ROOT, "evals/audio/dev/dev_en1.wav"))
        engine.stt.transcribe(x, sr)
    prior = {}
    if a.mode == "transcripts":
        prior = {r["id"]: r for r in (json.loads(l) for l in open(a.from_file, encoding="utf-8"))}

    os.makedirs(RESULTS, exist_ok=True)
    out_path = os.path.join(RESULTS, f"{tag}.jsonl")
    rows = []
    with open(out_path, "w", encoding="utf-8") as out:
        for i, q in enumerate(qs, 1):
            rec = {"id": q["id"], "lang": q["lang"], "noisy": bool(q.get("noise")), "reference": q["text"],
                   "expected_tool": q["expected_tool"], "key_fact": q["key_fact"], "backend": backend.name,
                   "mode": a.mode}
            if a.mode == "voice":
                from voice.tts import read_wav
                x, sr = read_wav(os.path.join(ROOT, q["audio"]))
                r = engine.turn_stream(x, sr)
                rec.update({"transcript": r.transcript, "detected_lang": r.lang, "whisper_lang": r.stt.get("whisper_lang"),
                            "lang_probs": r.stt.get("lang_probs"), "answer": r.answer,
                            "tool_calls": [{"tool": t["tool"], "args": t["args"], "result": t["result"]}
                                           for t in r.agent.get("tool_calls", [])],
                            "agent_backend": r.agent.get("backend"), "llm_cached": r.agent.get("cached"),
                            "timings_ms": r.timings_ms, "audio_s": r.stt.get("audio_s")})
                rec["wer"] = round(wer(q["text"], r.transcript), 4)
                rec["cer"] = round(cer(q["text"], r.transcript), 4)
            else:
                text = q["text"] if a.mode == "text" else prior[q["id"]]["transcript"]
                lang = q["lang"] if a.mode == "text" else prior[q["id"]]["detected_lang"]
                ar = agent.respond(text, lang)
                rec.update({"transcript": text, "detected_lang": lang, "answer": ar.answer,
                            "tool_calls": [{"tool": t.tool, "args": t.args, "result": t.result} for t in ar.tool_calls],
                            "agent_backend": ar.backend, "llm_cached": ar.cached,
                            "timings_ms": {"llm_ms": ar.llm_ms, "llm_api_ms": ar.llm_api_ms, "tools_ms": ar.tools_ms,
                                           "agent_ms": ar.total_ms}})
            truth = truth_for(q)
            rec["truth"] = truth
            rec["tool_ok"], rec["tool_args_ok"] = score_tools(q, rec["tool_calls"])
            rec["fact_ok"], rec["fact_note"] = check_fact(q["key_fact"], rec["answer"], truth) if "error" not in truth else (False, truth["error"])
            rec["lang_ok"] = rec["detected_lang"] == q["lang"]
            rec["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            rows.append(rec)
            tm = rec.get("timings_ms", {})
            print(f"[{i}/{len(qs)}] {q['id']:<10} lang {rec['detected_lang']}{'✓' if rec['lang_ok'] else '✗'} "
                  f"tool {'✓' if rec['tool_ok'] else '✗'} fact {'✓' if rec['fact_ok'] else '✗'} "
                  f"wer {rec.get('wer', '-')} v2v {tm.get('v2v_first_audio_ms', '-')} | {rec['transcript'][:50]!r} -> {rec['answer'][:70]!r}")
    meta = {"tag": tag, "mode": a.mode, "backend": backend.name, "model": getattr(backend, "model", ""),
            "n": len(rows), "scenario": scenario, "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "command": "python -m evals.run_eval " + " ".join(os.sys.argv[1:]),
            "stt": {"model": "faster-whisper small int8", "threads": int(os.environ.get("STT_THREADS", "1"))}}
    json.dump(meta, open(os.path.join(RESULTS, f"{tag}_meta.json"), "w"), indent=2)
    print("wrote", out_path)


if __name__ == "__main__":
    main()
