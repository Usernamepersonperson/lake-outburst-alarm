"""Regression tests for the real 10-minute experiment: event labelling near the record start,
the lead metric, and the FOEN 40-day file parser."""

import json

import numpy as np
import pytest

from lakealarm import data, sim

STEP = 1 / 6  # 10 minutes in hours


def _flood_then_blip(lead_in_h: float = 0.0):
    """Shape of the Emme flood of 8 Oct 2026: base 0.8, rise to 9.8 m3/s, recession, and a
    one-sample blip of 5.6 m3/s about 11 h after the peak. ``lead_in_h`` hours of flat base
    flow are recorded before the rise."""
    n = int(round((300 + lead_in_h) * 6))
    t = np.arange(n) * STEP
    tp = lead_in_h + 130 * STEP  # peak 21.67 h after the start of the flood part
    q = np.full(n, 0.8)
    rise = (t >= tp - 3.67) & (t < tp)
    q[rise] = 0.8 + 9.0 * (t[rise] - (tp - 3.67)) / 3.67
    after = t >= tp
    q[after] = 0.8 + 9.0 * np.exp(-(t[after] - tp) / 12.0)
    i_peak = int(round(tp * 6))
    i_blip = i_peak + 65  # +10.8 h
    q[i_blip] = 5.6
    return t, q, i_peak, i_blip


def test_peak_near_record_start_is_not_labelled_from_a_later_blip():
    # The peak has no history (< 50 samples 24-96 h before it), the blip on its falling limb
    # has just enough. The old finder reported the blip (5.6) as the event peak.
    t, q, i_peak, i_blip = _flood_then_blip(lead_in_h=0.0)
    m = (t >= t[i_blip] - 96) & (t <= t[i_blip] - 24)
    assert m.sum() >= 50 and q[i_blip] >= 2.5 * np.median(q[m])  # the blip alone would pass
    got = sim.find_live_events(t, q)
    assert i_blip not in got
    assert all(abs(t[i] - t[i_peak]) >= 48 for i in got)


def test_same_flood_with_history_is_labelled_at_the_true_peak():
    t, q, i_peak, i_blip = _flood_then_blip(lead_in_h=120.0)
    got = sim.find_live_events(t, q)
    assert len(got) == 1
    assert got[0] == i_peak
    assert q[got[0]] == pytest.approx(9.8)
    assert t[got[0]] == pytest.approx(120.0 + 21.667, abs=0.01)


def test_peak_before_record_start_is_not_labelled_from_a_later_blip():
    # Record starts 1 h after a peak (falling limb); a blip 32.5 h later has enough history.
    n = 300 * 6
    t = np.arange(n) * STEP
    q = 0.8 + 20.0 * np.exp(-(t + 1.0) / 3.0)  # starts at 15.1 m3/s, falling
    i_blip = 195
    q[i_blip] = 12.0  # lower than the record start, but 2.5x its own history median
    assert q[i_blip] < q[0]
    m = (t >= t[i_blip] - 96) & (t <= t[i_blip] - 24)
    assert m.sum() >= 50 and q[i_blip] >= 2.5 * np.median(q[m])
    assert sim.find_live_events(t, q) == []


def test_separate_peaks_more_than_48_h_apart_are_both_found():
    n = 400 * 6
    t = np.arange(n) * STEP
    q = np.full(n, 2.0)
    q[(t > 150) & (t < 153)] = 20.0
    q[(t > 250) & (t < 253)] = 12.0
    got = sim.find_live_events(t, q)
    assert len(got) == 2
    assert 150 < t[got[0]] < 153 and 250 < t[got[1]] < 253


def _spike_then_surge():
    """Flat 0.4 m3/s, one-sample spike to 0.76 at 100 h (trips the CUSUM, as on the Emme on
    7 Oct 2026), then a real surge peaking at 135 h."""
    n = 240 * 6
    t = np.arange(n) * STEP
    q = np.full(n, 0.4)
    q[600] = 0.76  # 100 h
    s = (t > 125) & (t < 145)
    q[s] = 0.4 + 9.4 * np.sin(np.pi * (t[s] - 125) / 20) ** 2
    epoch = (t * 3600).astype(int) + 1_790_000_000
    return t, q, epoch


def test_lead_ignores_an_earlier_separate_alarm_and_counts_it_as_false():
    t, q, epoch = _spike_then_surge()
    out = sim.run_live({"s": {"t_h": t, "epoch": epoch, "flow": q}})
    assert len(out["events"]) == 1
    ev = out["events"][0]
    assert ev["detector_t"] > 120  # the alarm on the rise, not the spike at 100 h
    assert ev["fixed_t"] > ev["detector_t"]
    assert 0 < ev["lead_h"] < 10
    assert out["natural"]["false_alarms"] == 1  # the spike


def test_lead_is_undefined_when_the_fixed_alarm_never_cleared():
    n = 300 * 6
    t = np.arange(n) * STEP
    q = np.full(n, 1.0)
    a = (t > 100) & (t < 110)
    q[a] = 1.0 + 20.0 * np.sin(np.pi * (t[a] - 100) / 10) ** 2
    q[(t >= 110) & (t <= 170)] = 3.0  # stays above the 2.5x-median fixed level
    b = (t > 160) & (t < 170)
    q[b] = 3.0 + 30.0 * np.sin(np.pi * (t[b] - 160) / 10) ** 2
    epoch = (t * 3600).astype(int) + 1_790_000_000
    out = sim.run_live({"s": {"t_h": t, "epoch": epoch, "flow": q}})
    second = [e for e in out["events"] if e["peak_q"] > 25]
    assert len(second) == 1
    assert second[0]["fixed_t"] is None and second[0]["lead_h"] is None


def _plot(xs, ys, name="Abfluss"):
    return {
        "plot": {
            "data": [
                {"name": "Wasserstand", "yaxis": "y", "x": xs, "y": [500.0] * len(xs)},
                {"name": name, "yaxis": "y2", "x": xs, "y": ys},
            ]
        }
    }


def test_parse_foen_plot_keeps_the_10_min_grid_and_drops_bad_values():
    xs = [
        "2026-10-08T00:35:00.000+02:00",
        "2026-10-08T00:30:00.000+02:00",
        "2026-10-08T00:40:00.000+02:00",
        "2026-10-08T00:50:00.000+02:00",
        "2026-10-08T01:00:00.000+02:00",
        "2026-10-08T01:10:00.000+02:00",
    ]
    ys = [9.0, 1.0, 2.0, None, -1.0, "x"]
    v = data.parse_foen_plot(_plot(xs, ys))
    assert list(v["flow"]) == [1.0, 2.0]  # 00:35 off-grid, None, negative, text dropped
    assert data.epoch_to_iso(int(v["epoch"][0])) == "2026-10-07T22:30Z"
    assert list(v["t_h"]) == pytest.approx([0.0, 1 / 6])


def test_parse_foen_plot_handles_the_dst_change():
    xs = ["2026-10-25T02:50:00.000+02:00", "2026-10-25T02:00:00.000+01:00"]
    v = data.parse_foen_plot(_plot(xs, [1.0, 2.0]))
    assert v["t_h"][1] - v["t_h"][0] == pytest.approx(10 / 60)


def test_parse_foen_plot_without_discharge_returns_none():
    assert data.parse_foen_plot({"plot": {"data": []}}) is None
    assert data.parse_foen_plot({}) is None


def test_load_live_cache_prefers_the_foen_40_day_files(tmp_path):
    (tmp_path / "live10min_a_b.json").write_text(
        json.dumps({"payload": [{"timestamp": 0, "loc": "9", "par": "flow", "val": 1.0}]})
    )
    assert set(data.load_live_cache(tmp_path)) == {"9"}
    assert data.live_source(tmp_path)["kind"] == "relay"
    d = tmp_path / "foen40d" / "2026-11-12"
    d.mkdir(parents=True)
    xs = ["2026-10-08T00:00:00.000+00:00", "2026-10-08T00:10:00.000+00:00"]
    (d / "2070.json").write_text(json.dumps(_plot(xs, [0.8, 0.9])))
    live = data.load_live_cache(tmp_path)
    assert set(live) == {"2070"} and list(live["2070"]["flow"]) == [0.8, 0.9]
    assert data.live_source(tmp_path) == {"kind": "foen40d", "retrieved": "2026-11-12", "files": 1}
