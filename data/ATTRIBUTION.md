# Data attribution

## daily_q_subset.csv.gz (committed)

Daily discharge (m3/s), basin-mean precipitation (mm/d) and basin-mean air temperature (degC)
for 20 Swiss gauging stations, 1981-01-01 to 2020-12-31, columns `station,date,q_m3s,precip_mm,tmean_c`.
Missing discharge days are empty (precipitation and temperature are blanked on those days too).

- Source dataset: CAMELS-CH (Hoge, Kauzlaric, Siber, Schonenberger and co-authors), Zenodo record
  15025258 (published 2025-03-14), licence **CC BY 4.0** as stated in the record metadata.
- Discharge: Swiss Federal Office for the Environment (FOEN/BAFU) as distributed in CAMELS-CH.
  Precipitation and temperature: the gridded products used by CAMELS-CH (see its data description).
- Changes: subset of 20 of the 331 catchments, observation-based columns only, converted to one gz-CSV.
- Rebuild: download `camels_ch.zip` from the Zenodo record into `cache/`, unzip, then
  `python -c "from pathlib import Path; from lakealarm import data; data.build_fixture(Path('cache/camels_x/camels_ch'))"`.

## 10-minute real-time discharge (not committed)

Source: Abteilung Hydrologie, Bundesamt für Umwelt BAFU (FOEN), https://www.hydrodaten.admin.ch/,
data retrieved 2026-11-12.

`python -m lakealarm fetch` saves the official FOEN 40-day records (provisional raw data, 5-minute values) of
each station as served behind its station page into `cache/foen40d/<retrieval date>/<station>.json`. The
results in `data/results.json` use the records retrieved on 2026-11-12, 2026-10-02 22:00 to 2026-11-11
22:20 UTC, 9 stations (station 2269 has no 40-day record), keeping the values on the 10-minute grid.

Terms: the FOEN FAQ (https://www.hydrodaten.admin.ch/de/fragen, "Nutzungsbedingungen und Quellenangabe",
checked 2026-11-12) states that the data can be used freely and recommends naming the source, suggesting
"Abteilung Hydrologie, Bundesamt für Umwelt BAFU (retrieval date)". The FOEN conditions for current raw
hydrological data
(https://www.bafu.admin.ch/dam/de/sd-web/5NAitqNKub6m/allgemeine_bedingungenfuerdasherunterladenaktuellerhydrologische.pdf,
version of 16.09.2019) allow commercial and non-commercial use and recommend naming the source. The raw series
is kept out of the repository anyway (gitignored `cache/`); `data/results.json` contains only derived values
(event times, peak and median flows, alarm and lead times).

Alternative: `python -m lakealarm fetch --source relay` writes `cache/live10min_<start>_<end>.json` from
api.existenz.ch, an unofficial relay of the same FOEN data (last 32 days). The relay states free use for public
and non-commercial purposes and asks that FOEN/BAFU data be credited and linked. The first published results
(before 2026-11-12) used this relay; its window no longer covers the start of the 8 Oct 2026 Emme flood.

## Flood catalogue

The six flood windows in `lakealarm/events.py` and their sources are listed in the README
("Flood catalogue: dates and sources"); they were checked against FOEN and MeteoSwiss reports on 2026-11-11.
