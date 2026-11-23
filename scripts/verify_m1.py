"""M1 check: ask Grafana (through its datasource proxy) for each device's status, plus the alert state.

  python scripts/verify_m1.py [--out examples/m1_grafana_status.json]
Prints a table and writes the raw query results so the run is recorded.
"""
import argparse, base64, json, os, time, urllib.parse, urllib.request

GRAFANA = os.environ.get("GRAFANA_URL", "http://127.0.0.1:13000")
AUTH = base64.b64encode(f"admin:{os.environ.get('GRAFANA_ADMIN_PASSWORD', 'admin')}".encode()).decode()
AGE = 'max by (device_id) (time() - tlast_over_time(device_uptime_seconds{job="fleet-sim"}[1d]))'


def get(path):
    req = urllib.request.Request(GRAFANA + path, headers={"Authorization": "Basic " + AUTH})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="examples/m1_grafana_status.json")
    a = ap.parse_args()
    q = urllib.parse.urlencode({"query": AGE})
    res = get(f"/api/datasources/proxy/uid/victoriametrics/api/v1/query?{q}")
    rows = []
    for s in sorted(res["data"]["result"], key=lambda s: s["metric"]["device_id"]):
        age = float(s["value"][1])
        rows.append({"device": s["metric"]["device_id"], "last_seen_s_ago": round(age, 1),
                     "status": "OFFLINE" if age > 120 else "ONLINE"})
    alerts = get("/api/prometheus/grafana/api/v1/alerts")["data"]["alerts"]
    alert_rows = [{"alert": a["labels"].get("alertname"), "device": a["labels"].get("device_id"),
                   "state": a["state"], "activeAt": a.get("activeAt")} for a in alerts]
    for r in rows:
        print(f"{r['device']:6} {r['status']:8} last seen {r['last_seen_s_ago']:>7.1f} s ago")
    print("alerts:", alert_rows or "none")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump({"recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "query_via": "Grafana datasource proxy (uid=victoriametrics)", "expr": AGE,
                   "devices": rows, "grafana_alerts": alert_rows, "raw": res}, f, indent=2)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
