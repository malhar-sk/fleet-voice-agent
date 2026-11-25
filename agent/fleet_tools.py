"""Fleet tools: PromQL/MetricsQL over VictoriaMetrics' HTTP API.

These are the only things the LLM can call. Each returns a small JSON-serialisable dict that is
easy to speak in two sentences. Offline semantics follow the fleet-health-monitor contract,
with a fixed 2-minute limit: a device is OFFLINE when its last `device_uptime_seconds` sample is
more than SILENT_AFTER_S (120 s) old.
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable

import httpx

VM_URL = os.environ.get("VM_URL", "http://127.0.0.1:18428").rstrip("/")
SILENT_AFTER_S = float(os.environ.get("SILENT_AFTER_S", "120"))
JOB = 'job="fleet-sim"'

METRICS = {
    "temperature": "device_temperature_celsius",
    "memory": "device_memory_utilization_percent",
    "cpu": "device_cpu_utilization_percent",
    "uptime": "device_uptime_seconds",
}
UNITS = {"temperature": "°C", "memory": "%", "cpu": "%", "uptime": "s"}
_METRIC_ALIASES = {
    "temp": "temperature", "temperature": "temperature", "cpu_temp": "temperature", "cpu temperature": "temperature",
    "device_temperature_celsius": "temperature", "heat": "temperature", "तापमान": "temperature",
    "mem": "memory", "memory": "memory", "ram": "memory", "device_memory_utilization_percent": "memory",
    "मेमरी": "memory", "मेमोरी": "memory",
    "cpu": "cpu", "load": "cpu", "cpu_usage": "cpu", "device_cpu_utilization_percent": "cpu",
    "uptime": "uptime", "device_uptime_seconds": "uptime",
}

# Number words that people say instead of digits, in English, Hindi and Marathi (Latin + Devanagari).
_NUM_WORDS = {
    "one": 1, "ek": 1, "एक": 1, "वन": 1,
    "two": 2, "do": 2, "don": 2, "दो": 2, "दोन": 2, "टू": 2,
    "three": 3, "teen": 3, "tin": 3, "तीन": 3, "थ्री": 3,
    "four": 4, "char": 4, "chaar": 4, "चार": 4, "फोर": 4, "फ़ोर": 4,
    "five": 5, "paanch": 5, "panch": 5, "pach": 5, "पांच": 5, "पाँच": 5, "पाच": 5, "फाइव": 5, "फाइव्ह": 5,
}
_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


class ToolError(Exception):
    pass


class VMClient:
    def __init__(self, base_url: str | None = None, timeout: float = 5.0, transport: httpx.BaseTransport | None = None):
        self.base_url = (base_url or VM_URL).rstrip("/")
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def query(self, expr: str) -> list[dict]:
        try:
            r = self._http.get(self.base_url + "/api/v1/query", params={"query": expr})
            r.raise_for_status()
            body = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ToolError(f"metrics backend unavailable: {e}") from e
        if body.get("status") != "success":
            raise ToolError(f"query failed: {body.get('error', body)}")
        return body["data"]["result"]

    def by_device(self, expr: str) -> dict[str, float]:
        out = {}
        for s in self.query(expr):
            dev = s["metric"].get("device_id")
            if dev is not None:
                out[dev] = float(s["value"][1])
        return out

    def scalar(self, expr: str) -> float | None:
        res = self.query(expr)
        if not res:
            return None
        return float(res[0]["value"][1])


_client: VMClient | None = None


def client() -> VMClient:
    global _client
    if _client is None:
        _client = VMClient()
    return _client


def set_client(c: VMClient | None) -> None:
    """Swap the VictoriaMetrics client (tests use a fake server)."""
    global _client
    _client = c


def normalize_device(name: str) -> str:
    """'pi-3', 'Pi 3', 'pi3', 'पाई ३', 'pi three', 'device 3' -> 'pi-3'."""
    if not name:
        raise ToolError("device name is empty")
    s = name.strip().lower().translate(_DEV_DIGITS)
    m = re.search(r"(\d+)", s)
    if m:
        return f"pi-{int(m.group(1))}"
    for word, n in _NUM_WORDS.items():
        if re.search(rf"(^|[\s\-_]){re.escape(word)}($|[\s\-_?.,])", s):
            return f"pi-{n}"
    raise ToolError(f"unknown device '{name}'")


def normalize_metric(metric: str) -> str:
    key = (metric or "").strip().lower()
    if key in _METRIC_ALIASES:
        return _METRIC_ALIASES[key]
    for alias, canon in _METRIC_ALIASES.items():
        if alias in key:
            return canon
    raise ToolError(f"unknown metric '{metric}'. Use one of: {', '.join(METRICS)}")


def _age_expr() -> str:
    return f"max by (device_id) (time() - tlast_over_time(device_uptime_seconds{{{JOB}}}[1d]))"


def _snapshot() -> dict[str, dict[str, Any]]:
    c = client()
    ages = c.by_device(_age_expr())
    temps = c.by_device(f"max by (device_id) (last_over_time(device_temperature_celsius{{{JOB}}}[1d]))")
    mems = c.by_device(f"max by (device_id) (last_over_time(device_memory_utilization_percent{{{JOB}}}[1d]))")
    cpus = c.by_device(f"max by (device_id) (last_over_time(device_cpu_utilization_percent{{{JOB}}}[1d]))")
    ups = c.by_device(f"max by (device_id) (last_over_time(device_uptime_seconds{{{JOB}}}[1d]))")
    out = {}
    for dev in sorted(ages, key=_dev_sort_key):
        age = ages[dev]
        online = age <= SILENT_AFTER_S
        out[dev] = {
            "device": dev,
            "status": "ONLINE" if online else "OFFLINE",
            "last_seen_seconds_ago": int(round(age)),
            "cpu_temperature_c": _r(temps.get(dev), 1),
            "memory_percent": _r(mems.get(dev), 1),
            "cpu_percent": _r(cpus.get(dev), 1),
            "uptime_seconds": int(ups[dev]) if dev in ups and online else None,
        }
    return out


def _r(v, nd):
    return None if v is None else round(v, nd)


def _dev_sort_key(d: str):
    m = re.search(r"(\d+)$", d)
    return (int(m.group(1)) if m else 0, d)


# ---------------------------------------------------------------- the tools

def list_devices() -> dict:
    """All known devices with ONLINE/OFFLINE status and their latest readings."""
    snap = _snapshot()
    online = [d for d, v in snap.items() if v["status"] == "ONLINE"]
    return {"total": len(snap), "online_count": len(online), "offline_count": len(snap) - len(online),
            "devices": list(snap.values())}


def list_offline_devices() -> dict:
    """Devices that have been silent for more than 2 minutes."""
    ages = client().by_device(_age_expr())
    off = [{"device": d, "silent_for_seconds": int(round(a)), "silent_for_minutes": round(a / 60, 1)}
           for d, a in sorted(ages.items(), key=lambda kv: _dev_sort_key(kv[0])) if a > SILENT_AFTER_S]
    return {"total_devices": len(ages), "offline_count": len(off), "offline": off,
            "offline_after_seconds": int(SILENT_AFTER_S)}


def device_status(name: str) -> dict:
    """Status and latest readings of one device."""
    dev = normalize_device(name)
    snap = _snapshot()
    if dev not in snap:
        raise ToolError(f"unknown device '{name}'. Known devices: {', '.join(snap) or 'none'}")
    return snap[dev]


def query_metric(device: str, metric: str, minutes: float = 10) -> dict:
    """Latest/min/avg/max of one metric for one device over the last N minutes."""
    dev = normalize_device(device)
    m = normalize_metric(metric)
    minutes = max(1, min(int(round(float(minutes or 10))), 24 * 60))
    series = f'{METRICS[m]}{{{JOB},device_id="{dev}"}}'
    c = client()
    vals = {}
    for fn in ("last", "min", "avg", "max"):
        vals[fn] = c.scalar(f"{fn}_over_time({series}[{minutes}m])")
    if all(v is None for v in vals.values()):
        known = c.by_device(_age_expr())
        if dev not in known:
            raise ToolError(f"unknown device '{device}'. Known devices: {', '.join(sorted(known, key=_dev_sort_key))}")
        return {"device": dev, "metric": m, "minutes": minutes, "unit": UNITS[m],
                "note": f"no samples in the last {minutes} minutes (device is silent)"}
    nd = 0 if m == "uptime" else 1
    return {"device": dev, "metric": m, "minutes": minutes, "unit": UNITS[m],
            "latest": _r(vals["last"], nd), "min": _r(vals["min"], nd),
            "avg": _r(vals["avg"], nd), "max": _r(vals["max"], nd)}


def sla_breaches(minutes: float = 5) -> dict:
    """Payment SLA breaches (MT103 ACK > 5 s), messages sent/acked and queue depth over N minutes."""
    minutes = max(1, min(int(round(float(minutes or 5))), 24 * 60))
    c = client()
    breaches = c.scalar(f"sum(increase(swift_sla_breaches_total[{minutes}m]))")
    sent = c.scalar(f"sum(increase(swift_messages_sent_total[{minutes}m]))")
    acked = c.scalar(f"sum(increase(swift_messages_acked_total[{minutes}m]))")
    queue = c.scalar("max(last_over_time(swift_queue_depth[5m]))")
    return {"minutes": minutes, "sla_breaches": int(round(breaches or 0)),
            "messages_sent": int(round(sent or 0)), "messages_acked": int(round(acked or 0)),
            "queue_depth": None if queue is None else int(queue)}


TOOL_FUNCS: dict[str, Callable[..., dict]] = {
    "list_devices": list_devices,
    "list_offline_devices": list_offline_devices,
    "device_status": device_status,
    "query_metric": query_metric,
    "sla_breaches": sla_breaches,
}

# Anthropic tool-use schemas (also rendered into the prompt for the CLI backend).
TOOL_SCHEMAS = [
    {"name": "list_devices",
     "description": "List every device in the fleet with ONLINE/OFFLINE status, CPU temperature, memory and uptime. Use for 'how many devices', 'how is the fleet', 'which devices are online'.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "list_offline_devices",
     "description": "List devices that are OFFLINE (silent for more than 2 minutes) and for how long. Use for 'which devices are offline/down'.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "device_status",
     "description": "Status and latest readings (temperature, memory, CPU, uptime, last seen) of one device, e.g. 'pi-3'.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string", "description": "device id like pi-3"}}, "required": ["name"]}},
    {"name": "query_metric",
     "description": "Latest/min/avg/max of one metric for one device over the last N minutes. metric is one of temperature, memory, cpu, uptime.",
     "input_schema": {"type": "object", "properties": {
         "device": {"type": "string", "description": "device id like pi-2"},
         "metric": {"type": "string", "enum": ["temperature", "memory", "cpu", "uptime"]},
         "minutes": {"type": "integer", "description": "look-back window in minutes, default 10"}},
         "required": ["device", "metric"]}},
    {"name": "sla_breaches",
     "description": "Payment-gateway SLA breaches (MT103 messages not acknowledged within 5 s), messages sent/acked and queue depth over the last N minutes.",
     "input_schema": {"type": "object", "properties": {"minutes": {"type": "integer", "description": "look-back window, default 5"}}, "required": []}},
]


def call_tool(name: str, args: dict | None = None) -> dict:
    """Run a tool by name; errors come back as {'error': ...} so the LLM can recover."""
    fn = TOOL_FUNCS.get(name)
    if fn is None:
        return {"error": f"unknown tool '{name}'"}
    args = dict(args or {})
    # be forgiving about argument names the model might use
    if name == "device_status" and "name" not in args:
        for k in ("device", "device_id", "id"):
            if k in args:
                args["name"] = args.pop(k)
    if name == "query_metric" and "device" not in args and "name" in args:
        args["device"] = args.pop("name")
    allowed = {"list_devices": set(), "list_offline_devices": set(), "device_status": {"name"},
               "query_metric": {"device", "metric", "minutes"}, "sla_breaches": {"minutes"}}[name]
    args = {k: v for k, v in args.items() if k in allowed}
    try:
        return fn(**args)
    except ToolError as e:
        return {"error": str(e)}
    except TypeError as e:
        return {"error": f"bad arguments for {name}: {e}"}
