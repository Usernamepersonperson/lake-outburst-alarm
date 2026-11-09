"""Data access: committed daily fixture (CAMELS-CH subset) and a 10-minute real-time fetcher."""

from __future__ import annotations

import csv
import gzip
import json
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "data" / "daily_q_subset.csv.gz"
CACHE = ROOT / "cache"
CAMELS_ZIP_URL = "https://zenodo.org/api/records/15025258/files/camels_ch.zip/content"

# gauge_id -> (water body, place, catchment glacier fraction class)
GLACIER_FED = {
    "2161": ("Massa", "Blatten bei Naters"),
    "2268": ("Rhone", "Gletsch"),
    "2269": ("Lonza", "Blatten"),
    "2351": ("Vispa", "Visp"),
    "2219": ("Simme", "Oberried / Lenk"),
    "2256": ("Rosegbach", "Pontresina"),
    "2117": ("Drance de Bagnes", "Le Chable-Villette"),
    "2299": ("Alpbach", "Erstfeld-Bodenberg"),
    "2346": ("Rhone", "Brig"),
    "2262": ("Berninabach", "Pontresina"),
    "2109": ("Lutschine", "Gsteig"),
    "2200": ("Weisse Lutschine", "Zweilutschinen"),
    "2419": ("Rhone", "Reckingen"),
    "2019": ("Aare", "Brienzwiler"),
}
RAIN_FED = {
    "2070": ("Emme", "Emmenmatt"),
    "2084": ("Muota", "Ingenbohl"),
    "2176": ("Sihl", "Zurich-Sihlholzli"),
    "2185": ("Plessur", "Chur"),
    "2355": ("Landwasser", "Davos-Frauenkirch"),
    "2364": ("Ticino", "Piotta"),
}
STATIONS = {**GLACIER_FED, **RAIN_FED}

# 10-minute real-time stations (FOEN ids) for the optional live background
LIVE_STATIONS = ["2351", "2346", "2269", "2268", "2109", "2200", "2419", "2161", "2070", "2084"]
LIVE_API = "https://api.existenz.ch/apiv1/hydro/daterange"


@dataclass
class DailySeries:
    station: str
    days: np.ndarray  # datetime64[D]
    q: np.ndarray  # m3/s, NaN where missing
    precip: np.ndarray  # basin precipitation mm/d
    tmean: np.ndarray  # basin mean air temperature degC

    @property
    def hours(self) -> np.ndarray:
        return (self.days - self.days[0]).astype("int64") * 24.0

    @property
    def years(self) -> float:
        return float(np.isfinite(self.q).sum()) / 365.25


def _f(x: str) -> float:
    try:
        return float(x)
    except ValueError:
        return float("nan")


def build_fixture(camels_dir: Path, out: Path = FIXTURE) -> int:
    """Extract the chosen stations from an unzipped CAMELS-CH folder into one small gz-CSV."""
    obs = camels_dir / "timeseries" / "observation_based"
    n = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["station", "date", "q_m3s", "precip_mm", "tmean_c"])
        for sid in STATIONS:
            with open(obs / f"CAMELS_CH_obs_based_{sid}.csv", encoding="utf-8") as src:
                rd = csv.DictReader(src)
                for row in rd:
                    q = row["discharge_vol(m3/s)"]
                    w.writerow(
                        [
                            sid,
                            row["date"],
                            q if q != "NaN" else "",
                            row["precipitation(mm/d)"] if q != "NaN" else "",
                            row["temperature_mean(degC)"] if q != "NaN" else "",
                        ]
                    )
                    n += 1
    return n


def load_daily(path: Path = FIXTURE) -> dict[str, DailySeries]:
    """Load the fixture into per-station arrays on a gap-free daily axis."""
    rows: dict[str, list[tuple[str, float, float, float]]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.setdefault(r["station"], []).append(
                (r["date"], _f(r["q_m3s"]), _f(r["precip_mm"]), _f(r["tmean_c"]))
            )
    out = {}
    for sid, lst in rows.items():
        days = np.array([d for d, *_ in lst], dtype="datetime64[D]")
        out[sid] = DailySeries(
            sid,
            days,
            np.array([x[1] for x in lst]),
            np.array([x[2] for x in lst]),
            np.array([x[3] for x in lst]),
        )
    return out


def parse_live(payload: dict) -> dict[str, dict[str, np.ndarray]]:
    """Parse an existenz.ch hydro payload into {station: {"t_h": hours, "flow": m3/s}}.

    Rows with a non-numeric or negative value are dropped; times are sorted and de-duplicated.
    """
    by: dict[str, dict[int, float]] = {}
    for row in payload.get("payload", []):
        if row.get("par") != "flow":
            continue
        try:
            v = float(row["val"])
            ts = int(row["timestamp"])
        except (KeyError, TypeError, ValueError):
            continue
        if not np.isfinite(v) or v < 0:
            continue
        by.setdefault(str(row["loc"]), {})[ts] = v
    out = {}
    for loc, d in by.items():
        ts = np.array(sorted(d))
        out[loc] = {"t_h": (ts - ts[0]) / 3600.0, "epoch": ts, "flow": np.array([d[t] for t in ts])}
    return out


def fetch_live(start: date, end: date, cache: Path = CACHE) -> dict[str, Path]:
    """Download 10-minute discharge for LIVE_STATIONS into cache/ (never committed)."""
    cache.mkdir(exist_ok=True)
    locs = ",".join(LIVE_STATIONS)
    url = (
        f"{LIVE_API}?locations={locs}&parameters=flow&startdate={start}&enddate={end}"
        "&app=lake-outburst-alarm&version=0.1"
    )
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 (fixed https URL)
        payload = json.load(resp)
    out = {}
    path = cache / f"live10min_{start}_{end}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    out["raw"] = path
    return out


def load_live_cache(cache: Path = CACHE) -> dict[str, dict[str, np.ndarray]]:
    files = sorted(cache.glob("live10min_*.json"))
    if not files:
        return {}
    return parse_live(json.loads(files[-1].read_text(encoding="utf-8")))


def epoch_to_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
