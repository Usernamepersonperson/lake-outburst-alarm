"""Streaming rate-of-rise + CUSUM detector and a fixed-threshold baseline.

All times are in hours (float), so the same code runs on 5-minute or daily samples.
The signal is transformed to ``y = ln(q)`` (mode "log", for discharge) or ``y = q``
(mode "linear", for stage in metres). All thresholds are in ``y`` units.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class DetectorConfig:
    mode: str = "log"  # "log" (discharge) or "linear" (stage)
    rate_window_h: float = 3.0  # least-squares slope window
    rate_alarm_per_h: float = 0.15  # y units per hour (log: 0.15 = +16 %/h)
    min_rise: float = math.log(1.5)  # y above baseline needed to alarm
    cusum_k_per_h: float = 0.04  # allowed drift (diurnal melt) per hour
    cusum_h: float = 0.5  # CUSUM decision threshold, y units
    baseline_tau_h: float = 48.0  # time constant of the slow baseline
    floor: float = 1e-3  # lower clip before ln()

    def __post_init__(self) -> None:
        if self.mode not in ("log", "linear"):
            raise ValueError(f"mode must be 'log' or 'linear', got {self.mode!r}")
        for name in ("rate_window_h", "rate_alarm_per_h", "cusum_h", "baseline_tau_h"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0")
        if self.cusum_k_per_h < 0 or self.min_rise < 0:
            raise ValueError("cusum_k_per_h and min_rise must be >= 0")

    def with_(self, **kw) -> DetectorConfig:
        return replace(self, **kw)


@dataclass(frozen=True)
class Status:
    t_h: float
    alarm: bool
    rate: float  # y units per hour
    cusum: float  # y units
    rise: float  # y above slow baseline
    reason: str  # "", "rate", "cusum"


class RateOfRiseDetector:
    """Alarm when the level rises fast (rate rule) or persistently (CUSUM) above baseline."""

    def __init__(self, config: DetectorConfig | None = None) -> None:
        self.cfg = config or DetectorConfig()
        self.reset()

    def reset(self) -> None:
        self._win: deque[tuple[float, float]] = deque()
        self._baseline: float | None = None
        self._cusum = 0.0
        self._last: tuple[float, float] | None = None
        self._alarm = False

    def _y(self, value: float) -> float:
        if self.cfg.mode == "log":
            return math.log(max(value, self.cfg.floor))
        return value

    def _rate(self) -> float:
        pts = self._win
        n = len(pts)
        if n < 2:
            return 0.0
        mt = sum(p[0] for p in pts) / n
        my = sum(p[1] for p in pts) / n
        den = sum((p[0] - mt) ** 2 for p in pts)
        if den <= 0:
            return 0.0
        return sum((p[0] - mt) * (p[1] - my) for p in pts) / den

    def update(self, t_h: float, value: float) -> Status:
        if value is None or not math.isfinite(value):
            raise ValueError("value must be a finite number")
        if self._last is not None and t_h <= self._last[0]:
            raise ValueError("timestamps must be strictly increasing")
        cfg = self.cfg
        y = self._y(value)
        # window keeps the newest sample plus anything within rate_window_h; always >= 2 points
        self._win.append((t_h, y))
        while len(self._win) > 2 and t_h - self._win[0][0] > cfg.rate_window_h:
            self._win.popleft()
        rate = self._rate()
        if self._baseline is None:
            self._baseline = y
        rise = y - self._baseline
        if self._last is not None:
            dt = t_h - self._last[0]
            step = y - self._last[1]
            self._cusum = max(0.0, self._cusum + step - cfg.cusum_k_per_h * dt)
            # slow baseline: frozen while something is happening so a surge cannot absorb itself
            quiet = rate < 0.5 * cfg.rate_alarm_per_h and self._cusum < 0.5 * cfg.cusum_h
            if quiet and not self._alarm:
                a = 1.0 - math.exp(-dt / cfg.baseline_tau_h)
                self._baseline += a * (y - self._baseline)
            elif self._alarm and rate < 0.0:
                # recession: let the baseline follow the falling limb so the alarm can clear
                a = 1.0 - math.exp(-dt / (cfg.baseline_tau_h / 3.0))
                self._baseline += a * (y - self._baseline)
        reason = ""
        risen = rise >= cfg.min_rise
        if risen and rate >= cfg.rate_alarm_per_h:
            reason = "rate"
        elif risen and self._cusum >= cfg.cusum_h:
            reason = "cusum"
        if reason:
            self._alarm = True
        elif self._alarm and rate <= 0.0 and rise < cfg.min_rise:
            self._alarm = False  # latched until the level has fallen back
        self._last = (t_h, y)
        return Status(t_h, self._alarm, rate, self._cusum, rise, reason)

    @property
    def baseline(self) -> float | None:
        return self._baseline


class FixedThreshold:
    """Classic level alarm: fires when value >= level, clears below ``level - hysteresis``."""

    def __init__(self, level: float, hysteresis: float = 0.0) -> None:
        if hysteresis < 0:
            raise ValueError("hysteresis must be >= 0")
        self.level = level
        self.hysteresis = hysteresis
        self._alarm = False

    def update(self, value: float) -> bool:
        if not math.isfinite(value):
            raise ValueError("value must be a finite number")
        if value >= self.level:
            self._alarm = True
        elif value < self.level - self.hysteresis:
            self._alarm = False
        return self._alarm


def alarm_flags(times_h, values, detector) -> list[bool]:
    """Run a RateOfRiseDetector or FixedThreshold over a series; one alarm flag per sample."""
    out = []
    for t, v in zip(times_h, values, strict=True):
        if isinstance(detector, FixedThreshold):
            out.append(detector.update(float(v)))
        else:
            out.append(detector.update(float(t), float(v)).alarm)
    return out


def first_alarm_index(times_h, values, detector) -> int | None:
    """Index of the first alarm sample, or None."""
    for i, flag in enumerate(alarm_flags(times_h, values, detector)):
        if flag:
            return i
    return None


def onsets(times_h, triggers, merge_h: float) -> list[float]:
    """Times at which a trigger run starts; runs closer than ``merge_h`` are one episode."""
    out: list[float] = []
    last_on = None
    prev = False
    for t, on in zip(times_h, triggers, strict=True):
        if on:
            if not prev and (last_on is None or t - last_on > merge_h):
                out.append(float(t))
            last_on = float(t)
        prev = bool(on)
    return out
