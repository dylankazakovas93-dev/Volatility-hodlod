# Data Pipeline

**Provenance classification: `CANONICAL_FILE_VERIFIED_BUT_RAW_CONSTRUCTION_PARTIALLY_UNKNOWN`**

The canonical NQ file (`data/nq_1m/nq_continuous_2018_2026_1m.csv`) is
hash-verified, byte-stable, and every trading-strategy result in this
handoff is reproducible from it. What is **not** fully recoverable is the
exact raw-Databento-to-canonical construction procedure, because the raw
multi-contract source file(s) are not present in this handoff (or in the
research repository this was extracted from) — only the already-built
continuous file is. Everything below is either read directly from the file
itself (proven) or stated as unknown (not guessed).

## What is proven from the file itself

- **Row count:** 2,964,655
- **SHA-256:** `3d0228fcc17a40933d4fdc3983a8153e5bb6445ed9e743919b3eb5c516e53880`
- **First timestamp:** `2018-01-01T23:00:00.000000000Z`
- **Last timestamp:** `2026-06-07T23:59:00.000000000Z`
- **Columns:** `timestamp, open, high, low, close, volume, contract, roll_day`
- **Timestamp format:** ISO-8601 with a literal `Z` suffix (UTC). Whether
  each timestamp marks bar-**open** or bar-**close** is **UNKNOWN** — no
  metadata field in the file states this, and it cannot be determined from
  OHLC values alone.
- **34 distinct `contract` values**, all of the form `NQ<month><year-digit>`
  with month codes limited to `H` (Mar), `M` (Jun), `U` (Sep), `Z` (Dec) —
  i.e. only the standard **quarterly** NQ contracts appear. No micro (`MNQ`)
  or calendar-spread symbols are present in this file.
- **`roll_day` flag:** 33 rows are flagged `roll_day=1` (one fewer than the
  34 contracts, as expected — the first contract has no roll *into* it).
  These 33 timestamps are the exact minutes the `contract` column changes
  value; there is no ambiguity about *when* a roll happened in this file,
  only about *why* that particular minute was chosen (see Unknowns below).
- **Unadjusted / not back-adjusted:** verified directly — at the first roll
  (`NQH8` -> `NQM8`, 2018-03-09 00:00 UTC) price jumps from 6976.00 to
  7001.75 with no adjustment applied to prior `NQH8` bars. Every roll in the
  file behaves the same way: the file is a straight concatenation of
  front-month segments, not a ratio- or difference-adjusted series.
- **No zero-volume rows:** `volume.min() == 1` across all 2,964,655 rows.
- **Missing-bar handling: bars are omitted, not filled.** Gap analysis on
  consecutive timestamps shows the file is *not* one row per calendar
  minute — 1-minute steps dominate (2,960,239 of 2,964,673 gaps), but there
  are also 1,642 exactly-61-minute gaps (consistent with the CME Globex
  daily maintenance break, ~17:00-18:00 ET) and 385 weekend-length gaps
  (~2 days 1 hour, consistent with Friday-close-to-Sunday-reopen). No
  synthetic/carried-forward bars exist for no-trade minutes; they are
  simply absent rows, not zero-volume filler rows.
- **Roll-timing pattern (empirical, quarterly):** every roll happens
  approximately **7 calendar days before** the outgoing contract's 3rd-Friday
  expiration (e.g. `NQH8`->`NQM8` on 2018-03-09, with March 2018 expiry on
  2018-03-16). This pattern holds across all 33 rolls in the file. This is
  consistent with a fixed calendar-offset-before-expiry roll rule (a common
  convention for continuous futures), but the file alone cannot prove
  whether the selection was actually calendar-based or happened to coincide
  with a volume-crossover day — see Unknowns.
- **Timestamps sort strictly ascending** with no duplicate timestamps found
  (`tests/test_data.py::test_bars_no_duplicate_timestamps` verifies this
  directly against the live file).
- **Loaded and converted to `America/New_York`** by `src/data_loader.py`'s
  `load_1m_ohlcv()`, which the engine consumes exclusively in that
  timezone — this conversion step is fully in this handoff's code, not an
  unknown.

## What is explicitly UNKNOWN — do not treat these as resolved

1. **Exact Databento dataset/schema identifiers** (e.g. the specific
   `dataset=GLBX.MDP3`, `schema=ohlcv-1m` request parameters, or equivalent)
   used to pull the raw data. Not recorded anywhere in this handoff or the
   research repository.
2. **Raw filenames** of the original multi-contract Databento dump(s) for
   NQ. A sibling GC pipeline in the research repository documents its raw
   filename (`glbx-mdp3-20230601-20260531.ohlcv-1m.csv.zst`) and a
   `scripts/build_gc_continuous.py` builder script; **no equivalent NQ
   filename or builder script exists** anywhere that was found.
3. **Exact roll-selection algorithm.** The GC pipeline's documented rule is
   "highest traded volume among standard contracts, per day." Whether the
   NQ file was built with that same volume-crossover rule, or with a fixed
   calendar-days-before-expiry rule (which the observed ~7-day-before-expiry
   pattern is also consistent with), cannot be distinguished without the raw
   multi-contract source data to check volume crossover against the
   observed roll dates.
4. **Whether the roll rule is causal** (i.e., decided using only
   information available at or before the roll date) cannot be verified
   without the raw multi-contract data — the *observed* pattern is
   consistent with a causal rule, but this handoff cannot prove it.
5. **Whether a contract can be re-selected after rolling away from it.**
   Not observed in this file (each of the 34 contracts appears in exactly
   one contiguous block), but the underlying selection code (if
   volume-based) is not available to confirm this is enforced rather than
   coincidental.
6. **Bar timestamp convention** (open-stamped vs close-stamped). Unknown —
   see above.
7. **DST handling in the original build.** The file's timestamps are UTC;
   `America/New_York` conversion (with DST) is applied by this handoff's
   own `load_1m_ohlcv()`, which is known code. Whether the *original*
   contract-roll timestamps were selected using a DST-aware or DST-naive
   local-time boundary is not documented anywhere found.
8. **Duplicate-timestamp handling policy during construction.** No
   duplicates exist in the final file (verified), but whether the build
   process de-duplicated raw ticks/bars, and by what rule, is unknown.

## VXN file

- **File:** `data/vxn_daily_2018_2026.csv`
- **SHA-256:** `76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e`
- **Rows:** 2,140 (including header)
- **Columns:** `date, open, high, low, close`
- **Source:** Not Databento — this is the CBOE Nasdaq-100 Volatility Index
  (VXN) daily OHLC series. The exact retrieval method (direct CBOE, a data
  vendor, or a scraping script) is **UNKNOWN** in this handoff; no fetch
  script for VXN specifically was found (a sibling `scripts/fetch_gvz.py`
  exists for the unrelated GVZ/gold-vol index in the research repository,
  fetching from Yahoo Finance's `^GVZ` as a FRED substitute, but there is no
  equivalent documented VXN fetcher).
- `src/level_generation.py`'s `generate_levels()` uses the VXN close from
  the most recent trading day **strictly before** the NQ session date (no
  lookahead) — verified directly by
  `tests/test_strategy_invariants.py::test_vxn_input_uses_only_prior_data`.

## What this means for reproducibility

You can fully reproduce every strategy result in this handoff starting from
the canonical files (hash-verified). You **cannot** currently reproduce the
canonical files themselves starting from raw Databento data using anything
in this handoff, because the raw-to-canonical build step's exact rule is
not fully documented anywhere available. If you need to extend this dataset
(e.g. add 2026 H2 data), you must either locate the original build script
(not present here) or write a new one and explicitly verify it reproduces
the existing file's contract assignments and roll days before trusting the
extension.
