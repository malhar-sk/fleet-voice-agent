"""Live tests: start VictoriaMetrics + fleet-sim with Docker Compose and query the real stack.

  make test-live      (or: pytest -m live)
"""
import os
import subprocess
import time

import httpx
import pytest

from agent import fleet_tools as ft

pytestmark = pytest.mark.live
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VM = os.environ.get("VM_URL", "http://127.0.0.1:18428")


def _compose(*args, check=True):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, check=check, capture_output=True, text=True)


@pytest.fixture(scope="module")
def stack():
    _compose("up", "-d", "--build", "victoriametrics", "fleet-sim")
    _compose("exec", "-T", "fleet-sim", "python", "-m", "fleet_sim.chaos", "random", "off")
    _compose("exec", "-T", "fleet-sim", "python", "-m", "fleet_sim.chaos", "recover", "all")
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            r = httpx.get(VM + "/api/v1/query", params={"query": 'count(device_uptime_seconds{job="fleet-sim"})'}, timeout=3)
            res = r.json()["data"]["result"]
            if res and float(res[0]["value"][1]) >= 5:
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        pytest.fail("fleet-sim data never reached VictoriaMetrics")
    ft.set_client(ft.VMClient(VM))
    yield
    _compose("exec", "-T", "fleet-sim", "python", "-m", "fleet_sim.chaos", "recover", "all", check=False)
    _compose("exec", "-T", "fleet-sim", "python", "-m", "fleet_sim.chaos", "random", "on", check=False)
    ft.set_client(None)


def test_five_devices_reporting(stack):
    r = ft.list_devices()
    assert r["total"] == 5
    assert {d["device"] for d in r["devices"]} == {f"pi-{i}" for i in range(1, 6)}
    for d in r["devices"]:
        if d["status"] == "ONLINE":
            assert 30 < d["cpu_temperature_c"] < 90 and 0 <= d["memory_percent"] <= 100


def test_query_metric_live(stack):
    r = ft.query_metric("pi-1", "temperature", 5)
    assert r["unit"] == "°C" and r["min"] <= r["avg"] <= r["max"]


def test_sla_breaches_live(stack):
    _compose("exec", "-T", "fleet-sim", "python", "-m", "fleet_sim.chaos", "breaches", "3")
    time.sleep(12)
    r = ft.sla_breaches(5)
    assert r["messages_sent"] > 0
    assert r["sla_breaches"] >= 3


def test_chaos_makes_device_offline(stack, monkeypatch):
    # The real limit is 120 s; shorten it for the test so we don't wait 2 minutes.
    monkeypatch.setattr(ft, "SILENT_AFTER_S", 15.0)
    _compose("exec", "-T", "fleet-sim", "python", "-m", "fleet_sim.chaos", "offline", "pi-4", "--minutes", "2")
    time.sleep(25)
    off = ft.list_offline_devices()
    assert "pi-4" in [o["device"] for o in off["offline"]]
    assert ft.device_status("pi-4")["status"] == "OFFLINE"
    _compose("exec", "-T", "fleet-sim", "python", "-m", "fleet_sim.chaos", "recover", "pi-4")
    time.sleep(12)
    assert ft.device_status("pi-4")["status"] == "ONLINE"
