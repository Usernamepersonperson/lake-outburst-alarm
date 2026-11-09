import json

import pytest

from lakealarm import cli, data, report


def test_travel_command_prints_minutes(capsys):
    rc = cli.main(
        ["travel", "--q", "100", "--length-km", "10", "--slope", "0.04", "--width-m", "12"]
    )
    out = capsys.readouterr().out
    assert rc == 0 and out.strip().endswith("min")
    # celerity 5/3 * 5.715 m/s over 10 km is about 17.5 min
    assert float(out.split()[0]) == pytest.approx(17.5, abs=0.2)


def test_cli_requires_a_subcommand():
    with pytest.raises(SystemExit):
        cli.main([])


def test_travel_example_orders_points_and_discharges():
    t = report.travel_example()
    assert t["20.0"]["village A (6 km)"] < t["20.0"]["town B (21 km)"]
    assert t["150.0"]["town B (21 km)"] < t["20.0"]["town B (21 km)"]


def test_daily_choice_still_meets_the_dry_weather_budget():
    series = data.load_daily()
    from lakealarm import evaluate

    r = evaluate.false_alarms(series, evaluate.daily_config(*report.DAILY_CHOICE), 1981, 2000)
    assert r.dry / r.station_years <= 0.1


def test_demo_runs_and_writes_results(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(report, "RESULTS", tmp_path / "r.json")
    monkeypatch.setattr(data, "load_live_cache", lambda cache=data.CACHE: {})
    rc = cli.main(["demo", "--no-figures", "--trials", "2", "--energy-runs", "2"])
    assert rc == 0
    res = json.loads((tmp_path / "r.json").read_text())
    assert res["daily_real"]["confirmed_events"] > 60
    assert "REAL daily" in capsys.readouterr().out
