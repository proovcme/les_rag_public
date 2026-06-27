"""ETA индексации — чистые функции оценки времени (числа считает код, не LLM)."""
from __future__ import annotations

from datetime import datetime, timedelta

from proxy.services.runtime_dispatcher import _fmt_dur, compute_eta


def test_fmt_dur_buckets():
    assert _fmt_dur(45) == "~45с"
    assert _fmt_dur(89) == "~89с"
    assert _fmt_dur(12 * 60) == "~12м"
    assert _fmt_dur(80 * 60) == "~80м"
    assert _fmt_dur(95 * 60) == "~1ч 35м"


def test_eta_basic():
    started = datetime(2026, 1, 1, 0, 0, 0)
    now_ts = (started + timedelta(seconds=100)).timestamp()
    eta = compute_eta(started.isoformat(), 10, 100, running=True, now_ts=now_ts)
    assert eta["percent"] == 10.0
    assert eta["elapsed_seconds"] == 100
    assert eta["eta_seconds"] == 900       # 90 осталось / 0.1 док/с
    assert eta["eta_text"] == "~15м"
    assert eta["rate_per_min"] == 6.0


def test_eta_not_running_keeps_percent_only():
    eta = compute_eta("2026-01-01T00:00:00", 5, 20, running=False)
    assert eta["percent"] == 25.0
    assert eta["eta_seconds"] is None and eta["eta_text"] == ""


def test_eta_complete_no_estimate():
    eta = compute_eta("2026-01-01T00:00:00", 50, 50, running=True)
    assert eta["percent"] == 100.0
    assert eta["eta_seconds"] is None


def test_eta_zero_progress_no_divide():
    eta = compute_eta("2026-01-01T00:00:00", 0, 100, running=True)
    assert eta["percent"] == 0.0
    assert eta["eta_seconds"] is None


def test_eta_bad_inputs_safe():
    assert compute_eta(None, None, None)["percent"] is None
    assert compute_eta("not-a-date", 5, 10, running=True)["eta_seconds"] is None
