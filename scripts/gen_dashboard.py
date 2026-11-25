"""Generate grafana/dashboards/fleet.json (run: python scripts/gen_dashboard.py).

Queries follow the fleet-health-monitor contract: a device is OFFLINE when the age of its last
device_uptime_seconds sample exceeds 120 s (the "device silent > 2 min" rule used everywhere here).
"""
import json, pathlib

DS = {"type": "prometheus", "uid": "victoriametrics"}
AGE = 'max by (device_id) (time() - tlast_over_time(device_uptime_seconds{job="fleet-sim"}[1d]))'
SILENT = 120

def target(expr, ref="A", legend="{{device_id}}", instant=False, fmt="time_series"):
    t = {"datasource": DS, "expr": expr, "refId": ref, "legendFormat": legend, "format": fmt}
    if instant:
        t.update({"instant": True, "range": False})
    return t

panels = []
y = 0
panels.append({
    "id": 1, "type": "stat", "title": "Devices online", "datasource": DS,
    "gridPos": {"h": 5, "w": 6, "x": 0, "y": y},
    "targets": [target(f"count(({AGE}) <= {SILENT}) or vector(0)", legend="online", instant=True)],
    "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background", "textMode": "value"},
    "fieldConfig": {"defaults": {"unit": "none", "thresholds": {"mode": "absolute", "steps": [
        {"color": "red", "value": None}, {"color": "orange", "value": 4}, {"color": "green", "value": 5}]}}, "overrides": []},
})
panels.append({
    "id": 2, "type": "stat", "title": "Devices OFFLINE (silent > 2 min)", "datasource": DS,
    "gridPos": {"h": 5, "w": 6, "x": 6, "y": y},
    "targets": [target(f"count(({AGE}) > {SILENT}) or vector(0)", legend="offline", instant=True)],
    "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background", "textMode": "value"},
    "fieldConfig": {"defaults": {"thresholds": {"mode": "absolute", "steps": [
        {"color": "green", "value": None}, {"color": "red", "value": 1}]}}, "overrides": []},
})
panels.append({
    "id": 3, "type": "stat", "title": "Payment SLA breaches (last 5 min)", "datasource": DS,
    "gridPos": {"h": 5, "w": 6, "x": 12, "y": y},
    "targets": [target('sum(increase(swift_sla_breaches_total[5m])) or vector(0)', legend="breaches", instant=True)],
    "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background"},
    "fieldConfig": {"defaults": {"decimals": 0, "thresholds": {"mode": "absolute", "steps": [
        {"color": "green", "value": None}, {"color": "red", "value": 1}]}}, "overrides": []},
})
panels.append({
    "id": 4, "type": "stat", "title": "Payment queue depth", "datasource": DS,
    "gridPos": {"h": 5, "w": 6, "x": 18, "y": y},
    "targets": [target('max(swift_queue_depth)', legend="queue", instant=True)],
    "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
    "fieldConfig": {"defaults": {}, "overrides": []},
})
y += 5
# Fleet table: one row per device with status
panels.append({
    "id": 5, "type": "table", "title": "Fleet: status per device", "datasource": DS,
    "gridPos": {"h": 9, "w": 24, "x": 0, "y": y},
    "targets": [
        target(AGE, "AGE", instant=True, fmt="table"),
        target('max by (device_id) (last_over_time(device_temperature_celsius[1d]))', "TEMP", instant=True, fmt="table"),
        target('max by (device_id) (last_over_time(device_memory_utilization_percent[1d]))', "MEM", instant=True, fmt="table"),
        target('max by (device_id) (last_over_time(device_uptime_seconds[1d]))', "UP", instant=True, fmt="table"),
    ],
    "transformations": [
        {"id": "merge", "options": {}},
        {"id": "organize", "options": {"excludeByName": {"Time": True},
            "renameByName": {"device_id": "Device", "Value #AGE": "Status (last seen, s ago)",
                             "Value #TEMP": "CPU temp (°C)", "Value #MEM": "Memory (%)", "Value #UP": "Uptime (last report)"}}},
        {"id": "sortBy", "options": {"sort": [{"field": "Device"}]}},
    ],
    "fieldConfig": {"defaults": {"custom": {"align": "auto"}}, "overrides": [
        {"matcher": {"id": "byName", "options": "Status (last seen, s ago)"}, "properties": [
            {"id": "mappings", "value": [
                {"type": "range", "options": {"from": 0, "to": SILENT, "result": {"text": "ONLINE", "color": "green", "index": 0}}},
                {"type": "range", "options": {"from": SILENT, "to": 1e12, "result": {"text": "OFFLINE", "color": "red", "index": 1}}}]},
            {"id": "custom.cellOptions", "value": {"type": "color-background"}}]},
        {"matcher": {"id": "byName", "options": "Uptime (last report)"}, "properties": [{"id": "unit", "value": "s"}]},
        {"matcher": {"id": "byName", "options": "Memory (%)"}, "properties": [{"id": "decimals", "value": 1}]},
    ]},
    "options": {"showHeader": True},
})
y += 9
panels.append({
    "id": 6, "type": "timeseries", "title": "CPU temperature", "datasource": DS,
    "gridPos": {"h": 8, "w": 12, "x": 0, "y": y},
    "targets": [target('max by (device_id) (device_temperature_celsius)')],
    "fieldConfig": {"defaults": {"unit": "celsius"}, "overrides": []},
})
panels.append({
    "id": 7, "type": "timeseries", "title": "Seconds since last report (OFFLINE above 120)", "datasource": DS,
    "gridPos": {"h": 8, "w": 12, "x": 12, "y": y},
    "targets": [target(AGE)],
    "fieldConfig": {"defaults": {"unit": "s", "custom": {"thresholdsStyle": {"mode": "line"}},
        "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "red", "value": SILENT}]}}, "overrides": []},
})
y += 8
panels.append({
    "id": 8, "type": "timeseries", "title": "Memory utilisation", "datasource": DS,
    "gridPos": {"h": 8, "w": 12, "x": 0, "y": y},
    "targets": [target('max by (device_id) (device_memory_utilization_percent)')],
    "fieldConfig": {"defaults": {"unit": "percent"}, "overrides": []},
})
panels.append({
    "id": 9, "type": "timeseries", "title": "Payments per minute: sent / acked / SLA breaches", "datasource": DS,
    "gridPos": {"h": 8, "w": 12, "x": 12, "y": y},
    "targets": [
        target('sum(increase(swift_messages_sent_total[1m]))', "S", legend="sent"),
        target('sum(increase(swift_messages_acked_total[1m]))', "K", legend="acked"),
        target('sum(increase(swift_sla_breaches_total[1m]))', "B", legend="SLA breaches"),
    ],
    "fieldConfig": {"defaults": {}, "overrides": []},
})

dash = {
    "uid": "fleet-voice", "title": "Device Fleet (simulated) + Payment SLA", "tags": ["fleet", "synthetic"],
    "timezone": "browser", "schemaVersion": 39, "version": 1, "refresh": "10s",
    "time": {"from": "now-30m", "to": "now"},
    "description": "Demonstration only. All data is synthetic, produced by fleet-sim.",
    "panels": panels,
}
out = pathlib.Path(__file__).resolve().parents[1] / "grafana/dashboards/fleet.json"
out.write_text(json.dumps(dash, indent=2))
print("wrote", out)
