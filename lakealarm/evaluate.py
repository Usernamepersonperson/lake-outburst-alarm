"""Evaluation on real daily data: confirmed events, lead time vs fixed threshold, false alarms."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .data import DailySeries
from .detect import DetectorConfig, RateOfRiseDetector
from .events import ConfirmedEvent, exclusion_mask

RAIN_MM = 15.0  # basin-mean precipitation on the alarm day or the day before => "rain-driven"


def daily_config(
    rise_per_day: float = 1.6, min_ratio: float = 1.5, cusum_ratio: float = 2.0
) -> DetectorConfig:
    """Detector tuned for 24 h samples. ``rise_per_day`` is the factor per day that trips the
    rate rule; ``cusum_ratio`` is the cumulative factor that trips the CUSUM."""
    return DetectorConfig(
        mode="log",
        rate_window_h=48.0,
        rate_alarm_per_h=math.log(rise_per_day) / 24.0,
        min_rise=math.log(min_ratio),
        cusum_k_per_h=math.log(1.15) / 24.0,
        cusum_h=math.log(cusum_ratio),
        baseline_tau_h=14 * 24.0,
    )


_FLAG_CACHE: dict[tuple[int, DetectorConfig], tuple[DailySeries, np.ndarray]] = {}


def run_daily(s: DailySeries, cfg: DetectorConfig) -> np.ndarray:
    """Alarm flag per day. The detector is reset across missing values. Results are memoised
    per (series object, config) because the sweeps below revisit the same pairs."""
    hit = _FLAG_CACHE.get((id(s), cfg))
    if hit is not None and hit[0] is s:
        return hit[1]
    det = RateOfRiseDetector(cfg)
    flags = np.zeros(len(s.days), dtype=bool)
    hours = s.hours
    for i, q in enumerate(s.q):
        if not math.isfinite(q):
            det.reset()
            continue
        flags[i] = det.update(float(hours[i]), float(q)).alarm
    _FLAG_CACHE[(id(s), cfg)] = (s, flags)
    return flags


def rising_edges(flags: np.ndarray) -> np.ndarray:
    prev = np.concatenate([[False], flags[:-1]])
    return np.flatnonzero(flags & ~prev)


@dataclass(frozen=True)
class FalseAlarmReport:
    alarms: int
    station_years: float
    rain_driven: int
    dry: int

    @property
    def per_station_year(self) -> float:
        return self.alarms / self.station_years if self.station_years else float("nan")


def false_alarms(
    series: dict[str, DailySeries],
    cfg: DetectorConfig,
    year_from: int = 1981,
    year_to: int = 2020,
    station_ids: list[str] | None = None,
) -> FalseAlarmReport:
    """Alarm onsets on days outside every catalogue flood window, per station-year."""
    alarms = rain = 0
    years = 0.0
    for sid, s in series.items():
        if station_ids is not None and sid not in station_ids:
            continue
        yrs = s.days.astype("datetime64[Y]").astype(int) + 1970
        keep = (yrs >= year_from) & (yrs <= year_to) & ~exclusion_mask(s) & np.isfinite(s.q)
        years += float(keep.sum()) / 365.25
        for i in rising_edges(run_daily(s, cfg)):
            if not keep[i]:
                continue
            alarms += 1
            p = np.nansum(s.precip[max(i - 1, 0) : i + 1])
            rain += int(p >= RAIN_MM)
    return FalseAlarmReport(alarms, years, rain, alarms - rain)


@dataclass(frozen=True)
class EventLead:
    event: ConfirmedEvent
    detector_day: int | None  # days before the peak day (positive = early)
    fixed_day: int | None
    lead_days: int | None  # fixed_day - detector_day, None if either missed


def fixed_level(s: DailySeries, pct: float = 99.0) -> float:
    return float(np.nanpercentile(s.q, pct))


def event_leads(
    series: dict[str, DailySeries],
    events: list[ConfirmedEvent],
    cfg: DetectorConfig,
    pct: float = 99.0,
    search_days: int = 7,
) -> list[EventLead]:
    """For each confirmed event: first alarm of detector and of a fixed percentile threshold
    in [peak - search_days, peak + 1]. Days are expressed as days before the peak."""
    out = []
    cache: dict[str, np.ndarray] = {}
    for ev in events:
        s = series[ev.station]
        if ev.station not in cache:
            cache[ev.station] = run_daily(s, cfg)
        flags = cache[ev.station]
        lo = max(ev.peak_idx - search_days, 0)
        hi = min(ev.peak_idx + 1, len(s.days) - 1)
        edges = set(rising_edges(flags).tolist())
        det = next((i for i in range(lo, hi + 1) if i in edges), None)
        lvl = fixed_level(s, pct)
        fix = next((i for i in range(lo, hi + 1) if s.q[i] >= lvl), None)
        d = None if det is None else ev.peak_idx - det
        f = None if fix is None else ev.peak_idx - fix
        out.append(EventLead(ev, d, f, None if d is None or f is None else d - f))
    return out


GRID = (
    (1.6, 1.8, 2.0, 2.5, 3.0),  # rise factor per day
    (1.5, 2.0, 2.5, 3.0),  # min ratio over baseline
    (3.0, 4.0, 5.0, 6.0),  # cumulative CUSUM ratio
)


def tune_daily(
    series: dict[str, DailySeries],
    year_from: int = 1981,
    year_to: int = 2000,
    dry_budget: float = 0.1,
    grid=GRID,
    station_ids: list[str] | None = None,
) -> tuple[DetectorConfig, tuple[float, float, float], float]:
    """Pick the most sensitive daily setting whose DRY-weather false alarms on the training
    years stay under ``dry_budget`` per station-year. No event data is used."""
    best = None
    for rise in grid[0]:
        for min_ratio in grid[1]:
            for cusum in grid[2]:
                key = (rise, min_ratio, cusum)
                if best is not None and key >= best[0]:
                    continue
                cfg = daily_config(rise, min_ratio, cusum)
                rep = false_alarms(series, cfg, year_from, year_to, station_ids)
                dry_rate = rep.dry / rep.station_years
                if dry_rate <= dry_budget:
                    best = (key, cfg, dry_rate)
    if best is None:
        raise RuntimeError("no setting meets the dry-weather false-alarm budget")
    return best[1], best[0], best[2]
