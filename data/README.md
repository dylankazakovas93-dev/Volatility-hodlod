# Data

This directory intentionally does **not** contain the large canonical NQ
bars file in this handoff repository/branch — it is too large for a normal
git object (211 MB) and is excluded via `.gitignore`. The small VXN file
*is* committed directly.

## Required files

| File | Size | SHA-256 | In this repo? |
|---|---|---|---|
| `nq_1m/nq_continuous_2018_2026_1m.csv` | ~211 MB | `3d0228fcc17a40933d4fdc3983a8153e5bb6445ed9e743919b3eb5c516e53880` | **No — place it yourself** |
| `vxn_daily_2018_2026.csv` | ~176 KB | `76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e` | Yes, committed |

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
