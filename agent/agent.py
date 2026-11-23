"""The fleet agent: question (+ language) -> tool calls -> short spoken answer.

LLM backends (LLM_BACKEND env var):
  anthropic   Claude via the Anthropic SDK with native tool use (needs ANTHROPIC_API_KEY)
  claude_cli  Claude via a logged-in `claude -p` CLI (the build host has no API key). It has no
              native tool use here, so tool calling is a 2-step JSON protocol: plan -> run tools -> answer.
  rules       offline keyword router + templates (no LLM at all), so the demo works without keys
  mock        scripted responses for tests
  auto        anthropic if a key is set, else claude_cli if `claude` is on PATH, else rules
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from agent import prompts, rules
from agent.fleet_tools import TOOL_SCHEMAS, call_tool
from agent.lang import detect_text_lang

DEFAULT_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-5-5")
CACHE_DIR = Path(os.environ.get("LLM_CACHE_DIR", Path(__file__).resolve().parents[1] / ".cache" / "llm"))


@dataclass
class ToolCall:
    tool: str
    args: dict
    result: dict
    ms: float


@dataclass
class AgentResult:
    question: str
    lang: str
    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    llm_ms: float = 0.0          # time spent waiting on the LLM (all rounds)
    tools_ms: float = 0.0        # time spent in tool calls (VictoriaMetrics queries)
    total_ms: float = 0.0
    backend: str = ""
    model: str = ""
    llm_rounds: int = 0
    cached: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _run_tools(calls: list[dict]) -> tuple[list[ToolCall], float]:
    out, total = [], 0.0
    for c in calls[:4]:
        name = c.get("tool") or c.get("name")
        args = c.get("args") or c.get("input") or {}
        t0 = time.perf_counter()
        res = call_tool(name, args)
        ms = (time.perf_counter() - t0) * 1000
        total += ms
        out.append(ToolCall(tool=name, args=args, result=res, ms=round(ms, 1)))
    return out, total


def clean_spoken(text: str) -> str:
    """Strip markdown/symbols the TTS would read badly."""
    text = re.sub(r"[*_`#>|]+", "", text or "")
    text = re.sub(r"\s+", " ", text).strip().strip('"').strip()
    return text


# ----------------------------------------------------------------- backends

class Backend:
    name = "base"
    model = ""

    def respond(self, question: str, lang: str) -> AgentResult:  # pragma: no cover
        raise NotImplementedError


class RulesBackend(Backend):
    name = "rules"
    model = "keyword-router"

    def respond(self, question, lang):
        t0 = time.perf_counter()
        calls = rules.plan(question)
        tcs, tools_ms = _run_tools(calls)
        ans = rules.answer([{"tool": t.tool, "result": t.result} for t in tcs], lang)
        total = (time.perf_counter() - t0) * 1000
        return AgentResult(question, lang, ans, tcs, llm_ms=round(total - tools_ms, 1), tools_ms=round(tools_ms, 1),
                           total_ms=round(total, 1), backend=self.name, model=self.model, llm_rounds=0)


def _extract_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON in LLM output: {text[:200]}")
    return json.loads(m.group(0))


class CompletionBackend(Backend):
    """Shared 2-step JSON tool protocol for backends that only do plain completions."""

    def __init__(self, model: str = DEFAULT_MODEL, use_cache: bool = False):
        self.model = model
        self.use_cache = use_cache
        self.last_cached = False

    def complete(self, system: str, prompt: str) -> str:  # pragma: no cover
        raise NotImplementedError

    def _cached_complete(self, system: str, prompt: str) -> tuple[str, bool]:
        key = hashlib.sha256(f"{self.name}|{self.model}|{system}|{prompt}".encode()).hexdigest()
        path = CACHE_DIR / f"{key}.json"
        if self.use_cache and path.exists():
            return json.loads(path.read_text())["text"], True
        text = self.complete(system, prompt)
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"model": self.model, "text": text}, ensure_ascii=False))
        except OSError:
            pass
        return text, False

    def respond(self, question, lang):
        t0 = time.perf_counter()
        llm_ms, cached_any = 0.0, False
        a = time.perf_counter()
        raw, c1 = self._cached_complete(prompts.cli_plan_system(), prompts.user_turn(question, lang))
        llm_ms += (time.perf_counter() - a) * 1000
        rounds = 1
        try:
            plan = _extract_json(raw)
        except (ValueError, json.JSONDecodeError):
            plan = {"calls": [], "answer": raw}
        calls = plan.get("calls") or []
        tcs, tools_ms = _run_tools(calls)
        if not tcs:
            ans = plan.get("answer") or rules.T["unknown"][lang if lang in rules.T["unknown"] else "en"]
            cached_any = c1
        else:
            a = time.perf_counter()
            ans, c2 = self._cached_complete(prompts.cli_answer_system(), prompts.answer_turn(
                question, lang, [{"tool": t.tool, "args": t.args, "result": t.result} for t in tcs]))
            llm_ms += (time.perf_counter() - a) * 1000
            rounds += 1
            cached_any = c1 or c2
        total = (time.perf_counter() - t0) * 1000
        return AgentResult(question, lang, clean_spoken(ans), tcs, llm_ms=round(llm_ms, 1), tools_ms=round(tools_ms, 1),
                           total_ms=round(total, 1), backend=self.name, model=self.model, llm_rounds=rounds,
                           cached=cached_any)


class ClaudeCLIBackend(CompletionBackend):
    name = "claude_cli"

    def complete(self, system, prompt):
        cmd = ["claude", "-p", "--model", self.model, "--output-format", "json", "--tools", "",
               "--system-prompt", system, "--setting-sources", "", "--strict-mcp-config",
               "--no-session-persistence", prompt]
        with tempfile.TemporaryDirectory() as d:  # empty cwd: no project files leak into the prompt
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=90, cwd=d)
        if p.returncode != 0:
            raise RuntimeError(f"claude CLI failed ({p.returncode}): {p.stderr[-300:] or p.stdout[-300:]}")
        out = json.loads(p.stdout)
        if out.get("is_error"):
            raise RuntimeError(f"claude CLI error: {out.get('result')}")
        return out.get("result", "")


class AnthropicBackend(Backend):
    """Native tool use with the Anthropic Messages API."""
    name = "anthropic"

    def __init__(self, model: str = DEFAULT_MODEL, client=None, max_rounds: int = 3):
        self.model = model
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client = client
        self.max_rounds = max_rounds

    def respond(self, question, lang):
        t0 = time.perf_counter()
        messages = [{"role": "user", "content": prompts.user_turn(question, lang)}]
        tcs: list[ToolCall] = []
        llm_ms = tools_ms = 0.0
        answer, rounds = "", 0
        for _ in range(self.max_rounds):
            a = time.perf_counter()
            resp = self.client.messages.create(model=self.model, max_tokens=300, system=prompts.SYSTEM_PROMPT,
                                               tools=TOOL_SCHEMAS, messages=messages)
            llm_ms += (time.perf_counter() - a) * 1000
            rounds += 1
            uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            text = " ".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
            if not uses:
                answer = text
                break
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for u in uses:
                new, ms = _run_tools([{"tool": u.name, "args": dict(u.input or {})}])
                tools_ms += ms
                tcs.extend(new)
                results.append({"type": "tool_result", "tool_use_id": u.id,
                                "content": json.dumps(new[0].result, ensure_ascii=False)})
            messages.append({"role": "user", "content": results})
        total = (time.perf_counter() - t0) * 1000
        return AgentResult(question, lang, clean_spoken(answer), tcs, llm_ms=round(llm_ms, 1), tools_ms=round(tools_ms, 1),
                           total_ms=round(total, 1), backend=self.name, model=self.model, llm_rounds=rounds)


class MockBackend(CompletionBackend):
    """Tests: a function maps (system, prompt) -> text."""
    name = "mock"

    def __init__(self, fn: Callable[[str, str], str]):
        super().__init__(model="mock")
        self.fn = fn

    def complete(self, system, prompt):
        return self.fn(system, prompt)


def pick_backend_name(name: str | None = None) -> str:
    name = (name or os.environ.get("LLM_BACKEND", "auto")).lower()
    if name != "auto":
        return name
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if shutil.which("claude"):
        return "claude_cli"
    return "rules"


def make_backend(name: str | None = None, model: str | None = None, use_cache: bool = False) -> Backend:
    name = pick_backend_name(name)
    model = model or DEFAULT_MODEL
    if name == "anthropic":
        return AnthropicBackend(model=model)
    if name == "claude_cli":
        return ClaudeCLIBackend(model=model, use_cache=use_cache)
    if name == "rules":
        return RulesBackend()
    raise ValueError(f"unknown LLM backend '{name}'")


class FleetAgent:
    def __init__(self, backend: Backend | None = None, fallback: Backend | None = None):
        self.backend = backend or make_backend()
        self.fallback = fallback if fallback is not None else (RulesBackend() if self.backend.name != "rules" else None)

    def respond(self, question: str, lang: str | None = None) -> AgentResult:
        lang = lang or detect_text_lang(question)
        try:
            return self.backend.respond(question, lang)
        except Exception as e:  # LLM down / quota / CLI missing: keep the voice loop alive
            if self.fallback is None:
                raise
            r = self.fallback.respond(question, lang)
            r.backend = f"{r.backend} (fallback: {type(e).__name__}: {str(e)[:120]})"
            return r
