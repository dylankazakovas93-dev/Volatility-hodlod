# Data

This directory intentionally does **not** contain the large canonical bars
files in this repository/branch — they are too large for normal git objects
and are excluded via `.gitignore`. Small volatility index files *are*
committed directly.

## Required files (NQ strategy)

| File | Size | SHA-256 | In this repo? |
|---|---|---|---|
| `nq_1m/nq_continuous_2018_2026_1m.csv` | ~211 MB | `3d0228fcc17a40933d4fdc3983a8153e5bb6445ed9e743919b3eb5c516e53880` | **No — place it yourself** |
| `vxn_daily_2018_2026.csv` | ~176 KB | `76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e` | Yes, committed |

## Required files (ES/VIX strategy)

| File | Size | SHA-256 | In this repo? |
|---|---|---|---|
| `es_1m/es_continuous_2018_2026_1m.csv` | ~190 MB | `c38d850aa63172aceb03be283dc8b0f5911db73fb1ec87a250b0771d8cb078dd` | **No — build from raw archives** |
| `vix_raw_cboe_official.csv` | ~460 KB | `3a909bc8987edd6b6c08873a09abcc74c9697aa1b93004d6725475e21e7164b6` | Yes, committed |
| `vix_daily_1990_2026.csv` | ~312 KB | `af8e7d8e1d139ed258f2a117df54c76464277866cd5466cd256e89ac629746a1` | Yes, committed |

### Building the ES continuous file

Requires the raw Databento ES archives (`es2018.zip`, `es2023.zip`, `es2026.zip`)
and the build script:

```
python3 scripts/build_es_continuous.py \
    --zip /path/to/es2018.zip \
    --zip /path/to/es2023.zip \
    --zip /path/to/es2026.zip \
    --out data/es_1m/es_continuous_2018_2026_1m.csv
```

The raw archives are available in the canonical data library at
`/workspaces/quant-stack/data/raw/ES/`.

## Getting the NQ bars file

This handoff does not include a portable retrieval script for the raw NQ
data (see `docs/DATA_PIPELINE.md` for exactly what is and isn't known about
its construction). You must obtain `nq_continuous_2018_2026_1m.csv`
out-of-band (e.g. copy it from wherever the research repository's
`data/nq_1m/` directory lives, or re-request the equivalent continuous
series from your Databento account) and place it at:

```
data/nq_1m/nq_continuous_2018_2026_1m.csv
```

Then verify it before trusting any result:

```
python3 scripts/build_or_verify_data.py \
    --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
    --vxn  data/vxn_daily_2018_2026.csv
```

This must print `DATA VERIFICATION: PASS`. If the hash or row count does
not match, do not proceed — you do not have the canonical dataset, and no
downstream number in this handoff will reproduce.

No Git LFS or other special storage is used or required — the file is
simply excluded from version control and must be transferred out-of-band.
