import gzip

import numpy as np
import pytest

from lakealarm import data, events


@pytest.fixture(scope="module")
def series():
    return data.load_daily()


def test_fixture_has_all_stations_and_forty_years(series):
    assert set(series) == set(data.STATIONS)
    s = series["2351"]
    assert str(s.days[0]) == "1981-01-01" and str(s.days[-1]) == "2020-12-31"
    assert 39.5 < s.years < 40.1


def test_fixture_values_are_physical(series):
    for s in series.values():
        ok = s.q[np.isfinite(s.q)]
        assert (ok >= 0).all() and ok.max() < 2000


def test_known_value_from_fixture(series):
    s = series["2351"]
    i = int(np.searchsorted(s.days, np.datetime64("1981-01-01")))
    assert s.q[i] == pytest.approx(4.291)


def test_parse_live_drops_bad_rows_and_dedupes():
    payload = {
        "payload": [
            {"timestamp": 600, "loc": "1", "par": "flow", "val": 2.0},
            {"timestamp": 0, "loc": "1", "par": "flow", "val": 1.0},
            {"timestamp": 0, "loc": "1", "par": "flow", "val": 1.5},  # duplicate time
            {"timestamp": 1200, "loc": "1", "par": "flow", "val": "x"},
            {"timestamp": 1800, "loc": "1", "par": "flow", "val": -4},
            {"timestamp": 1800, "loc": "1", "par": "height", "val": 600.0},
            {"loc": "1", "par": "flow", "val": 1.0},
        ]
    }
    out = data.parse_live(payload)
    assert list(out["1"]["flow"]) == [1.5, 2.0]
    assert list(out["1"]["t_h"]) == [0.0, 600 / 3600]


def test_parse_live_empty():
    assert data.parse_live({"payload": []}) == {}


def test_epoch_to_iso():
    assert data.epoch_to_iso(0) == "1970-01-01T00:00Z"


def test_build_fixture_roundtrip(tmp_path):
    obs = tmp_path / "timeseries" / "observation_based"
    obs.mkdir(parents=True)
    hdr = "date,discharge_vol(m3/s),discharge_spec(mm/d),waterlevel(m),precipitation(mm/d)"
    hdr += ",temperature_min(degC),temperature_mean(degC),temperature_max(degC)\n"
    for sid in data.STATIONS:
        (obs / f"CAMELS_CH_obs_based_{sid}.csv").write_text(
            hdr + "2000-01-01,1.5,0,0,2.0,0,3.0,0\n2000-01-02,NaN,0,0,0,0,0,0\n", encoding="utf-8"
        )
    out = tmp_path / "f.csv.gz"
    assert data.build_fixture(tmp_path, out) == 2 * len(data.STATIONS)
    got = data.load_daily(out)
    assert got["2351"].q[0] == 1.5 and np.isnan(got["2351"].q[1])
    assert gzip.open(out, "rt").readline().startswith("station,date")


def test_visp_october_2000_is_confirmed(series):
    ev = events.confirm_event(series["2351"], "x", "2000-10-13", "2000-10-16")
    assert ev is not None and ev.peak_day == "2000-10-15" and ev.ratio > 8


def test_quiet_window_is_not_confirmed(series):
    assert events.confirm_event(series["2351"], "x", "2003-02-10", "2003-02-12") is None


def test_window_before_enough_history_returns_none(series):
    assert events.confirm_event(series["2351"], "x", "1981-01-10", "1981-01-12") is None


def test_window_after_record_returns_none(series):
    assert events.confirm_event(series["2351"], "x", "2021-06-01", "2021-06-03") is None


def test_higher_ratio_requirement_drops_events(series):
    lo = events.confirm_event(series["2269"], "x", "1987-08-23", "1987-08-26", ratio=2.5)
    hi = events.confirm_event(series["2269"], "x", "1987-08-23", "1987-08-26", ratio=50.0)
    assert lo is not None and hi is None


def test_confirm_all_finds_many_and_covers_every_window(series):
    got = events.confirm_all(series)
    assert len(got) > 60
    assert {e.label for e in got} == {w[0] for w in events.FLOOD_WINDOWS}


def test_exclusion_mask_covers_windows_only(series):
    s = series["2351"]
    m = events.exclusion_mask(s)
    i = int(np.searchsorted(s.days, np.datetime64("2000-10-15")))
    assert m[i] and not m[i - 60] and not m[i + 60]
