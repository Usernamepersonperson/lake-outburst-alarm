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

`python -m lakealarm fetch` writes `cache/live10min_<start>_<end>.json` from api.existenz.ch, an unofficial
relay of FOEN/BAFU real-time data. The relay states free use for public and non-commercial purposes and that
the original data owner may add licence restrictions. The FOEN terms of use could not be retrieved when this
repository was written, so the raw 10-minute data is not redistributed here. `data/results.json` contains
only derived values (event times, peak and median flows, lead times).
