"""Tune the STT language policy on the DEV set only (evals/dev_questions.jsonl, disjoint from the eval set).

For each dev clip: Whisper's restricted language probabilities, and the transcript when decoding as
hi vs mr, with and without the domain prompt. Prints language accuracy + CER per policy.
  python -m evals.tune_stt
"""
import json
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

from agent.lang import resolve_lang  # noqa: E402
from evals.metrics import corpus_cer, corpus_wer  # noqa: E402
from voice import stt as stt_mod  # noqa: E402
from voice.tts import read_wav  # noqa: E402


def main():
    rows = [json.loads(l) for l in open("evals/dev_questions.jsonl", encoding="utf-8")]
    s = stt_mod.WhisperSTT()
    recs = []
    for r in rows:
        a, sr = read_wav(r["audio"])
        a = stt_mod.resample(a, sr, 16000)
        _, probs, _ = s.detect(a)
        rec = {"id": r["id"], "lang": r["lang"], "probs": probs, "text": r["text"], "hyp": {}}
        langs = ["en"] if r["lang"] == "en" else ["hi", "mr"]
        for lg in langs:
            for prompt in (False, True):
                stt_mod.USE_PROMPT = prompt
                res = s.transcribe(a, 16000, language=lg)
                rec["hyp"][f"{lg}|{int(prompt)}"] = res.text
        recs.append(rec)
        print(r["id"], probs, rec["hyp"])
    json.dump(recs, open("evals/results/dev_tuning_raw.json", "w"), ensure_ascii=False, indent=1)
    print("\npolicy                       lang_acc   CER(hi+mr)  WER(hi+mr)")
    for ratio in (1e9, 1.0, 0.5, 0.25, 0.0):
        for prompt in (0, 1):
            stt_mod.MR_RATIO = ratio
            ok, refs, hyps = 0, [], []
            for rec in recs:
                if rec["lang"] == "en":
                    continue
                wl = stt_mod.choose_lang(rec["probs"])
                wl = wl if wl in ("hi", "mr") else "hi"
                hyp = rec["hyp"][f"{wl}|{prompt}"]
                final = resolve_lang(wl, hyp)
                ok += final == rec["lang"]
                refs.append(rec["text"]); hyps.append(hyp)
            n = len(refs)
            label = f"mr_ratio={'argmax' if ratio > 1e8 else ratio} prompt={prompt}"
            print(f"{label:28} {ok}/{n}      {corpus_cer(refs, hyps):.3f}       {corpus_wer(refs, hyps):.3f}")


if __name__ == "__main__":
    main()
