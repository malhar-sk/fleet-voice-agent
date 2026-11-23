"""Prompts for the fleet voice agent."""
from __future__ import annotations

import json

from agent.fleet_tools import TOOL_SCHEMAS
from agent.lang import LANG_NAMES

SYSTEM_PROMPT = """You are the voice assistant for a small simulated device fleet (Raspberry Pis named pi-1 to pi-5) and a simulated payment gateway. This is a demonstration system, not a clinical or safety system.

Rules for every answer:
- Your answer is spoken aloud, so use at most 2 short sentences. No lists, markdown, emojis or symbols.
- Always get facts from the tools; never invent device names or numbers.
- Say numbers naturally: round them (about 55 degrees, not 55.37), say durations in minutes rather than seconds, and write numbers as digits so the speech engine can read them.
- Say device names like "pi 3".
- Answer in the user's language (English, Hindi or Marathi). For Hindi and Marathi use Devanagari script; device names can stay as "pi 3".
- A device is OFFLINE when it has been silent for more than 2 minutes.
- If the question is not about the fleet or the payment gateway, say briefly that you can only answer questions about the device fleet."""


def tool_catalog() -> str:
    lines = []
    for t in TOOL_SCHEMAS:
        props = t["input_schema"].get("properties", {})
        args = ", ".join(f"{k}: {v.get('type')}" + (f" (one of {v['enum']})" if "enum" in v else "")
                         for k, v in props.items())
        lines.append(f"- {t['name']}({args}): {t['description']}")
    return "\n".join(lines)


def cli_plan_system() -> str:
    return (SYSTEM_PROMPT + "\n\nYou can call these tools:\n" + tool_catalog() + """

Step 1 of 2: decide which tool calls are needed to answer the user's question.
Reply with ONLY a JSON object, no prose, in this exact shape:
{"calls": [{"tool": "<tool name>", "args": {...}}]}
Use one call when one is enough; use several only for compound questions. If no tool applies, reply {"calls": [], "answer": "<your spoken answer>"}.""")


def cli_answer_system() -> str:
    return (SYSTEM_PROMPT + """

Step 2 of 2: you are given the user's question and the tool results. Reply with ONLY the spoken answer text (at most 2 short sentences, in the requested language). No JSON, no quotes, no preamble.""")


def user_turn(question: str, lang: str) -> str:
    return f"[The user spoke {LANG_NAMES.get(lang, 'English')}. Reply in {LANG_NAMES.get(lang, 'English')}.]\n{question}"


def answer_turn(question: str, lang: str, results: list[dict]) -> str:
    return (user_turn(question, lang) + "\n\nTool results:\n" +
            json.dumps(results, ensure_ascii=False))
