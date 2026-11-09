"""Command line: ``python -m lakealarm demo | tune | fetch | travel``."""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from . import data, evaluate, report
from .travel import Reach, travel_time_h


def _fmt(x, nd=2):
    return "n/a" if x is None else f"{x:.{nd}f}"


def cmd_demo(args: argparse.Namespace) -> int:
    live_ok = bool(data.load_live_cache()) and not args.no_live
    res = report.run_all(live=live_ok, trials=args.trials, energy_runs=args.energy_runs)
    d = res["daily_real"]
    print("== REAL daily data (CAMELS-CH subset of FOEN gauges, 1981-2020) ==")
    print(f"confirmed station-events: {d['confirmed_events']}  {d['event_labels']}")
    for k in ("lead_p99", "lead_p95"):
        s = d[k]
        print(
            f"{k}: detector {s['detector_alarmed']}/{s['events']}, fixed {s['fixed_alarmed']}/"
            f"{s['events']}, mean lead {_fmt(s['mean_lead_days'])} d "
            f"(earlier {s['earlier']}, same day {s['same_day']}, later {s['later']})"
        )
    for k, v in d.items():
        if k.startswith("fa_"):
            print(
                f"{k}: {v['alarms']} alarms ({v['rain_driven']} rain-driven, {v['dry']} dry) "
                f"over {v['station_years']:.0f} station-years = {v['per_station_year']:.2f}/yr, "
                f"dry {v['dry_per_station_year']:.3f}/yr"
            )
    print("== SIMULATED sub-daily surges (fixed 10-min sampling) ==")
    for key in ("grid_fixed_2p5x", "grid_fixed_4x"):
        print(key)
        for r in res["subdaily_sim"][key]:
            print(
                f"  rise {r['rise_h']:>4.0f} h  peak x{r['peak_ratio']:<4.0f} "
                f"detected {r['detected']}/{r['trials']}  fixed {r['fixed_detected']}/{r['trials']}"
                f"  median lead {_fmt(r['median_lead_h'])} h"
            )
    for k in ("sim_false_alarms_diurnal_0.3", "sim_false_alarms_diurnal_0.6"):
        v = res["subdaily_sim"][k]
        print(f"{k}: {v['alarms']} alarms in {v['station_years']:.2f} simulated station-years")
    e = res["energy_sim"]
    print("== Sampling energy (SIMULATED, ASSUMED per-event costs) ==")
    print(
        f"samples -{e['mean_sample_reduction']:.0%}, energy -{e['mean_energy_saving']:.0%}, "
        f"detection delay {_fmt(e['mean_detect_delay_min'], 1)} min (max "
        f"{_fmt(e['max_detect_delay_min'], 1)}), mean power {e['fixed_mean_power_uw']:.0f} -> "
        f"{e['adaptive_mean_power_uw']:.0f} uW"
    )
    if res.get("live_real"):
        lv = res["live_real"]
        print(f"== REAL 10-min records {lv['range'][0]} .. {lv['range'][1]} ==")
        for ev in lv["events"]:
            print(
                f"  {ev['station']} {ev['time']} peak {ev['peak_q']:.1f} (median {ev['ref_q']:.1f})"
                f" lead {_fmt(ev['lead_h'])} h"
            )
        print(f"natural-flow: {lv['natural']}  peaking: {lv['peaking']}")
    report.save(res)
    if not args.no_figures:
        from . import figures

        figures.make_all(res)
    return 0


def cmd_tune(_: argparse.Namespace) -> int:
    series = data.load_daily()
    cfg, key, dry = evaluate.tune_daily(series)
    print("chosen (rise/day, min ratio, cusum ratio):", key, "dry FA/station-year:", round(dry, 4))
    print(cfg)
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    end = date.today()
    start = end - timedelta(days=args.days)
    out = data.fetch_live(start, end)
    print("saved", out["raw"])
    return 0


def cmd_travel(args: argparse.Namespace) -> int:
    reach = Reach(args.length_km, args.slope, args.width_m)
    print(f"{travel_time_h(args.q, [reach]) * 60.0:.1f} min")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="lakealarm", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="reproduce every README number")
    d.add_argument("--no-figures", action="store_true")
    d.add_argument("--no-live", action="store_true", help="skip the cached 10-min real data")
    d.add_argument("--trials", type=int, default=20)
    d.add_argument("--energy-runs", type=int, default=12)
    d.set_defaults(fn=cmd_demo)
    sub.add_parser("tune", help="re-derive the daily setting").set_defaults(fn=cmd_tune)
    f = sub.add_parser("fetch", help="download recent 10-min real data into cache/")
    f.add_argument("--days", type=int, default=32)
    f.set_defaults(fn=cmd_fetch)
    t = sub.add_parser("travel", help="travel time over one reach")
    t.add_argument("--q", type=float, required=True, help="discharge m3/s")
    t.add_argument("--length-km", type=float, required=True)
    t.add_argument("--slope", type=float, required=True)
    t.add_argument("--width-m", type=float, required=True)
    t.set_defaults(fn=cmd_travel)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
