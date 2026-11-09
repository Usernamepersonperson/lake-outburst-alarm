# lake-outburst-alarm

A rate-of-rise alarm for glacial-lake outbursts and sudden river surges, built for low-power level sensors downstream: it watches how fast the water climbs, not how high it is, and it samples faster only while the water is rising.

![result](docs/figure.png)

Panels A, C: real FOEN/BAFU data. Panels B, D: simulated surges (labelled as such).

## What it does

- **Rate-of-rise detector** on discharge (log scale) or stage (linear): least-squares slope over a short window, plus a slow baseline that freezes while a surge is under way.
- **CUSUM change detector** for slower, persistent rises that stay under the rate threshold.
- **Fixed-level alarm** as the baseline to compare against.
- **Travel-time estimate** from the sensor to downstream points (Manning, wide channel, kinematic wave celerity 5/3 of mean velocity).
- **Battery-aware sampling rule**: quiet interval 30 min, 5 min while rising (held for 6 h), quiet interval doubled when the battery is low; fast samples are buffered, the radio is used hourly and while alarmed.

Pure Python + numpy, streaming (one sample in, one status out), so the same code can be ported to a microcontroller.

## Results

All numbers come from `python -m lakealarm demo` (written to `data/results.json`).

| What | Result | Data |
|---|---|---|
| Lead over a fixed level alarm, **real 10-min surge** (Weisse Lutschine, 25 Oct 2026) | **+1.5 h** (alarm at -5.0 h vs -3.5 h before the peak) | real, FOEN/BAFU, 10-min |
| Same, all 6 real station-events in 32 days (3 natural-flow stations) | median **+1.4 h**, range -1.8 h to +9.8 h | real, 2026-10-08 to 2026-11-09 |
| Lead over a fixed alarm at 2.5x median, simulated 5x surge | 0.2 h (24 h rise) to 2.7 h (12 h rise); 24 h rise with 3x peak: detected 14/20 | simulated, 20 trials per cell |
| Same against a fixed alarm at 4x median | 0.8 h (2 h rise) to 5.6 h (24 h rise); the fixed alarm missed every 3x surge | simulated |
| Lead on **real daily data**, 87 confirmed flood station-events | 0.4 d mean where both alarmed (8 earlier, 30 same day, 2 later); detector alarmed on 48/87, fixed P99 level on 56/87 | real, CAMELS-CH 1981-2020 |
| **Dry-weather false alarms**, glacier-fed stations, test years 2001-2020 | **0.09 per station-year** (26 alarms, 279 station-years) | real daily |
| All alarms outside flood windows, glacier-fed / rain-fed, 2001-2020 | 0.60 / 4.24 per station-year; 84 % / 96 % of them rain-driven (real unlabelled floods, counted as false for a lake alarm) | real daily |
| False alarms, simulated surge-free background (diurnal amplitude 30 % and 60 %) | 0 in 5 simulated station-years each | simulated |
| False alarms on real 10-min records, natural-flow stations | 7 in 0.52 station-years | real, 6 stations, 32 days |
| Same, stations with a daily release pattern | 34 alarms in 0.26 station-years: not usable there | real, 3 stations |
| Adaptive sampling vs fixed 10 min | **-62 % samples** (144 to 54 per day); energy **-17 %**, mean power 98 to 81 uW under **assumed** costs (20 mJ per sample, 150 mJ per uplink, 20 uW sleep); detection never later than fixed (mean -4.6 min, max 0 min), 12 runs | simulated |
| Travel time, assumed reaches (6 km and 21 km), 20 to 150 m3/s | 17 to 8 min and 90 to 40 min | assumed geometry |

Reading the table honestly: at daily resolution the rise happens inside one sample, so there is almost no lead over a high fixed level; the benefit shows at 10-minute resolution and for slow rises. The detector is tuned for lake-outburst-like surges, so every rain flood is also an alarm.

## Quick start

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"   # Linux/macOS: .venv/bin/python
python -m lakealarm demo            # reproduces the numbers above, writes docs/*.png
python -m lakealarm demo --no-figures --no-live
python -m lakealarm travel --q 100 --length-km 10 --slope 0.04 --width-m 12
python -m lakealarm fetch           # optional: last 32 days of real 10-min data into cache/
python -m lakealarm tune            # re-derive the daily setting (about 10 minutes)
python -m pytest -q                 # 79 tests
```

```python
from lakealarm import DetectorConfig, RateOfRiseDetector

det = RateOfRiseDetector(DetectorConfig())
status = det.update(t_hours, discharge_m3s)  # status.alarm, status.reason, status.rate
```

`demo` without a `cache/live10min_*.json` skips the live part. The 10-minute window moves on every day, so only the numbers in `data/results.json` are frozen; the committed daily fixture reproduces everything else exactly.

## How it works

```mermaid
flowchart LR
  S[level / discharge sample] --> Y[y = ln q]
  Y --> R[slope over 3 h]
  Y --> C[CUSUM vs drift allowance]
  Y --> B[slow baseline, frozen in a surge]
  R --> A{rise over baseline and rate or CUSUM over limit}
  C --> A
  B --> A
  A --> P[alarm + travel time to downstream points]
  R --> M[sampling rule: 30 min quiet, 5 min rising]
  C --> M
```

- Alarm when `ln q` is at least `ln 1.5` above the baseline **and** the slope is at least 0.12 per hour (about +13 % per hour) **or** the CUSUM (allowance 0.025 per hour, limit 0.6) is over its limit. The latch clears when the level falls back.
- The daily setting (factor 2.0 per day, 3.0 over baseline, CUSUM 5.0) is the most sensitive grid point with at most 0.1 dry-weather false alarms per station-year on **1981-2000**; no event data was used. The 2001-2020 years are the held-out test. Re-run with `python -m lakealarm tune`.
- Fixed baseline: the daily P99 of the station (real daily data), or 2.5x the station median (10-minute and simulated data). 4x is shown as the more typical warning-level case.
- "Rain-driven" means basin precipitation of at least 15 mm on the alarm day or the day before (from CAMELS-CH).
- Confirmed events: a catalogue window of a widely reported Swiss flood (1987-08, 1993-09, 1999-05, 2000-10, 2005-08, 2020-10) counts at a station only if that station's daily peak inside the window is at least 2.5x the median of the 30 days ending 3 days before. That gave 87 of 120 possible station-events (median peak ratio 3.3 to 6.7 per flood). Real 10-minute events are peaks of at least 2.5x the median of the window 24 to 96 h before. A real flood is not a lake outburst; it is used here because it is a verifiable sudden surge.

## Data sources

| Data | Used for | Source and licence |
|---|---|---|
| Daily discharge, basin precipitation and temperature, 20 gauges, 1981-2020 | event confirmation, lead time, false alarms | **CAMELS-CH** (Hoge, Kauzlaric, Siber, Schonenberger et al.), Zenodo record 15025258, **CC BY 4.0**. Discharge originates from the Swiss Federal Office for the Environment (FOEN/BAFU). Subset committed as `data/daily_q_subset.csv.gz` (2.7 MB). Source: FOEN/BAFU via CAMELS-CH. |
| 10-minute discharge, 10 stations, last about 32 days | real surge example, real 10-min false alarms | FOEN/BAFU real-time data through the unofficial relay api.existenz.ch (stated free for public and non-commercial use, "additional licensing restrictions may apply by the original data owner"). The FOEN terms of use could not be fetched when this was written, so the raw data is **not committed**: `python -m lakealarm fetch` downloads it into the gitignored `cache/`. Source: FOEN/BAFU. |
| Simulated surges and background | lead-time grid, simulated false alarms, energy | generated by `lakealarm/sim.py`, seeded, labelled simulated everywhere |

Historic 10-minute FOEN data is **not openly downloadable**: the FOEN portal shows the last 40 days and the current-year tables, older data is ordered from its Hydrological Data Service. That is why long-record results here are daily, and sub-daily results use simulated surges or the 32-day real window. See `data/ATTRIBUTION.md`.

## What is not verified yet

- **This is not an official warning system** and must not be used as one. It has no field deployment, no customers and no review by a hydrology service.
- **No real glacial-lake outburst is in the evaluation.** I checked the Mattervispa / Vispa gauge at Visp (it integrates the Gornersee catchment) for 2004 and 2005; Gornersee drains almost every year within a few days (Huss et al. 2007, J. Glaciol.), but the drainage is not identifiable in the daily means of a 786 km2 regulated catchment, so I did not claim any Gornersee date. Outburst-shaped surges are simulated, with a simple exponential rising limb that is not calibrated to any lake.
- The real surges are rain floods. The flood-window dates are from widely reported events and were **not cross-checked against a citation**; the hydrograph check is the only confirmation (87 of 120 possible station-events pass).
- Real 10-minute evidence is small: 32 days, 9 stations, 6 events at 3 stations, 5 of them on two days (21 and 25 Oct 2026). The lead range is -1.8 h to +9.8 h and the large values come from a low-flow station with a very low fixed level.
- At 10-minute resolution the detector fired 7 times on natural-flow stations in 0.52 station-years; at stations downstream of regulated releases (a repeating daily peak) it fires about daily. Do not install it there without a release filter.
- Rain floods are alarms by design; the daily test shows 4.2 alarms per station-year at rain-fed stations.
- Energy numbers use **assumed** per-event costs, not measured hardware. Sample reduction (-62 %) is a count and does not depend on them.
- Travel-time reaches are made-up geometry; Manning roughness and the wide-channel assumption are not validated against any survey.
- FOEN terms of use for redistribution of the daily subset were not independently checked; I rely on the CC BY 4.0 licence on the CAMELS-CH record.
- Detector thresholds were tuned on daily data and checked on a 20-year hold-out, but not on 10-minute multi-year records.

## Licence

MIT, Copyright (c) 2026 Victor Bonilla. The daily data subset keeps its own licence (CC BY 4.0, see above).
