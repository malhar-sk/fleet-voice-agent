import pytest

from agent import fleet_tools as ft


@pytest.mark.parametrize("raw,expected", [
    ("pi-3", "pi-3"), ("Pi 3", "pi-3"), ("pi3", "pi-3"), ("पाई ३", "pi-3"), ("pi three", "pi-3"),
    ("device 5", "pi-5"), ("पाई दोन", "pi-2"), ("PI-1", "pi-1"),
])
def test_normalize_device(raw, expected):
    assert ft.normalize_device(raw) == expected


def test_normalize_device_rejects_garbage():
    with pytest.raises(ft.ToolError):
        ft.normalize_device("the toaster")


def test_list_devices(fake_vm):
    r = ft.list_devices()
    assert r["total"] == 5 and r["online_count"] == 4 and r["offline_count"] == 1
    assert [d["device"] for d in r["devices"]] == ["pi-1", "pi-2", "pi-3", "pi-4", "pi-5"]
    pi3 = r["devices"][2]
    assert pi3["status"] == "OFFLINE" and pi3["uptime_seconds"] is None


def test_list_offline_devices(fake_vm):
    r = ft.list_offline_devices()
    assert r["offline_count"] == 1
    assert r["offline"][0] == {"device": "pi-3", "silent_for_seconds": 245, "silent_for_minutes": 4.1}


def test_device_status_online_and_unknown(fake_vm):
    r = ft.device_status("pi 5")
    assert r["status"] == "ONLINE" and r["cpu_temperature_c"] == 57.6
    with pytest.raises(ft.ToolError, match="Known devices"):
        ft.device_status("pi-9")


def test_query_metric(fake_vm):
    r = ft.query_metric("pi-2", "temp", 15)
    assert r["metric"] == "temperature" and r["unit"] == "°C" and r["minutes"] == 15
    assert r["latest"] == 48.9 and r["max"] == pytest.approx(50.4)
    assert 'device_id="pi-2"' in fake_vm.queries[-1] and "[15m]" in fake_vm.queries[-1]


def test_query_metric_silent_device(fake_vm):
    r = ft.query_metric("pi-3", "memory", 2)
    assert "note" in r and "latest" not in r


def test_query_metric_bad_metric(fake_vm):
    assert "error" in ft.call_tool("query_metric", {"device": "pi-1", "metric": "humidity"})


def test_sla_breaches(fake_vm):
    r = ft.sla_breaches(10)
    assert r == {"minutes": 10, "sla_breaches": 8, "messages_sent": 1200, "messages_acked": 1190, "queue_depth": 3}


def test_call_tool_forgiving_args(fake_vm):
    assert ft.call_tool("device_status", {"device": "pi-1"})["device"] == "pi-1"
    assert ft.call_tool("list_devices", {"junk": 1})["total"] == 5
    assert "error" in ft.call_tool("rm_rf", {})


def test_backend_down_is_a_tool_error():
    ft.set_client(ft.VMClient("http://127.0.0.1:9", timeout=0.5))
    try:
        assert "unavailable" in ft.call_tool("list_offline_devices")["error"]
    finally:
        ft.set_client(None)


def test_schemas_match_functions():
    assert {s["name"] for s in ft.TOOL_SCHEMAS} == set(ft.TOOL_FUNCS)
