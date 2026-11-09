"""Event catalogue and hydrograph confirmation.

Each catalogue entry is only a date WINDOW for a named, widely reported Swiss flood. An event
counts at a station only if the hydrograph itself confirms it (see ``confirm_event``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .data import DailySeries

# label, window start, window end (inclusive, YYYY-MM-DD)
FLOOD_WINDOWS = [
    ("1987-08 storm floods", "1987-08-23", "1987-08-26"),
    ("1993-09 Valais floods", "1993-09-22", "1993-09-25"),
    ("1999-05 Pentecost floods", "1999-05-20", "1999-05-23"),
    ("2000-10 Valais floods", "2000-10-13", "2000-10-16"),
    ("2005-08 storm floods", "2005-08-21", "2005-08-23"),
    ("2020-10 storm floods", "2020-10-02", "2020-10-04"),
]

CONFIRM_RATIO = 2.5  # peak daily flow >= this x the pre-event 30-day median
PRE_DAYS = 30
GAP_DAYS = 3  # baseline window ends this many days before the catalogue window


@dataclass(frozen=True)
class ConfirmedEvent:
    station: str
    label: str
    peak_idx: int
    peak_day: str
    peak_q: float
    base_q: float
    ratio: float
    precip_mm: float


def confirm_event(
    s: DailySeries, label: str, start: str, end: str, ratio: float = CONFIRM_RATIO
) -> ConfirmedEvent | None:
    """Confirm a catalogue window from the station's own daily hydrograph.

    Rule: the daily peak inside [start-1 d, end+1 d] must be >= ``ratio`` x the median daily
    flow of the 30 days ending 3 days before ``start``. Returns None if it is not met or if
    data are missing.
    """
    d0 = np.datetime64(start)
    d1 = np.datetime64(end)
    if d0 < s.days[0] + np.timedelta64(PRE_DAYS + GAP_DAYS, "D") or d1 > s.days[-1]:
        return None
    i0 = int(np.searchsorted(s.days, d0)) - 1
    i1 = int(np.searchsorted(s.days, d1)) + 1
    win = s.q[i0 : i1 + 1]
    if not np.isfinite(win).any():
        return None
    pk = int(np.nanargmax(win)) + i0
    b1 = int(np.searchsorted(s.days, d0)) - GAP_DAYS
    base = s.q[b1 - PRE_DAYS : b1]
    if np.isfinite(base).sum() < PRE_DAYS * 0.8:
        return None
    bq = float(np.nanmedian(base))
    if bq <= 0 or s.q[pk] < ratio * bq:
        return None
    pr = s.precip[max(pk - 1, 0) : pk + 1]
    return ConfirmedEvent(
        s.station,
        label,
        pk,
        str(s.days[pk]),
        float(s.q[pk]),
        bq,
        float(s.q[pk] / bq),
        float(np.nansum(pr)),
    )


def confirm_all(series: dict[str, DailySeries]) -> list[ConfirmedEvent]:
    out = []
    for label, a, b in FLOOD_WINDOWS:
        for s in series.values():
            ev = confirm_event(s, label, a, b)
            if ev:
                out.append(ev)
    return out


def exclusion_mask(s: DailySeries, pad_before: int = 3, pad_after: int = 7) -> np.ndarray:
    """True for days inside any catalogue window (padded) - removed from the non-event set."""
    m = np.zeros(len(s.days), dtype=bool)
    for _, a, b in FLOOD_WINDOWS:
        i0 = int(np.searchsorted(s.days, np.datetime64(a))) - pad_before
        i1 = int(np.searchsorted(s.days, np.datetime64(b))) + pad_after
        m[max(i0, 0) : i1 + 1] = True
    return m
