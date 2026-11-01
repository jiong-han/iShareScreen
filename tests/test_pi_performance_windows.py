"""Bounded rolling stage metrics; no raw key or frame data in telemetry."""
import threading
import pytest

from isharescreen.proxy.input import InputController
import isharescreen.proxy.input as input_mod


class Socket:
    def sendall(self, _data):
        pass


def make_controller(monkeypatch, enabled=True):
    monkeypatch.setenv("ISS_PI_PERF_STATS", "1" if enabled else "0")
    return InputController(Socket(), None, server_width=1920, server_height=1080)


def test_rolling_percentiles_and_old_spike_expiry(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(input_mod.time, "monotonic", lambda: clock[0])
    c = make_controller(monkeypatch)
    for value in range(1, 101):
        c.note_timing("decode", float(value))
    s = c.performance_snapshot()["stages_ms"]["decode"]
    assert s == {"count": 100, "mean": 50.5, "p50": 50.0, "p95": 95.0,
                 "p99": 99.0, "max": 100.0}
    clock[0] = 11.0
    c.note_timing("decode", 2.0)
    assert c.performance_snapshot()["stages_ms"]["decode"]["max"] == 2
    clock[0] = 22.0
    assert c.performance_snapshot()["stages_ms"] == {}


def test_metrics_have_bounded_storage_and_packet_sampling(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(input_mod.time, "monotonic", lambda: clock[0])
    c = make_controller(monkeypatch)
    for value in range(3000):
        c.note_timing("convert", float(value))
    assert len(c._timing_windows["convert"]) == 2048
    assert c.performance_snapshot()["stages_ms"]["convert"]["count"] == 2048
    for i in range(1000):
        clock[0] = i / 1000
        c.note_timing("video_wait", 1.0)
    assert len(c._timing_windows["video_wait"]) <= 101


def test_opt_in_privacy_and_legacy_schema(monkeypatch):
    c = make_controller(monkeypatch, enabled=False)
    c.note_timing("decode", 30)
    c.note_timing("send", 0.4)
    assert c.performance_snapshot() is None
    assert "timing_windows_ms" not in c.diagnostics()
    assert set(c.diagnostics()["timings_ms"]) == {"send"}
    c = make_controller(monkeypatch)
    c.key_event(True, ord("x"))
    for value in (float("nan"), float("inf"), -1):
        c.note_timing("decode", value)
    c.note_timing("unknown-stage", 1)
    c.note_timing("upload", 3.0)
    d = c.diagnostics()
    assert d["key_event_count"] == 1
    assert set(d["timing_windows_ms"]["stages_ms"]) == {"send", "upload"}
    assert "keys" not in d and "keysyms" not in d


def test_decode_and_ui_threads_can_record_and_snapshot_concurrently(monkeypatch):
    c = make_controller(monkeypatch)
    errors = []
    def record(stage):
        try:
            for _ in range(500):
                c.note_timing(stage, 1.0)
                c.performance_snapshot()
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=record, args=(name,))
               for name in ("decode", "convert", "upload")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert all(s["count"] == 500 for s in c.performance_snapshot()["stages_ms"].values())
