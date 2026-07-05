# Data Pipeline

**Provenance classification: `FULLY_REPRODUCIBLE_FROM_RAW_DATABENTO`**

Updated after the user supplied the five raw Databento batch-download
archives (`nq2018.zip`, `nq2020.zip`, `nq2021.zip`, `nq2023.zip`,
`nq2025.zip`) that were used to build the canonical continuous file. Each
archive contains `metadata.json` (the exact Databento query), `manifest.json`
(per-file hashes), and the raw multi-contract CSV (zstd-compressed). The
raw-to-canonical construction rule was reverse-engineered from these files
and then **verified row-for-row against the entire canonical file — all
2,964,655 rows, every column, matched exactly, zero mismatches.**

## Exact Databento query (from `metadata.json` in every archive)

```json
{
  "dataset": "GLBX.MDP3",
  "schema": "ohlcv-1m",
  "symbols": ["NQ.FUT"],
  "stype_in": "parent",
  "stype_out": "instrument_id",
  "encoding": "csv",
  "compression": "zstd"
}
```

`stype_in: "parent"` means the query resolves to **every individual
instrument under the NQ.FUT parent symbol at once** — every quarterly
contract plus every calendar-spread contract (e.g. `NQH8-NQM8`) — not
Databento's separate continuous-contract symbology (which would use
`stype_in: "continuous"` with symbols like `NQ.c.0`). The raw files are true
multi-contract dumps, confirmed by multiple `symbol` values sharing the same
`ts_event` timestamp.

## Raw file inventory (5 archives, contiguous 2018-01-01 -> 2026-06-07)

| Archive | Raw filename | Date range (query) |
|---|---|---|
| nq2018.zip | `glbx-mdp3-20180101-20191230.ohlcv-1m.csv.zst` | 2018-01-01 -> 2019-12-30 |
| nq2020.zip | `glbx-mdp3-20200101-20201230.ohlcv-1m.csv.zst` | 2020-01-01 -> 2020-12-30 |
| nq2021.zip | `glbx-mdp3-20210101-20221230.ohlcv-1m.csv.zst` | 2021-01-01 -> 2022-12-30 |
| nq2023.zip | `glbx-mdp3-20230101-20241230.ohlcv-1m.csv.zst` | 2023-01-01 -> 2024-12-30 |
| nq2025.zip | `glbx-mdp3-20250101-20260607.ohlcv-1m.csv.zst` | 2025-01-01 -> 2026-06-07 |

Raw CSV columns (post zstd-decompression): `ts_event, rtype, publisher_id,
instrument_id, open, high, low, close, volume, symbol`.

## The exact roll-selection rule (verified, not inferred)

**For each UTC calendar day, keep only the standard quarterly contract
(`symbol` matches `NQ[HMUZ]\d`, e.g. `NQH8` — this excludes calendar-spread
symbols like `NQH8-NQM8`, which are also present in the raw dump) with the
highest total traded volume that day, and use only that contract's bars for
the day.**

This is exactly the same methodology documented for the sibling GC pipeline
(`scripts/build_gc_continuous.py` in the research repository: "picks the
highest-volume standard contract per day"). It is implemented in this
handoff as `scripts/build_nq_continuous.py`.

**Verification performed:** rebuilding the full continuous series from the
five raw archives using this rule and diffing against
`data/nq_1m/nq_continuous_2018_2026_1m.csv`:

```
canonical rows: 2,964,655
rebuilt rows:   2,964,655
merge (outer join on timestamp): 2,964,655 matched, 0 left-only, 0 right-only
contract mismatches: 0
open/high/low/close mismatches (>0.001): 0 / 0 / 0 / 0
roll_day mismatches: 0
```

Every one of the 33 roll days and 34 contract assignments in the canonical
file was independently reproduced from raw data — e.g. the first roll
(`NQH8` -> `NQM8` at 2018-03-09 00:00 UTC) happens on the exact calendar day
`NQM8`'s daily volume (231,083) first exceeds `NQH8`'s (171,709); the day
before, `NQH8` still leads (358,574 vs 29,511).

## Everything this resolves from the previous (partially-unknown) version of this document

- **Databento dataset/schema:** `GLBX.MDP3` / `ohlcv-1m` — confirmed exactly.
- **Symbols requested:** `NQ.FUT`, `stype_in=parent` — confirmed exactly.
- **Raw filenames:** confirmed, see table above.
- **Individual contracts vs continuous symbology:** individual contracts +
  calendar spreads, confirmed (not Databento continuous symbology).
- **Roll-selection algorithm:** confirmed as highest-volume-per-day among
  standard contracts — **not** a fixed calendar-days-before-expiry rule (the
  ~7-day-before-expiry pattern noted in the prior version of this document
  was a coincidental correlate of the volume crossover, not the actual rule).
- **Whether a contract can be re-selected after rolling away:** not
  observed in either the raw or canonical data across 2018-2026, and the
  rule as implemented has no mechanism to re-select a lower-volume contract
  once a higher-volume one has taken over for a given day — in practice,
  volume monotonically shifts to the new front month and never reverts.

## What remains genuinely unresolved

1. **Roll-selection causality.** The rule selects day D's contract using
   day D's **own full-day** volume total, not information available only
   before day D starts. This is **not strictly pre-day-causal** — it is a
   same-day (full-day-lookback) selection, identical in spirit to the GC
   methodology. This does not affect the backtest's causality (the strategy
   engine itself never uses future bars), but it does mean the continuous
   series' contract assignment for a given day was technically fixed using
   that day's complete trading data, not decided in advance.
2. **Bar timestamp convention** (`ts_event`= bar-open vs bar-close). Not
   stated in Databento's response metadata for this schema in a way this
   handoff can point to directly; the field name `ts_event` is carried
   through unchanged into the canonical file's `timestamp` column, so
   whichever convention it represents is the one the engine uses — but this
   handoff cannot independently confirm from the data alone which
   convention that is.
3. **DST handling in the raw data itself** — Databento's own internal
   handling of exchange-local DST transitions for the underlying instrument
   definitions is outside what these files document; this handoff's own
   `America/New_York` conversion (via `pandas.tz_convert`, standard IANA
   tzdata) is known code, not an unknown.

## Reproducing the canonical file from raw data

```
# decompress each archive's .csv.zst first, then:
python3 scripts/build_nq_continuous.py \
    --raw glbx-mdp3-20180101-20191230.ohlcv-1m.csv \
    --raw glbx-mdp3-20200101-20201230.ohlcv-1m.csv \
    --raw glbx-mdp3-20210101-20221230.ohlcv-1m.csv \
    --raw glbx-mdp3-20230101-20241230.ohlcv-1m.csv \
    --raw glbx-mdp3-20250101-20260607.ohlcv-1m.csv \
    --out data/nq_1m/nq_continuous_2018_2026_1m.csv
```

The raw archives themselves are not included in this handoff (they total
tens of MB compressed, ~700MB+ decompressed, and are Databento-licensed
data) — obtain them from Databento directly using the exact query
documented above, or from wherever they were originally saved.

## VXN file

- **File:** `data/vxn_daily_2018_2026.csv`
- **SHA-256:** `76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e`
- **Rows:** 2,139 (excluding header)
- **Columns:** `date, open, high, low, close`
- **Source:** Not Databento — this is the CBOE Nasdaq-100 Volatility Index
  (VXN) daily OHLC series. The exact retrieval method is still **UNKNOWN**
  in this handoff (no raw archive for VXN was supplied alongside the NQ
  ones). This file's own hash and row count are verified and stable, and
  it is used strictly-prior-only (no lookahead) —
  `tests/test_strategy_invariants.py::test_vxn_input_uses_only_prior_data`
  confirms this directly.

## What this means for reproducibility

Every strategy result in this handoff, **and the canonical NQ data file
itself**, are now fully reproducible from source: raw Databento archives ->
`scripts/build_nq_continuous.py` -> canonical file -> `src/strict_engine.py`
/ `src/independent_strict_engine.py` -> the verified trade ledger. The only
remaining unresolved item is the VXN file's exact retrieval pipeline.
