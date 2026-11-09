import pytest

from lakealarm.detect import DetectorConfig, Status
from lakealarm.sampling import AdaptiveSampler, EnergyModel, SamplerConfig
from lakealarm.travel import (
    Reach,
    arrival_times_h,
    manning_velocity,
    travel_time_h,
    wave_celerity,
)

DCFG = DetectorConfig()


def status(t, rate=0.0, cusum=0.0, rise=0.0, alarm=False):
    return Status(t, alarm, rate, cusum, rise, "")


def test_quiet_uses_base_interval():
    s = AdaptiveSampler(DCFG)
    assert s.next_interval_s(status(0.0)) == 1800.0


def test_rising_switches_to_fast():
    s = AdaptiveSampler(DCFG)
    assert s.next_interval_s(status(1.0, rate=0.5 * DCFG.rate_alarm_per_h + 0.05, rise=0.3)) == 300


def test_cusum_alone_switches_to_fast():
    s = AdaptiveSampler(DCFG)
    assert s.next_interval_s(status(1.0, cusum=DCFG.cusum_h)) == 300


def test_hold_keeps_fast_then_returns_to_base():
    s = AdaptiveSampler(DCFG, SamplerConfig(hold_s=3600))
    s.next_interval_s(status(0.0, alarm=True))
    assert s.next_interval_s(status(0.5)) == 300
    assert s.next_interval_s(status(1.5)) == 1800


def test_low_battery_stretches_quiet_interval_only():
    s = AdaptiveSampler(DCFG)
    assert s.next_interval_s(status(0.0), battery_frac=0.1) == 3600
    assert s.next_interval_s(status(1.0, alarm=True), battery_frac=0.1) == 300


def test_battery_fraction_validated():
    with pytest.raises(ValueError):
        AdaptiveSampler(DCFG).next_interval_s(status(0.0), battery_frac=1.5)


def test_sampler_config_validation():
    with pytest.raises(ValueError):
        SamplerConfig(base_s=60, fast_s=300)
    with pytest.raises(ValueError):
        SamplerConfig(enter_frac=0.0)
    with pytest.raises(ValueError):
        SamplerConfig(low_battery_base_mult=0.5)


def test_energy_total_numeric():
    m = EnergyModel(sample_mj=20, uplink_mj=150, sleep_uw=20)
    # 10 samples + 2 uplinks + 1000 s sleep at 20 uW = 200 + 300 + 20 mJ
    assert m.total_mj(10, 2, 1000) == pytest.approx(520.0)
    with pytest.raises(ValueError):
        m.total_mj(-1, 0, 0)


def test_manning_velocity_matches_manning_identity():
    r = Reach(1.0, 0.04, 12.0, 0.045)
    v = manning_velocity(100.0, r)
    h = 100.0 / (12.0 * v)
    assert v == pytest.approx(h ** (2 / 3) * 0.04**0.5 / 0.045, rel=1e-9)
    assert v == pytest.approx(5.715, abs=1e-3)


def test_celerity_is_five_thirds_of_velocity():
    r = Reach(1.0, 0.02, 10.0)
    assert wave_celerity(30.0, r) == pytest.approx(5 / 3 * manning_velocity(30.0, r))


def test_bigger_flood_arrives_sooner():
    r = [Reach(10.0, 0.03, 12.0)]
    assert travel_time_h(150.0, r) < travel_time_h(20.0, r)


def test_travel_time_is_additive_over_reaches():
    a, b = Reach(4.0, 0.05, 9.0), Reach(7.0, 0.02, 15.0)
    assert travel_time_h(50.0, [a, b]) == pytest.approx(
        travel_time_h(50.0, [a]) + travel_time_h(50.0, [b])
    )


def test_travel_inputs_validated():
    with pytest.raises(ValueError):
        Reach(0.0, 0.01, 5.0)
    with pytest.raises(ValueError):
        travel_time_h(10.0, [])
    with pytest.raises(ValueError):
        manning_velocity(0.0, Reach(1, 0.01, 5))


def test_arrival_times_offset_from_alarm():
    out = arrival_times_h(2.0, 40.0, {"x": [Reach(5.0, 0.03, 10.0)]})
    assert out["x"] == pytest.approx(2.0 + travel_time_h(40.0, [Reach(5.0, 0.03, 10.0)]))
