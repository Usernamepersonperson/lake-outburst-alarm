"""Simple kinematic travel-time estimate from an upstream alarm to downstream points."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reach:
    """A uniform river reach, wide rectangular channel approximation."""

    length_km: float
    slope: float  # m/m
    width_m: float
    manning_n: float = 0.045  # steep gravel/boulder stream

    def __post_init__(self) -> None:
        if self.length_km <= 0 or self.slope <= 0 or self.width_m <= 0 or self.manning_n <= 0:
            raise ValueError("reach parameters must all be > 0")


def manning_velocity(q_m3s: float, reach: Reach) -> float:
    """Mean velocity (m/s) for discharge ``q`` from Manning's equation, wide channel (R ~ depth).

    q = w * h * v and v = h^(2/3) * sqrt(S) / n  =>  v = (q * S^(3/4) / (w * n^(3/2))) ** (2/5)
    """
    if q_m3s <= 0:
        raise ValueError("discharge must be > 0")
    return (q_m3s * reach.slope**0.75 / (reach.width_m * reach.manning_n**1.5)) ** 0.4


def wave_celerity(q_m3s: float, reach: Reach) -> float:
    """Kinematic wave celerity (m/s); for Manning in a wide channel it is 5/3 of mean velocity."""
    return (5.0 / 3.0) * manning_velocity(q_m3s, reach)


def travel_time_h(q_m3s: float, reaches: list[Reach]) -> float:
    """Hours for the flood front to cross all ``reaches`` in order at discharge ``q``."""
    if not reaches:
        raise ValueError("need at least one reach")
    return sum(r.length_km * 1000.0 / wave_celerity(q_m3s, r) for r in reaches) / 3600.0


def arrival_times_h(
    t_alarm_h: float, q_m3s: float, points: dict[str, list[Reach]]
) -> dict[str, float]:
    """Expected arrival time of the surge front at each named downstream point."""
    return {name: t_alarm_h + travel_time_h(q_m3s, rs) for name, rs in points.items()}
