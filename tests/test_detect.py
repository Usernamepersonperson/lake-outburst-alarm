import math

import pytest

from lakealarm.detect import (
    DetectorConfig,
    FixedThreshold,
    RateOfRiseDetector,
    alarm_flags,
    first_alarm_index,
    onsets,
)

STEP_H = 10 / 60


def run(det, values, step_h=STEP_H):
    return [det.update(i * step_h, v) for i, v in enumerate(values)]


def test_config_rejects_bad_mode():
    with pytest.raises(ValueError):
        DetectorConfig(mode="cubic")


@pytest.mark.parametrize("field", ["rate_window_h", "rate_alarm_per_h", "cusum_h"])
def test_config_rejects_non_positive(field):
    with pytest.raises(ValueError):
        DetectorConfig(**{field: 0.0})


def test_config_with_replaces_field():
    assert DetectorConfig().with_(cusum_h=2.0).cusum_h == 2.0


def test_flat_series_never_alarms():
    st = run(RateOfRiseDetector(), [10.0] * 500)
    assert not any(s.alarm for s in st)


def test_exponential_rise_slope_is_recovered():
    det = RateOfRiseDetector(DetectorConfig(rate_alarm_per_h=5.0))
    vals = [10.0 * math.exp(0.3 * i * STEP_H) for i in range(60)]
    st = run(det, vals)
    assert st[-1].rate == pytest.approx(0.3, abs=1e-9)


def test_fast_surge_triggers_rate_rule():
    vals = [10.0] * 200 + [10.0 * math.exp(0.4 * i * STEP_H) for i in range(60)]
    st = run(RateOfRiseDetector(), vals)
    first = next(s for s in st if s.alarm)
    assert first.reason == "rate"
    assert first.t_h > 200 * STEP_H


def test_diurnal_cycle_is_not_an_alarm():
    vals = [10.0 * math.exp(0.15 * math.sin(2 * math.pi * i * STEP_H / 24)) for i in range(144 * 7)]
    assert not any(s.alarm for s in run(RateOfRiseDetector(), vals))


def test_slow_persistent_rise_caught_by_cusum():
    # +0.06 ln-units per hour: below the rate rule (0.12) but above the CUSUM drift allowance
    vals = [10.0] * 200 + [10.0 * math.exp(0.06 * i * STEP_H) for i in range(200)]
    st = run(RateOfRiseDetector(DetectorConfig(rate_alarm_per_h=0.12, cusum_k_per_h=0.02)), vals)
    hit = next(s for s in st if s.alarm)
    assert hit.reason == "cusum"


def test_linear_mode_stage_rise():
    cfg = DetectorConfig(mode="linear", rate_alarm_per_h=0.3, min_rise=0.2, cusum_h=0.4)
    vals = [1.0] * 100 + [1.0 + 0.5 * i * STEP_H * 2 for i in range(30)]
    st = run(RateOfRiseDetector(cfg), vals)
    assert any(s.alarm for s in st)


def test_alarm_clears_after_recession():
    up = [10.0 * math.exp(0.4 * i * STEP_H) for i in range(30)]
    down = [up[-1] * math.exp(-0.15 * i * STEP_H) for i in range(400)]
    st = run(RateOfRiseDetector(), [10.0] * 100 + up + down)
    assert any(s.alarm for s in st)
    assert not st[-1].alarm


def test_baseline_is_frozen_during_a_surge():
    det = RateOfRiseDetector()
    run(det, [10.0] * 100)
    b0 = det.baseline
    run_vals = [10.0 * math.exp(0.4 * i * STEP_H) for i in range(1, 25)]
    for i, v in enumerate(run_vals):
        det.update(100 * STEP_H + i * STEP_H, v)
    assert det.baseline == pytest.approx(b0, abs=0.05)


def test_timestamps_must_increase():
    det = RateOfRiseDetector()
    det.update(1.0, 5.0)
    with pytest.raises(ValueError):
        det.update(1.0, 5.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), None])
def test_non_finite_value_rejected(bad):
    with pytest.raises(ValueError):
        RateOfRiseDetector().update(0.0, bad)


def test_zero_and_negative_values_do_not_crash_in_log_mode():
    det = RateOfRiseDetector()
    assert det.update(0.0, 0.0).alarm is False
    assert det.update(0.1, -3.0).alarm is False


def test_daily_step_jump_alarms():
    cfg = DetectorConfig(
        rate_window_h=48, rate_alarm_per_h=math.log(2) / 24, min_rise=math.log(2), cusum_h=3.0
    )
    st = run(RateOfRiseDetector(cfg), [5.0] * 20 + [5.0, 40.0, 90.0], step_h=24.0)
    assert not st[19].alarm
    assert st[-2].alarm


def test_reset_clears_state():
    det = RateOfRiseDetector()
    run(det, [10.0] * 10)
    det.reset()
    assert det.baseline is None


def test_fixed_threshold_with_hysteresis():
    f = FixedThreshold(10.0, hysteresis=2.0)
    assert [f.update(v) for v in (5, 10, 9, 7.9, 5)] == [False, True, True, False, False]


def test_fixed_threshold_rejects_negative_hysteresis_and_nan():
    with pytest.raises(ValueError):
        FixedThreshold(1.0, hysteresis=-1)
    with pytest.raises(ValueError):
        FixedThreshold(1.0).update(float("nan"))


def test_onsets_merge_close_runs():
    t = [0, 1, 2, 3, 4, 5, 6, 7, 8]
    on = [0, 1, 0, 1, 0, 0, 0, 0, 1]
    assert onsets(t, on, merge_h=2.5) == [1.0, 8.0]


def test_first_alarm_index_none_for_flat_and_value_for_surge():
    t = [i * STEP_H for i in range(100)]
    assert first_alarm_index(t, [4.0] * 100, RateOfRiseDetector()) is None
    surge = [4.0] * 50 + [4.0 * math.exp(0.5 * i * STEP_H) for i in range(50)]
    assert first_alarm_index(t, surge, RateOfRiseDetector()) > 50
    assert alarm_flags(t, surge, FixedThreshold(8.0))[-1] is True
