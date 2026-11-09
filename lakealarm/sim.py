"""SIMULATED surges and backgrounds, plus the sub-daily lead-time / energy experiments.

Everything here that is synthetic is labelled as such in the outputs. The live-data experiment
(`run_live`) superimposes nothing: it uses real 10-minute records as they are.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .detect import DetectorConfig, FixedThreshold, RateOfRiseDetector, onsets
from .sampling import AdaptiveSampler, EnergyModel, SamplerConfig

FIXED_FACTOR = 2.5  # fixed-threshold alarm level = this x the background median
DT_H = 10.0 / 60.0  # reference fixed sampling interval, hours


def fast_config() -> DetectorConfig:
    """Detector for 5-30 minute sampling."""
    return DetectorConfig(
        mode="log",
        rate_window_h=3.0,
        rate_alarm_per_h=0.12,
        min_rise=math.log(1.5),
        cusum_k_per_h=0.025,
        cusum_h=0.6,
        baseline_tau_h=36.0,
    )


def background_1min(
    days: float,
    base: float,
    seed: int,
    diurnal_amp: float = 0.3,
    noise_cv: float = 0.02,
    drift_cv: float = 0.1,
) -> np.ndarray:
    """SIMULATED background at 1-min resolution: diurnal melt cycle + slow drift + noise."""
    if days <= 0 or base <= 0:
        raise ValueError("days and base must be > 0")
    rng = np.random.default_rng(seed)
    n = int(days * 1440)
    t_h = np.arange(n) / 60.0
    phase = rng.uniform(0, 2 * math.pi)
    diurnal = diurnal_amp * np.sin(2 * math.pi * t_h / 24.0 + phase)
    # slow drift: random walk on a 6-hour grid, interpolated
    k = int(days * 4) + 2
    walk = np.cumsum(rng.normal(0, drift_cv / 4.0, k))
    walk -= walk.mean()
    drift = np.interp(t_h, np.arange(k) * 6.0, walk)
    noise = rng.normal(0, noise_cv, n)
    return base * np.exp(diurnal * 0.5 + drift + noise)


def surge_shape(t_h: np.ndarray, t0_h: float, rise_h: float, decay_h: float) -> np.ndarray:
    """Unit hydrograph 0..1: convex (exponential-type) rising limb, exponential recession.

    Outburst floods through ice tunnels grow roughly exponentially until the lake is drained;
    this is a deliberately simple stand-in, not a calibrated physical model.
    """
    if rise_h <= 0 or decay_h <= 0:
        raise ValueError("rise_h and decay_h must be > 0")
    x = (t_h - t0_h) / rise_h
    k = 3.0
    rising = (np.exp(k * np.clip(x, 0, 1)) - 1.0) / (math.exp(k) - 1.0)
    falling = np.exp(-np.clip(t_h - t0_h - rise_h, 0, None) / decay_h)
    return np.where(x < 0, 0.0, np.where(x <= 1, rising, falling))


def inject_surge(
    q: np.ndarray, step_min: float, t0_h: float, peak_ratio: float, rise_h: float, decay_h: float
) -> np.ndarray:
    """Add a SIMULATED surge so the peak is ``peak_ratio`` x the local background level."""
    if peak_ratio <= 1:
        raise ValueError("peak_ratio must be > 1")
    t_h = np.arange(len(q)) * step_min / 60.0
    local = float(np.median(q))
    return q + local * (peak_ratio - 1.0) * surge_shape(t_h, t0_h, rise_h, decay_h)


@dataclass(frozen=True)
class SurgeResult:
    detector_h: float | None  # hours after surge start at which the rate-of-rise alarm fired
    fixed_h: float | None
    lead_h: float | None


def _first_hit(t_h: np.ndarray, q: np.ndarray, det, after_h: float) -> float | None:
    for t, v in zip(t_h, q, strict=True):
        hit = det.update(float(v)) if isinstance(det, FixedThreshold) else det.update(t, v).alarm
        if hit and t >= after_h:
            return float(t)
    return None


def run_surge(
    peak_ratio: float,
    rise_h: float,
    seed: int,
    cfg: DetectorConfig | None = None,
    step_min: float = 10.0,
    diurnal_amp: float = 0.3,
    fixed_factor: float = FIXED_FACTOR,
) -> SurgeResult:
    """One trial: SIMULATED background + SIMULATED surge at 3.5 days, fixed 10-min sampling."""
    cfg = cfg or fast_config()
    base = 10.0
    bg = background_1min(7.0, base, seed, diurnal_amp=diurnal_amp)
    t0 = 84.0 + (seed % 7)  # hours; varies the diurnal phase at onset
    q1 = inject_surge(bg, 1.0, t0, peak_ratio, rise_h, decay_h=max(rise_h, 3.0))
    s = int(step_min)
    q = q1[::s]
    t_h = np.arange(len(q)) * step_min / 60.0
    ref = float(np.median(bg))
    d = _first_hit(t_h, q, RateOfRiseDetector(cfg), t0)
    f = _first_hit(t_h, q, FixedThreshold(fixed_factor * ref), t0)
    lead = None if d is None or f is None else f - d
    return SurgeResult(None if d is None else d - t0, None if f is None else f - t0, lead)


def lead_grid(
    peaks=(3.0, 5.0, 10.0),
    rises=(2.0, 6.0, 12.0, 24.0),
    trials: int = 20,
    cfg: DetectorConfig | None = None,
    fixed_factor: float = FIXED_FACTOR,
) -> list[dict]:
    rows = []
    for rise in rises:
        for peak in peaks:
            res = [
                run_surge(peak, rise, seed=1000 + i, cfg=cfg, fixed_factor=fixed_factor)
                for i in range(trials)
            ]
            leads = [r.lead_h for r in res if r.lead_h is not None]
            rows.append(
                {
                    "rise_h": rise,
                    "peak_ratio": peak,
                    "trials": trials,
                    "detected": sum(r.detector_h is not None for r in res),
                    "fixed_detected": sum(r.fixed_h is not None for r in res),
                    "median_lead_h": float(np.median(leads)) if leads else None,
                    "median_detect_h": float(
                        np.median([r.detector_h for r in res if r.detector_h is not None])
                    )
                    if any(r.detector_h is not None for r in res)
                    else None,
                }
            )
    return rows


def sim_false_alarms(
    years: float = 5.0, diurnal_amp: float = 0.3, cfg: DetectorConfig | None = None, seed: int = 7
) -> tuple[int, float]:
    """Alarm onsets per simulated station-year on a SIMULATED surge-free background."""
    cfg = cfg or fast_config()
    n_chunks = int(round(years * 365 / 30))
    count = 0
    for c in range(n_chunks):
        bg = background_1min(30.0, 10.0, seed + c, diurnal_amp=diurnal_amp)[::10]
        det = RateOfRiseDetector(cfg)
        prev = False
        for i, v in enumerate(bg):
            a = det.update(i * DT_H, float(v)).alarm
            if a and not prev:
                count += 1
            prev = a
    return count, n_chunks * 30 / 365.0


# --------------------------------------------------------------------------- sampling / energy


@dataclass(frozen=True)
class EnergyResult:
    samples: int
    uplinks: int
    energy_mj: float
    detect_h: float | None  # first alarm minus surge start (hours), None if missed
    fast_samples: int = 0


def _run_sampler(
    q1: np.ndarray,
    t0_h: float,
    adaptive: bool,
    cfg: DetectorConfig,
    scfg: SamplerConfig,
    model: EnergyModel,
) -> EnergyResult:
    """Walk a 1-min series with either fixed 10-min sampling or the adaptive rule."""
    det = RateOfRiseDetector(cfg)
    sampler = AdaptiveSampler(cfg, scfg)
    n = len(q1)
    t_s = 0.0
    samples = uplinks = fast_samples = 0
    last_up_s = 0.0
    detect = None
    while t_s < (n - 1) * 60.0:
        v = float(q1[int(t_s // 60)])
        st = det.update(t_s / 3600.0, v)
        samples += 1
        if adaptive:
            interval = sampler.next_interval_s(st)
            fast_samples += int(interval <= scfg.fast_s)
        else:
            interval = 600.0
        # fast samples are buffered; the radio is used hourly and on every sample while alarmed
        if st.alarm or t_s - last_up_s >= 3600.0:
            uplinks += 1
            last_up_s = t_s
        if st.alarm and detect is None and t_s / 3600.0 >= t0_h:
            detect = t_s / 3600.0 - t0_h
        t_s += interval
    return EnergyResult(
        samples, uplinks, model.total_mj(samples, uplinks, n * 60.0), detect, fast_samples
    )


def energy_comparison(
    days: float = 60.0,
    surges: int = 2,
    seed: int = 11,
    cfg: DetectorConfig | None = None,
    scfg: SamplerConfig | None = None,
    model: EnergyModel | None = None,
) -> dict:
    """SIMULATED ``days`` of background plus ``surges`` surges: fixed 10-min vs adaptive."""
    cfg = cfg or fast_config()
    scfg = scfg or SamplerConfig()
    model = model or EnergyModel()
    rng = np.random.default_rng(seed)
    bg = background_1min(days, 10.0, seed)
    q = bg.copy()
    starts = np.sort(rng.uniform(5 * 24, days * 24 - 5 * 24, surges))
    # keep surges far apart
    starts = np.array([s for i, s in enumerate(starts) if i == 0 or s - starts[i - 1] > 48])
    first = float(starts[0])
    for s0 in starts:
        q = inject_surge(q, 1.0, float(s0), float(rng.uniform(3, 8)), float(rng.uniform(3, 12)), 6)
    fixed = _run_sampler(q, first, False, cfg, scfg, model)
    adapt = _run_sampler(q, first, True, cfg, scfg, model)
    return {
        "days": days,
        "surges": len(starts),
        "fixed": fixed,
        "adaptive": adapt,
        "saving": 1.0 - adapt.energy_mj / fixed.energy_mj if fixed.energy_mj else 0.0,
    }


# --------------------------------------------------------------------------- real 10-min data


def find_live_events(
    t_h: np.ndarray, q: np.ndarray, ratio: float = 2.5, sep_h: float = 48.0
) -> list[int]:
    """Peaks of a REAL 10-minute record that exceed ``ratio`` x the median of the window
    [peak-96 h, peak-24 h]; used to confirm an event from the hydrograph alone."""
    out: list[int] = []
    order = np.argsort(-q)
    for i in order:
        if q[i] <= 0:
            break
        if any(abs(t_h[i] - t_h[j]) < sep_h for j in out):
            continue
        m = (t_h >= t_h[i] - 96) & (t_h <= t_h[i] - 24)
        if m.sum() < 50:
            continue
        if q[i] >= ratio * float(np.median(q[m])):
            out.append(int(i))
        if len(out) >= 6:
            break
    return sorted(out)


def _peaking(t_epoch: np.ndarray, peak_idx: list[int], tol_h: float = 1.5) -> bool:
    """True if >= 3 event peaks fall at nearly the same hour of day (recurring release pattern)."""
    if len(peak_idx) < 3:
        return False
    hod = np.array([(int(t_epoch[i]) % 86400) / 3600.0 for i in peak_idx])
    for h in hod:
        d = np.abs(((hod - h) + 12.0) % 24.0 - 12.0)
        if int((d <= tol_h).sum()) >= 3:
            return True
    return False


def run_live(
    live: dict[str, dict[str, np.ndarray]],
    cfg: DetectorConfig | None = None,
    fixed_factor: float = FIXED_FACTOR,
    merge_h: float = 12.0,
) -> dict:
    """REAL 10-minute records, nothing injected.

    Per station: events are peaks confirmed from the hydrograph (``find_live_events``). Stations
    whose events recur at the same hour of day are labelled "peaking" (regulated releases) and
    reported separately. Lead = fixed-threshold alarm time minus detector alarm time, both
    searched in [peak - 36 h, peak + 1 h]. False alarms are detector onsets (episodes merged
    within ``merge_h``) more than 36 h from any confirmed event of the same station.
    """
    cfg = cfg or fast_config()
    events = []
    natural = {"false_alarms": 0, "hours": 0.0, "stations": 0}
    peaking = {"false_alarms": 0, "hours": 0.0, "stations": 0, "alarms": 0}
    for sid, v in live.items():
        t_h, q = v["t_h"], v["flow"]
        ref = float(np.median(q))
        evs = find_live_events(t_h, q)
        is_peaking = _peaking(v["epoch"], evs)
        fixed_lvl = fixed_factor * ref
        det = RateOfRiseDetector(cfg)
        trig = [bool(det.update(float(t), float(x)).reason) for t, x in zip(t_h, q, strict=True)]
        alarm_t = onsets(t_h, trig, merge_h)
        fx = FixedThreshold(fixed_lvl)
        fixed_flags = [fx.update(float(x)) for x in q]
        if not is_peaking:
            for i in evs:
                lo, hi = t_h[i] - 36.0, t_h[i] + 1.0
                d = next((t for t in alarm_t if lo <= t <= hi), None)
                f = next(
                    (
                        float(t)
                        for t, a in zip(t_h, fixed_flags, strict=True)
                        if a and lo <= t <= hi
                    ),
                    None,
                )
                events.append(
                    {
                        "station": sid,
                        "epoch": int(v["epoch"][i]),
                        "peak_q": float(q[i]),
                        "ref_q": ref,
                        "detector_t": d,
                        "fixed_t": f,
                        "lead_h": None if d is None or f is None else f - d,
                    }
                )
        ev_t = [t_h[i] for i in evs]
        far = [t for t in alarm_t if all(abs(t - e) > 36.0 for e in ev_t)]
        bucket = peaking if is_peaking else natural
        bucket["false_alarms"] += len(far)
        bucket["hours"] += float(t_h[-1] - t_h[0])
        bucket["stations"] += 1
        if is_peaking:
            bucket["alarms"] += len(alarm_t)
    for b in (natural, peaking):
        b["station_years"] = b["hours"] / 24.0 / 365.25
    return {"events": events, "natural": natural, "peaking": peaking}
