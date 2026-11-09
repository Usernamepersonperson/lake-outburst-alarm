"""Battery-aware adaptive sampling: sample fast when rising, slow when quiet."""

from __future__ import annotations

from dataclasses import dataclass

from .detect import DetectorConfig, Status


@dataclass(frozen=True)
class SamplerConfig:
    base_s: float = 1800.0  # quiet interval
    fast_s: float = 300.0  # interval while rising
    hold_s: float = 6 * 3600.0  # stay fast this long after the last trigger
    enter_frac: float = 0.6  # trigger at this fraction of the alarm thresholds
    low_battery_frac: float = 0.2
    low_battery_base_mult: float = 2.0  # stretch the quiet interval when the battery is low

    def __post_init__(self) -> None:
        if not 0 < self.fast_s <= self.base_s:
            raise ValueError("need 0 < fast_s <= base_s")
        if self.hold_s < 0 or not 0 < self.enter_frac <= 1:
            raise ValueError("hold_s >= 0 and 0 < enter_frac <= 1 required")
        if self.low_battery_base_mult < 1:
            raise ValueError("low_battery_base_mult must be >= 1")


class AdaptiveSampler:
    """Chooses the next sampling interval from the detector status."""

    def __init__(self, detector_cfg: DetectorConfig, config: SamplerConfig | None = None) -> None:
        self.dcfg = detector_cfg
        self.cfg = config or SamplerConfig()
        self._fast_until_h = float("-inf")

    def rising(self, st: Status) -> bool:
        f = self.cfg.enter_frac
        return (
            st.alarm
            or (st.rate >= f * self.dcfg.rate_alarm_per_h and st.rise > 0)
            or st.cusum >= f * self.dcfg.cusum_h
        )

    def next_interval_s(self, st: Status, battery_frac: float = 1.0) -> float:
        if not 0.0 <= battery_frac <= 1.0:
            raise ValueError("battery_frac must be in [0, 1]")
        if self.rising(st):
            self._fast_until_h = st.t_h + self.cfg.hold_s / 3600.0
        if st.t_h < self._fast_until_h:
            return self.cfg.fast_s
        base = self.cfg.base_s
        if battery_frac < self.cfg.low_battery_frac:
            base *= self.cfg.low_battery_base_mult
        return base


@dataclass(frozen=True)
class EnergyModel:
    """Per-event energy. Defaults are ASSUMED round numbers for a low-power radar level
    sensor with a LoRa-class radio, not measurements of any specific hardware."""

    sample_mj: float = 20.0  # wake + measure
    uplink_mj: float = 150.0  # one radio uplink
    sleep_uw: float = 20.0  # sleep power, micro-watts

    def total_mj(self, n_samples: int, n_uplinks: int, duration_s: float) -> float:
        if min(n_samples, n_uplinks) < 0 or duration_s < 0:
            raise ValueError("counts and duration must be >= 0")
        return (
            n_samples * self.sample_mj
            + n_uplinks * self.uplink_mj
            + self.sleep_uw * 1e-3 * duration_s
        )
