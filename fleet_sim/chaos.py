"""Chaos control for the fleet simulator (edits the shared chaos JSON file).

  python -m fleet_sim.chaos offline pi-3 --minutes 10   # force pi-3 silent for 10 min
  python -m fleet_sim.chaos recover pi-3                # bring it back now
  python -m fleet_sim.chaos recover all
  python -m fleet_sim.chaos random off|on               # freeze / resume random flapping and breach bursts
  python -m fleet_sim.chaos breaches 5                  # inject 5 SLA breaches on the next tick
  python -m fleet_sim.chaos show
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time

from fleet_sim.sim import CHAOS_FILE, read_chaos


def write_chaos(data: dict, path: str = CHAOS_FILE) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(tmp, 0o666)
    os.replace(tmp, path)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", default=CHAOS_FILE)
    sub = p.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("offline"); o.add_argument("device"); o.add_argument("--minutes", type=float, default=10)
    r = sub.add_parser("recover"); r.add_argument("device")
    rnd = sub.add_parser("random"); rnd.add_argument("state", choices=["on", "off"])
    b = sub.add_parser("breaches"); b.add_argument("count", type=int)
    sub.add_parser("show")
    a = p.parse_args(argv)
    data = read_chaos(a.file)
    data.setdefault("forced_offline", {})
    if a.cmd == "offline":
        data["forced_offline"][a.device] = time.time() + a.minutes * 60
        print(f"{a.device} forced OFFLINE for {a.minutes:g} min")
    elif a.cmd == "recover":
        if a.device == "all":
            data["forced_offline"] = {}
        else:
            data["forced_offline"].pop(a.device, None)
        print(f"{a.device} recovered")
    elif a.cmd == "random":
        data["random"] = a.state == "on"
        print(f"random flapping {a.state}")
    elif a.cmd == "breaches":
        data["inject_breaches"] = int(data.get("inject_breaches", 0)) + a.count
        print(f"injecting {a.count} SLA breaches")
    write_chaos(data, a.file)
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
