import math

import numpy as np
import pytest

from lakealarm import data, evaluate, events, sim


def test_background_is_deterministic_and_seeded():
    a = sim.background_1min(1.0, 10.0, seed=3)
    assert np.array_equal(a, sim.background_1min(1.0, 10.0, seed=3))
    assert not np.array_equal(a, sim.background_1min(1.0, 10.0, seed=4))
    assert len(a) == 1440


def test_background_rejects_bad_input():
    with pytest.raises(ValueError):
        sim.background_1min(0.0, 10.0, 1)


def test_surge_shape_values():
    t = np.array([0.0, 5.0, 10.0, 16.0])
    s = sim.surge_shape(t, t0_h=5.0, rise_h=5.0, decay_h=6.0)
    assert s[0] == 0.0 and s[1] == 0.0
    assert s[2] == pytest.approx(1.0)
    assert s[3] == pytest.approx(math.exp(-1.0))


def test_surge_shape_rejects_bad_params():
    with pytest.raises(ValueError):
        sim.surge_shape(np.zeros(3), 0, 0, 1)


def test_inject_surge_hits_requested_peak_ratio():
    q = np.full(2000, 10.0)
    out = sim.inject_surge(q, 1.0, t0_h=1.0, peak_ratio=5.0, rise_h=4.0, decay_h=3.0)
    assert out.max() == pytest.approx(50.0, rel=0.01)
    with pytest.raises(ValueError):
        sim.inject_surge(q, 1.0, 1.0, 1.0, 4.0, 3.0)


def test_fast_surge_detected_before_fixed_threshold():
    r = sim.run_surge(peak_ratio=5.0, rise_h=6.0, seed=1)
    assert r.detector_h is not None and r.fixed_h is not None
    assert r.lead_h > 0


def test_lead_grid_shape_and_counts():
    rows = sim.lead_grid(peaks=(5.0,), rises=(6.0,), trials=3)
    assert len(rows) == 1 and rows[0]["trials"] == 3
    assert 0 <= rows[0]["detected"] <= 3


def test_no_false_alarms_on_quiet_simulated_background():
    n, years = sim.sim_false_alarms(years=0.5, diurnal_amp=0.3)
    assert n == 0 and years > 0.4


def test_find_live_events_picks_the_peak_only():
    t = np.arange(0, 300, 1 / 6)
    q = np.full(len(t), 2.0)
    q[(t > 200) & (t < 205)] = 20.0
    got = sim.find_live_events(t, q)
    assert len(got) == 1 and 200 < t[got[0]] < 205


def test_find_live_events_ignores_small_bumps():
    t = np.arange(0, 300, 1 / 6)
    q = np.full(len(t), 2.0)
    q[(t > 200) & (t < 205)] = 3.0
    assert sim.find_live_events(t, q) == []


def test_peaking_flags_same_hour_recurrence():
    ep = np.array([h * 3600 for h in (19, 43, 67, 91)])
    assert sim._peaking(ep, [0, 1, 2, 3])
    ep2 = np.array([h * 3600 for h in (3, 17, 30, 45)])
    assert not sim._peaking(ep2, [0, 1, 2, 3])
    assert not sim._peaking(ep2, [0, 1])


def test_run_live_on_synthetic_record():
    t = np.arange(0, 24 * 10, 1 / 6)
    q = np.full(len(t), 3.0)
    surge = (t > 150) & (t < 160)
    q[surge] = 3.0 + 40.0 * np.sin(np.pi * (t[surge] - 150) / 10) ** 2
    epoch = (t * 3600).astype(int) + 1_700_000_000
    out = sim.run_live({"s": {"t_h": t, "epoch": epoch, "flow": q}})
    assert len(out["events"]) == 1
    ev = out["events"][0]
    assert ev["detector_t"] is not None and ev["lead_h"] > 0
    assert out["natural"]["false_alarms"] == 0


def test_adaptive_sampling_uses_fewer_samples_and_same_detection():
    r = sim.energy_comparison(days=20, surges=1, seed=5)
    assert r["adaptive"].samples < 0.7 * r["fixed"].samples
    assert r["adaptive"].detect_h is not None
    assert abs(r["adaptive"].detect_h - r["fixed"].detect_h) < 1.0


def test_energy_comparison_uses_given_costs():
    from lakealarm.sampling import EnergyModel

    zero = sim.energy_comparison(days=10, surges=1, seed=2, model=EnergyModel(0, 0, 0))
    assert zero["fixed"].energy_mj == 0.0 and zero["saving"] == 0.0
    costly = sim.energy_comparison(days=10, surges=1, seed=2, model=EnergyModel(100, 0, 0))
    assert costly["fixed"].energy_mj == pytest.approx(costly["fixed"].samples * 100)


# ------------------------------------------------------------------ real daily evaluation


@pytest.fixture(scope="module")
def series():
    return data.load_daily()


def test_daily_config_values():
    cfg = evaluate.daily_config(2.0, 2.0, 4.0)
    assert cfg.rate_alarm_per_h == pytest.approx(math.log(2) / 24)
    assert cfg.min_rise == pytest.approx(math.log(2))


def test_rising_edges():
    f = np.array([0, 1, 1, 0, 1, 0, 0, 1], dtype=bool)
    assert list(evaluate.rising_edges(f)) == [1, 4, 7]


def test_run_daily_resets_across_gaps(series):
    s = series["2070"]
    q = s.q.copy()
    q[100:110] = np.nan
    s2 = data.DailySeries(s.station, s.days, q, s.precip, s.tmean)
    flags = evaluate.run_daily(s2, evaluate.daily_config())
    assert not flags[100:110].any()


def test_fixed_level_is_a_percentile(series):
    s = series["2351"]
    assert evaluate.fixed_level(s, 99) > evaluate.fixed_level(s, 95) > np.nanmedian(s.q)


def test_false_alarm_report_counts_add_up(series):
    r = evaluate.false_alarms(series, evaluate.daily_config(2.5, 2.5, 4.0), 1981, 1990, ["2351"])
    assert r.alarms == r.rain_driven + r.dry
    assert 9.5 < r.station_years < 10.1
    assert r.per_station_year == pytest.approx(r.alarms / r.station_years)


def test_event_leads_report_both_alarms_for_a_big_flood(series):
    ev = events.confirm_event(series["2351"], "x", "2000-10-13", "2000-10-16")
    out = evaluate.event_leads(series, [ev], evaluate.daily_config(2.5, 2.5, 4.0))
    assert out[0].detector_day is not None and out[0].fixed_day is not None
    assert out[0].lead_days == out[0].detector_day - out[0].fixed_day


def test_tune_daily_respects_budget_on_small_grid(series):
    cfg, key, dry = evaluate.tune_daily(
        series, 1981, 1990, dry_budget=1e6, grid=((2.5, 3.0), (2.5,), (4.0,)), station_ids=["2070"]
    )
    assert key == (2.5, 2.5, 4.0) and cfg.min_rise == pytest.approx(math.log(2.5))


def test_tune_daily_raises_when_budget_impossible(series):
    with pytest.raises(RuntimeError):
        evaluate.tune_daily(
            series, 1981, 1985, dry_budget=-1.0, grid=((1.6,), (1.5,), (3.0,)), station_ids=["2351"]
        )
