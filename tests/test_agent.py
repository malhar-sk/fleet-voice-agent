import json
from types import SimpleNamespace

from agent.agent import AnthropicBackend, FleetAgent, MockBackend, RulesBackend, _extract_json, clean_spoken


def test_cli_protocol_two_steps(fake_vm):
    seen = []

    def fake_llm(system, prompt):
        seen.append((system, prompt))
        if "Step 1 of 2" in system:
            return '```json\n{"calls": [{"tool": "list_offline_devices", "args": {}}]}\n```'
        assert "Tool results" in prompt and "pi-3" in prompt
        return "pi 3 is offline; it has been silent for about 4 minutes."

    r = FleetAgent(MockBackend(fake_llm)).respond("which devices are offline?")
    assert r.lang == "en" and r.llm_rounds == 2
    assert [t.tool for t in r.tool_calls] == ["list_offline_devices"]
    assert r.tool_calls[0].result["offline_count"] == 1
    assert "pi 3" in r.answer
    assert "Reply in English" in seen[0][1]


def test_cli_protocol_no_tool_answer(fake_vm):
    r = FleetAgent(MockBackend(lambda s, p: '{"calls": [], "answer": "I only know about the fleet."}')).respond("tell me a joke")
    assert r.tool_calls == [] and r.answer == "I only know about the fleet." and r.llm_rounds == 1


def test_cli_language_hint_marathi(fake_vm):
    prompts = []

    def fake(system, prompt):
        prompts.append(prompt)
        return '{"calls": [{"tool": "sla_breaches", "args": {"minutes": 10}}]}' if "Step 1" in system else "गेल्या 10 मिनिटांत 8 उल्लंघने झाली."

    r = FleetAgent(MockBackend(fake)).respond("गेल्या 10 मिनिटांत किती पेमेंट उल्लंघने झाली?")
    assert r.lang == "mr" and "Reply in Marathi" in prompts[0]
    assert r.tool_calls[0].result["sla_breaches"] == 8


def test_fallback_to_rules_when_llm_fails(fake_vm):
    def boom(s, p):
        raise RuntimeError("no network")

    r = FleetAgent(MockBackend(boom)).respond("which devices are offline?")
    assert r.backend.startswith("rules (fallback") and "pi 3" in r.answer


def test_rules_backend(fake_vm):
    r = RulesBackend().respond("पाई 3 का तापमान क्या है?", "hi")
    assert r.tool_calls[0].tool == "query_metric" and "51" in r.answer


class _FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            assert {t["name"] for t in kw["tools"]} >= {"device_status", "sla_breaches"}
            return SimpleNamespace(content=[
                SimpleNamespace(type="text", text="Checking."),
                SimpleNamespace(type="tool_use", id="tu_1", name="device_status", input={"name": "pi-5"})])
        tool_result = kw["messages"][-1]["content"][0]
        assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "tu_1"
        assert json.loads(tool_result["content"])["device"] == "pi-5"
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="**pi 5** is online at about 58 degrees.")])


def test_anthropic_native_tool_use(fake_vm):
    client = SimpleNamespace(messages=_FakeMessages())
    r = AnthropicBackend(model="claude-haiku-5-5", client=client).respond("how is pi 5?", "en")
    assert r.llm_rounds == 2 and r.tool_calls[0].tool == "device_status"
    assert r.answer == "pi 5 is online at about 58 degrees."


def test_extract_json_and_clean():
    assert _extract_json('sure: {"calls": []} done') == {"calls": []}
    assert clean_spoken('  "**Hello**  `x`" ') == "Hello x"
