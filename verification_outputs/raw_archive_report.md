# Raw Databento Archive Verification Report

Verifier: Claude, branch `verification/claude-baseline-v1`, checked out from
handoff commit `a375818056ca435df021d60b111f5f58b1f3551f`.

## Archive inventory

| Archive | job_id | Compressed filename | Decompressed filename | Compressed SHA-256 (vs manifest.json) |
|---|---|---|---|---|
| nq2018.zip | GLBX-20260609-BFRKLJWR9U | glbx-mdp3-20180101-20191230.ohlcv-1m.csv.zst | glbx-mdp3-20180101-20191230.ohlcv-1m.csv | MATCH (e55c1737...) |
| nq2020.zip | GLBX-20260609-QVFT5M33E5 | glbx-mdp3-20200101-20201230.ohlcv-1m.csv.zst | glbx-mdp3-20200101-20201230.ohlcv-1m.csv | MATCH (738b6575...) |
| nq2021.zip | GLBX-20260608-3QFYEF9JWB | glbx-mdp3-20210101-20221230.ohlcv-1m.csv.zst | glbx-mdp3-20210101-20221230.ohlcv-1m.csv | MATCH (5012a9f1...) |
| nq2023.zip | GLBX-20260608-9W6GDSCJF4 | glbx-mdp3-20230101-20241230.ohlcv-1m.csv.zst | glbx-mdp3-20230101-20241230.ohlcv-1m.csv | MATCH (fbc646a1...) |
| nq2025.zip | GLBX-20260608-SDAEXE8C4W | glbx-mdp3-20250101-20260607.ohlcv-1m.csv.zst | glbx-mdp3-20250101-20260607.ohlcv-1m.csv | MATCH (4a56638d...) |

All 5 compressed `.zst` files' SHA-256 match their own `manifest.json` exactly.
zstd decompression is deterministic and lossless, so the decompressed CSVs
are guaranteed bit-identical to whatever Databento originally delivered for
these job IDs.

## metadata.json query verification (all 5 archives)

Every archive's `metadata.json` specifies exactly:

```json
{"dataset": "GLBX.MDP3", "schema": "ohlcv-1m", "symbols": ["NQ.FUT"],
 "stype_in": "parent", "stype_out": "instrument_id",
 "encoding": "csv", "compression": "zstd"}
```

Query `start`/`end` (ns epoch) decode to the documented date ranges exactly
(end is exclusive):

| Archive | start (UTC) | end (UTC, exclusive) | Documented range |
|---|---|---|---|
| nq2018 | 2018-01-01 | 2019-12-31 | 2018-01-01 -> 2019-12-30 |
| nq2020 | 2020-01-01 | 2020-12-31 | 2020-01-01 -> 2020-12-30 |
| nq2021 | 2021-01-01 | 2022-12-31 | 2021-01-01 -> 2022-12-30 |
| nq2023 | 2023-01-01 | 2024-12-31 | 2023-01-01 -> 2024-12-30 |
| nq2025 | 2025-01-01 | 2026-06-08 | 2025-01-01 -> 2026-06-07 |

## Raw CSV structure

Columns (all 5 files): `ts_event, rtype, publisher_id, instrument_id, open,
high, low, close, volume, symbol` -- matches documented schema exactly.

| Archive | Raw rows | First ts_event | Last ts_event | Distinct symbols | Standard outrights (NQ[HMUZ]\d) | Spread symbols |
|---|---|---|---|---|---|---|
| nq2018 | 942,559 | 2018-01-01T23:00:00Z | 2019-12-30T23:59:00Z | 37 | 12 | 25 |
| nq2020 | 487,719 | 2020-01-01T23:00:00Z | 2020-12-30T23:59:00Z | 21 | 8  | 13 |
| nq2021 | 1,028,959 | 2021-01-03T23:00:00Z | 2022-12-30T21:59:00Z | 35 | 12 | 23 |
| nq2023 | 1,025,448 | 2023-01-02T23:00:00Z | 2024-12-30T23:59:00Z | 38 | 13 | 25 |
| nq2025 | 741,444 | 2025-01-01T23:00:00Z | 2026-06-07T23:59:00Z | 29 | 12 | 17 |

Standard quarterly outrights (H/M/U/Z codes) and calendar-spread instruments
(e.g. `NQH3-NQM3`) both confirmed present in every archive, as documented.

## Independent roll-rule audit

An independently coded script (`independent_daily_contract_selection.csv` in
this directory; plain Python `csv`/dict aggregation, does NOT import or call
`scripts/build_nq_continuous.py`) recomputed the "highest standard-contract
volume per UTC day" rule from scratch across all 5 raw files:

- 2,624 trading days
- **34 distinct selected contracts** (matches claim)
- **33 contract changes / roll days** (matches claim)
- **Zero same-day volume ties** found between any two standard contracts
  across the entire 2018-2026 span (checked explicitly)

## Caveats (per instructions, must not be silently changed)

1. The roll-selection rule uses each day's own full-day volume total, not
   pre-day information -- **not strictly pre-day-causal**, as documented.
2. The VXN file's exact original retrieval pipeline remains unresolved (hash
   and row count verified; the fetch method is not).
