"""A fake VictoriaMetrics: a real HTTP server on 127.0.0.1 that answers /api/v1/query.

It does not parse PromQL; it recognises the handful of expression shapes fleet_tools uses and
answers them from a fixture fleet state. Used by CI (no Docker).
"""
from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DEFAULT_STATE = {
    "devices": {
        "pi-1": {"age": 2, "temp": 45.2, "mem": 37.1, "cpu": 12.0, "uptime": 86400},
        "pi-2": {"age": 3, "temp": 48.9, "mem": 44.0, "cpu": 22.5, "uptime": 7200},
        "pi-3": {"age": 245, "temp": 51.3, "mem": 51.0, "cpu": 30.1, "uptime": 3600},
        "pi-4": {"age": 1, "temp": 54.0, "mem": 58.2, "cpu": 18.0, "uptime": 600},
        "pi-5": {"age": 4, "temp": 57.6, "mem": 65.0, "cpu": 40.0, "uptime": 120000},
    },
    "sla": {"breaches_per_min": 0.8, "sent_per_min": 120, "acked_per_min": 119, "queue": 3},
}

_METRIC_KEY = {
    "device_temperature_celsius": "temp", "device_memory_utilization_percent": "mem",
    "device_cpu_utilization_percent": "cpu", "device_uptime_seconds": "uptime",
}


class FakeVM:
    def __init__(self, state: dict | None = None):
        self.state = json.loads(json.dumps(state or DEFAULT_STATE))
        self.queries: list[str] = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                u = urlparse(self.path)
                if u.path != "/api/v1/query":
                    self.send_response(404); self.end_headers(); return
                expr = parse_qs(u.query).get("query", [""])[0]
                fake.queries.append(expr)
                try:
                    result = fake.evaluate(expr)
                    body = {"status": "success", "data": {"resultType": "vector", "result": result}}
                    code = 200
                except ValueError as e:
                    body, code = {"status": "error", "error": str(e)}, 400
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()

    # ------------------------------------------------------------------
    def _vec(self, items):
        now = time.time()
        return [{"metric": m, "value": [now, str(v)]} for m, v in items]

    def evaluate(self, expr: str):
        devs = self.state["devices"]
        sla = self.state["sla"]
        if "tlast_over_time(device_uptime_seconds" in expr:
            return self._vec([({"device_id": d}, v["age"]) for d, v in devs.items()])
        m = re.match(r"max by \(device_id\) \(last_over_time\((\w+)\{", expr)
        if m:
            key = _METRIC_KEY[m.group(1)]
            return self._vec([({"device_id": d}, v[key]) for d, v in devs.items() if v["age"] <= 120 or key != "uptime"])
        m = re.match(r'(last|min|avg|max)_over_time\((\w+)\{job="fleet-sim",device_id="([^"]+)"\}\[(\d+)m\]\)', expr)
        if m:
            fn, metric, dev, minutes = m.group(1), m.group(2), m.group(3), int(m.group(4))
            d = devs.get(dev)
            if d is None or d["age"] > minutes * 60:
                return []
            base = d[_METRIC_KEY[metric]]
            delta = {"last": 0, "min": -1.0, "avg": -0.2, "max": 1.5}[fn]
            return self._vec([({}, base + delta)])
        m = re.match(r"sum\(increase\((swift_\w+)\[(\d+)m\]\)\)", expr)
        if m:
            per_min = {"swift_sla_breaches_total": sla["breaches_per_min"], "swift_messages_sent_total": sla["sent_per_min"],
                       "swift_messages_acked_total": sla["acked_per_min"]}[m.group(1)]
            return self._vec([({}, per_min * int(m.group(2)))])
        if "swift_queue_depth" in expr:
            return self._vec([({}, sla["queue"])])
        raise ValueError(f"FakeVM cannot evaluate: {expr}")
