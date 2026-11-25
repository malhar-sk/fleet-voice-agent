"""Fleet simulator: 5 fake devices (pi-1..pi-5) and a payment-SLA feed.

ALL DATA IS SYNTHETIC. Nothing here talks to real hardware.

Every PUSH_INTERVAL seconds the simulator writes Prometheus text-format samples to
VictoriaMetrics' /api/v1/import/prometheus endpoint (no timestamp = "now").

Device metrics reuse the names from the fleet-health-monitor contract
(device_uptime_seconds is the liveness metric; a silent device pushes nothing):
  device_cpu_utilization_percent, device_memory_utilization_percent,
  device_temperature_celsius, device_uptime_seconds,
  device_report_interval_seconds, device_heartbeat_timestamp_seconds

Payment-SLA metrics reuse the swift-mt103-monitor names (OTel dots -> Prometheus underscores):
  swift_messages_sent_total, swift_messages_acked_total, swift_messages_dropped_total,
  swift_sla_breaches_total, swift_queue_depth

Chaos / control lives in a small JSON file (CHAOS_FILE), written by `python -m fleet_sim.chaos`:
  {"forced_offline": {"pi-3": <until_epoch>}, "random": true, "inject_breaches": 0}
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
import signal
import time
import urllib.request

log = logging.getLogger("fleet-sim")

VM_URL = os.environ.get("VM_URL", "http://victoriametrics:8428").rstrip("/")
PUSH_INTERVAL = float(os.environ.get("PUSH_INTERVAL", "5"))
DEVICES = [d.strip() for d in os.environ.get("DEVICES", "pi-1,pi-2,pi-3,pi-4,pi-5").split(",") if d.strip()]
CHAOS_FILE = os.environ.get("CHAOS_FILE", "/state/chaos.json")
# Random flapping: probability per device per minute of dropping off, and how long it stays off.
FLAP_PROB_PER_MIN = float(os.environ.get("FLAP_PROB_PER_MIN", "0.01"))
FLAP_MIN_SECS = float(os.environ.get("FLAP_MIN_SECS", "60"))
FLAP_MAX_SECS = float(os.environ.get("FLAP_MAX_SECS", "300"))
# Payment feed
MSGS_PER_MIN = float(os.environ.get("MSGS_PER_MIN", "120"))
BREACH_BURST_PROB_PER_MIN = float(os.environ.get("BREACH_BURST_PROB_PER_MIN", "0.05"))
SEED = os.environ.get("SIM_SEED")


def read_chaos(path: str = CHAOS_FILE) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


class Device:
    def __init__(self, name: str, rng: random.Random):
        self.name = name
        self.rng = rng
        idx = int(name.split("-")[-1]) if name.split("-")[-1].isdigit() else 1
        self.base_temp = 42.0 + 3.0 * idx          # pi-1 runs cool, pi-5 runs warm
        self.base_mem = 30.0 + 7.0 * idx
        self.boot_time = time.time() - rng.uniform(2, 30) * 3600
        self.random_off_until = 0.0
        self.was_offline = False

    def online(self, now: float, chaos: dict) -> bool:
        forced = (chaos.get("forced_offline") or {}).get(self.name)
        if forced and float(forced) > now:
            return False
        if chaos.get("random", True):
            if now < self.random_off_until:
                return False
            p_tick = FLAP_PROB_PER_MIN * PUSH_INTERVAL / 60.0
            if self.rng.random() < p_tick:
                self.random_off_until = now + self.rng.uniform(FLAP_MIN_SECS, FLAP_MAX_SECS)
                log.info("%s randomly going offline until %s", self.name, time.ctime(self.random_off_until))
                return False
        else:
            self.random_off_until = 0.0
        return True

    def sample(self, now: float) -> dict[str, float]:
        if self.was_offline:
            # Coming back from a silence counts as a reboot: uptime restarts.
            self.boot_time = now - self.rng.uniform(5, 20)
            self.was_offline = False
        wobble = math.sin(now / 300.0 + hash(self.name) % 7)
        return {
            "device_cpu_utilization_percent": max(0.0, min(100.0, 18 + 12 * wobble + self.rng.gauss(0, 4))),
            "device_memory_utilization_percent": max(0.0, min(100.0, self.base_mem + 4 * wobble + self.rng.gauss(0, 1))),
            "device_temperature_celsius": round(self.base_temp + 5 * wobble + self.rng.gauss(0, 0.5), 1),
            "device_uptime_seconds": round(now - self.boot_time, 0),
            "device_report_interval_seconds": PUSH_INTERVAL,
            "device_heartbeat_timestamp_seconds": round(now, 0),
        }


class PaymentFeed:
    """Simulated MT103 payment gateway counters (synthetic)."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.sent = self.acked = self.dropped = self.breaches = 0
        self.queue = 0
        self.burst_left = 0

    def step(self, chaos: dict, injected_new: int) -> dict[str, float]:
        n = _poisson(self.rng, MSGS_PER_MIN * PUSH_INTERVAL / 60.0)
        self.sent += n
        if chaos.get("random", True) and self.burst_left == 0 and self.rng.random() < BREACH_BURST_PROB_PER_MIN * PUSH_INTERVAL / 60.0:
            self.burst_left = self.rng.randint(1, 4)   # a few ticks of slow ACKs
        new_breaches = injected_new
        if self.burst_left > 0:
            new_breaches += self.rng.randint(1, 3)
            self.burst_left -= 1
        dropped = 1 if self.rng.random() < 0.02 else 0
        self.breaches += new_breaches
        self.dropped += dropped
        self.acked += max(0, n - dropped)
        self.queue = max(0, int(self.rng.gauss(2 + 6 * new_breaches, 1)))
        return {
            "swift_messages_sent_total": self.sent,
            "swift_messages_acked_total": self.acked,
            "swift_messages_dropped_total": self.dropped,
            "swift_sla_breaches_total": self.breaches,
            "swift_queue_depth": self.queue,
        }


def _poisson(rng: random.Random, lam: float) -> int:
    l, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1


def render(devices_samples: dict[str, dict[str, float]], payments: dict[str, float]) -> str:
    lines = []
    for dev, metrics in devices_samples.items():
        for m, v in metrics.items():
            lines.append(f'{m}{{device_id="{dev}",hostname="{dev}",job="fleet-sim"}} {v}')
    for m, v in payments.items():
        lines.append(f'{m}{{gateway="mt103-gw",job="payment-sim"}} {v}')
    return "\n".join(lines) + "\n"


def push(body: str) -> None:
    req = urllib.request.Request(VM_URL + "/api/v1/import/prometheus", data=body.encode(), method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        r.read()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rng = random.Random(int(SEED)) if SEED else random.Random()
    devices = [Device(d, rng) for d in DEVICES]
    feed = PaymentFeed(rng)
    # injections are a running total in the chaos file; only new ones count after a (re)start
    consumed_injections = int(read_chaos().get("inject_breaches", 0))
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("fleet-sim: %d devices -> %s every %.0fs (synthetic data)", len(devices), VM_URL, PUSH_INTERVAL)
    prev_state: dict[str, bool] = {}
    while running:
        now = time.time()
        chaos = read_chaos()
        samples = {}
        for d in devices:
            up = d.online(now, chaos)
            if prev_state.get(d.name) is not None and prev_state[d.name] != up:
                log.info("%s is now %s", d.name, "ONLINE" if up else "OFFLINE (silent)")
            prev_state[d.name] = up
            if up:
                samples[d.name] = d.sample(now)
            else:
                d.was_offline = True
        injected_total = int(chaos.get("inject_breaches", 0))
        new_inj = max(0, injected_total - consumed_injections)
        consumed_injections = max(consumed_injections, injected_total)
        payments = feed.step(chaos, new_inj)
        try:
            push(render(samples, payments))
        except Exception as e:  # keep running if VM is briefly down
            log.warning("push failed: %s", e)
        time.sleep(max(0.0, PUSH_INTERVAL - (time.time() - now)))


if __name__ == "__main__":
    main()
