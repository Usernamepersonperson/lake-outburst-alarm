"""Run every experiment and collect the numbers that go into the README and the figures."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import data, evaluate, events, sim
from .sampling import SamplerConfig
from .travel import Reach, travel_time_h

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "results.json"

# Output of evaluate.tune_daily(series) on 1981-2000 (dry-weather budget 0.1 / station-year).
# Re-derive with `python -m lakealarm tune`; a test checks the budget is still met.
DAILY_CHOICE = (2.0, 3.0, 5.0)  # rise factor per day, min ratio over baseline, CUSUM ratio


def _lead_stats(leads: list[evaluate.EventLead]) -> dict:
    both = [item.lead_days for item in leads if item.lead_days is not None]
    return {
        "events": len(leads),
        "detector_alarmed": sum(item.detector_day is not None for item in leads),
        "fixed_alarmed": sum(item.fixed_day is not None for item in leads),
        "both": len(both),
        "mean_lead_days": float(np.mean(both)) if both else None,
        "earlier": int(sum(x > 0 for x in both)),
        "same_day": int(sum(x == 0 for x in both)),
        "later": int(sum(x < 0 for x in both)),
    }


def daily_section(series: dict[str, data.DailySeries]) -> dict:
    cfg = evaluate.daily_config(*DAILY_CHOICE)
    confirmed = events.confirm_all(series)
    out: dict = {
        "config": {
            "rise_per_day": DAILY_CHOICE[0],
            "min_ratio": DAILY_CHOICE[1],
            "cusum_ratio": DAILY_CHOICE[2],
        }
    }
    out["confirmed_events"] = len(confirmed)
    out["event_labels"] = {}
    for e in confirmed:
        out["event_labels"][e.label] = out["event_labels"].get(e.label, 0) + 1
    out["lead_p99"] = _lead_stats(evaluate.event_leads(series, confirmed, cfg, pct=99.0))
    out["lead_p95"] = _lead_stats(evaluate.event_leads(series, confirmed, cfg, pct=95.0))
    for name, (a, b) in {"train_1981_2000": (1981, 2000), "test_2001_2020": (2001, 2020)}.items():
        for grp, ids in (
            ("glacier_fed", list(data.GLACIER_FED)),
            ("rain_fed", list(data.RAIN_FED)),
        ):
            r = evaluate.false_alarms(series, cfg, a, b, ids)
            out[f"fa_{name}_{grp}"] = {
                "alarms": r.alarms,
                "rain_driven": r.rain_driven,
                "dry": r.dry,
                "station_years": r.station_years,
                "per_station_year": r.per_station_year,
                "dry_per_station_year": r.dry / r.station_years,
            }
    return out


def subdaily_section(trials: int = 20) -> dict:
    cfg = sim.fast_config()
    out: dict = {"label": "SIMULATED surges on SIMULATED background, fixed 10-min sampling"}
    out["grid_fixed_2p5x"] = sim.lead_grid(trials=trials, cfg=cfg, fixed_factor=2.5)
    out["grid_fixed_4x"] = sim.lead_grid(trials=trials, cfg=cfg, fixed_factor=4.0)
    for amp in (0.3, 0.6):
        n, yrs = sim.sim_false_alarms(years=5.0, diurnal_amp=amp, cfg=cfg)
        out[f"sim_false_alarms_diurnal_{amp}"] = {"alarms": n, "station_years": yrs}
    return out


def energy_section(runs: int = 12) -> dict:
    savings, samples_red, delays = [], [], []
    fixed_mj = adapt_mj = 0.0
    scfg = SamplerConfig()
    for seed in range(100, 100 + runs):
        r = sim.energy_comparison(seed=seed, scfg=scfg)
        savings.append(r["saving"])
        samples_red.append(1.0 - r["adaptive"].samples / r["fixed"].samples)
        fixed_mj += r["fixed"].energy_mj
        adapt_mj += r["adaptive"].energy_mj
        if r["fixed"].detect_h is not None and r["adaptive"].detect_h is not None:
            delays.append((r["adaptive"].detect_h - r["fixed"].detect_h) * 60.0)
    days = 60.0
    return {
        "label": "SIMULATED 60-day runs, 1-2 surges each; energy uses ASSUMED per-event costs",
        "runs": runs,
        "mean_energy_saving": float(np.mean(savings)),
        "mean_sample_reduction": float(np.mean(samples_red)),
        "mean_detect_delay_min": float(np.mean(delays)) if delays else None,
        "max_detect_delay_min": float(np.max(delays)) if delays else None,
        "fixed_mean_power_uw": fixed_mj / runs / (days * 86400.0) * 1e3,
        "adaptive_mean_power_uw": adapt_mj / runs / (days * 86400.0) * 1e3,
    }


def live_section() -> dict | None:
    live = data.load_live_cache()
    if not live:
        return None
    r = sim.run_live(live)
    epochs = [int(v["epoch"][0]) for v in live.values()] + [
        int(v["epoch"][-1]) for v in live.values()
    ]
    leads = [e["lead_h"] for e in r["events"] if e["lead_h"] is not None]
    src = data.live_source() or {}
    if src.get("kind") == "foen40d":
        label = (
            "REAL 10-minute records, nothing injected (official FOEN/BAFU 40-day records, "
            "5-min values on the 10-min grid)"
        )
    else:
        label = "REAL 10-minute records, nothing injected (relay of FOEN real-time data)"
    return {
        "label": label,
        "source": src,
        "range": [data.epoch_to_iso(min(epochs)), data.epoch_to_iso(max(epochs))],
        "stations": len(live),
        "events": [{**e, "time": data.epoch_to_iso(e["epoch"])} for e in r["events"]],
        "median_lead_h": float(np.median(leads)) if leads else None,
        "mean_lead_h": float(np.mean(leads)) if leads else None,
        "natural": r["natural"],
        "peaking": r["peaking"],
    }


def travel_example() -> dict:
    """Illustrative reaches (ASSUMED geometry, not surveyed)."""
    pts = {
        "village A (6 km)": [Reach(6, 0.05, 10)],
        "town B (21 km)": [Reach(6, 0.05, 10), Reach(15, 0.02, 18)],
    }
    out = {}
    for q in (20.0, 60.0, 150.0):
        out[str(q)] = {k: travel_time_h(q, v) * 60.0 for k, v in pts.items()}
    return out


def run_all(live: bool = True, trials: int = 20, energy_runs: int = 12) -> dict:
    series = data.load_daily()
    res = {
        "daily_real": daily_section(series),
        "subdaily_sim": subdaily_section(trials),
        "energy_sim": energy_section(energy_runs),
        "travel_min": travel_example(),
    }
    if live:
        res["live_real"] = live_section()
    return res


def save(res: dict, path: Path | None = None) -> None:
    path = path or RESULTS
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(res, indent=1), encoding="utf-8")
