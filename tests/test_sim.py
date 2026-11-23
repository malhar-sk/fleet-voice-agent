import json
import random

from fleet_sim import chaos, sim


def test_render_has_contract_metric_names():
    d = sim.Device("pi-2", random.Random(1))
    feed = sim.PaymentFeed(random.Random(1))
    body = sim.render({"pi-2": d.sample(1_000_000.0)}, feed.step({}, 0))
    for name in ("device_uptime_seconds", "device_temperature_celsius", "device_memory_utilization_percent",
                 "device_heartbeat_timestamp_seconds", "swift_sla_breaches_total", "swift_queue_depth"):
        assert name in body
    assert 'device_id="pi-2"' in body and 'job="fleet-sim"' in body


def test_forced_offline_and_random_off(tmp_path):
    f = tmp_path / "chaos.json"
    chaos.main(["--file", str(f), "offline", "pi-3", "--minutes", "5"])
    chaos.main(["--file", str(f), "random", "off"])
    data = json.loads(f.read_text())
    assert data["random"] is False
    d3, d1 = sim.Device("pi-3", random.Random(0)), sim.Device("pi-1", random.Random(0))
    import time
    now = time.time()
    assert d3.online(now, data) is False
    assert d1.online(now, data) is True
    chaos.main(["--file", str(f), "recover", "pi-3"])
    assert d3.online(now, json.loads(f.read_text())) is True


def test_injected_breaches_counted():
    feed = sim.PaymentFeed(random.Random(3))
    out = feed.step({"random": False}, 4)
    assert out["swift_sla_breaches_total"] == 4
    assert out["swift_messages_sent_total"] >= out["swift_messages_acked_total"]
