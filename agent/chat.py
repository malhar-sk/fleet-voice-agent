"""Text-only agent CLI.

  python -m agent.chat "which devices are offline?"
  python -m agent.chat --backend rules "पाई 3 का तापमान क्या है?"
  python -m agent.chat --json "how many payment SLA breaches in the last 10 minutes?"
"""
from __future__ import annotations

import argparse
import json
import sys

from agent.agent import FleetAgent, make_backend


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ask the fleet agent a question (text only).")
    ap.add_argument("question", nargs="+")
    ap.add_argument("--backend", default=None, help="auto | anthropic | claude_cli | rules")
    ap.add_argument("--lang", default=None, help="en | hi | mr (default: detect from text)")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    a = ap.parse_args(argv)
    q = " ".join(a.question)
    agent = FleetAgent(make_backend(a.backend))
    r = agent.respond(q, a.lang)
    if a.json:
        print(json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
    else:
        for t in r.tool_calls:
            print(f"[tool] {t.tool}({json.dumps(t.args, ensure_ascii=False)}) -> {json.dumps(t.result, ensure_ascii=False)[:300]}",
                  file=sys.stderr)
        print(f"[{r.backend} · {r.lang} · llm {r.llm_ms:.0f} ms · total {r.total_ms:.0f} ms]", file=sys.stderr)
        print(r.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
