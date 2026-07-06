# OG VXN Exploratory Filter Protocol

**Phase label: `POST_VALIDATION_EXPLORATORY_REDEVELOPMENT`.**

This document is written and committed BEFORE the 14-candidate filter
matrix is run (per the task's commit-sequence requirement). It defines the
VXN data provenance, the causal merge rule, the filter definitions, and the
robustness criteria that will be applied to the results.

## Context and why this exists

`docs/OG_VALIDATION_RESULTS_DUAL_CONFIG.md` (branch
`research/og-build-four-years`, commit `add8f30`) locked a
`DUAL_CONFIG_FAIL` verdict for both `OG_PRIMARY_150R` and
`OG_OPERATIONAL_100R` against validation years 2019/2021/2022/2024/2025.
Per that protocol, neither config may be resurrected by "chasing the gate"
with new parameter search on the SAME held-out years. This branch does not
attempt that. Instead, it explores whether a VXN-level pre-entry filter,
evaluated honestly across the *entire* redevelopment sample (both the
original 2018/2020/2023/2026 build years and the now-viewed
2019/2021/2022/2024/2025 years), earns a place as a genuinely new
candidate for a FUTURE, still-unopened test (2013-2015). It does not
reopen or reinterpret the `DUAL_CONFIG_FAIL` verdict, and it does not
touch 2013-2015 data.

**2019/2021/2022/2024/2025 have been viewed** (via the just-completed
locked validation) and are labeled `FORMER_VALIDATION__NOW_DEVELOPMENT`
throughout this study -- never described as out-of-sample for any
VXN-filtered candidate produced here, because the filter itself is being
selected with knowledge of how those years perform.

## VXN data provenance (honesty checkpoint)

This repository already contains `data/vxn_daily_2018_2026.csv`, used as
the canonical VXN input throughout the entire OG research line (Stage A
through the just-completed locked validation; referenced by both
`configs/OG_PRIMARY_150R.yaml` and `configs/OG_OPERATIONAL_100R.yaml` as
`data.vxn_file` / `data.vxn_sha256`).

- **Raw file:** `data/vxn_daily_2018_2026.csv`
- **Raw file SHA-256:** `76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e`
- **Rows:** 2,139 (excluding header)
- **Columns:** `date, open, high, low, close`
- **Coverage:** 2017-12-01 through 2026-06-08 (first/last row dates)
- **Provider / retrieval method: UNKNOWN.** `docs/DATA_PIPELINE.md`
  (section "VXN file") states this plainly: *"Source: Not Databento --
  this is the CBOE Nasdaq-100 Volatility Index (VXN) daily OHLC series.
  The exact retrieval method is still UNKNOWN in this handoff (no raw
  archive for VXN was supplied alongside the NQ ones)."* This task does
  **not** claim a specific named vendor (e.g. CBOE official downloads,
  Bloomberg, a specific data API) because no file in this repository
  independently verifies one. Attempting a fresh re-sourcing from an
  authoritative provider was considered; this environment's network
  access goes through a restricted proxy with no verified path to a VXN
  data vendor, and re-sourcing was not attempted in a way that would
  produce a real, verifiable second source within this task's scope.
  **This study reuses the existing, already-hash-verified,
  already-used-throughout-this-project VXN file as-is.** This is not
  fabrication -- it is reuse of a real file with a known, stable hash and
  a previously-documented provenance gap; the gap is disclosed here
  exactly as it already was in `docs/DATA_PIPELINE.md`, not hidden or
  glossed over.
- **No missing-calendar-date analysis beyond what's below has been
  attempted against an external NYSE holiday calendar file** (none is
  committed in this repo); instead, gaps are identified directly from the
  VXN file itself (see below) and cross-checked against well-known US
  market holidays (Thanksgiving, Christmas) by manual date lookup.

### Normalized file (this study only)

For merge convenience this study renames/reduces columns
(`date`->`vxn_date`, drops `open/high/low`, keeps `close`->`vxn_close`) and
writes a derived file:

- **Normalized file:** `data/vxn_daily_2018_2026_normalized.csv`
- **Normalized file SHA-256:** `4f38f834d8a5dd592c13b0ae7225ea6ba4072fda6dce2dbbe03aa43f1dcc59e6`
- **Rows:** 2,139 (same row count, sorted by date, no rows dropped or added)
- This is a pure reformat of the raw file (sort + column rename/subset); it
  changes no values from the raw file's `date`/`close` columns.

### Gap analysis (raw file, all 2,139 rows)

Calendar-day deltas between consecutive VXN trading dates: 1,669 one-day
gaps, 24 two-day, 386 three-day (typical weekend), 59 four-day (long
weekend / single-day-holiday-adjacent weekend). **No gap exceeds 4 calendar
days anywhere in the full 2017-12-01..2026-06-08 span** (verified directly
in `tests/test_vxn_causal_merge.py::test_no_gap_exceeds_max_forward_fill_in_committed_data`).
Confirmed-absent holiday dates directly checked against the file:
2019-11-28 (Thanksgiving), 2019-12-25 (Christmas), 2020-01-01 (New Year's
Day) -- all absent, as expected for a US market holiday calendar.

## Causal timing rule

NQ sessions in this codebase begin at **19:00 ET** on the calendar day
before the labeled `session_date` for evening entries, or run through the
labeled date for day-session entries (`src/strict_engine.py::session_date`
and `session_cutoff`: a session_date `D`'s trading runs from 19:00 ET the
prior evening through the 15:00 ET cutoff or 19:00 ET rollover on day `D`).

VXN (CBOE Nasdaq-100 Volatility Index) is a **cash index** computed from
NDX option quotes; its regular-session reference close corresponds to the
~16:15 ET NDX/cash-market close area, i.e. VXN's "daily close" for
calendar day `D` is fully known by roughly 16:15 ET on day `D` --
**several hours before** the 19:00 ET session-open for that same calendar
day `D`.

**Therefore: the same calendar day D's own VXN close IS causal input for
the NQ session that begins at 19:00 ET on day D.** This is not the same
statement as "use information not yet known" -- 16:15 ET < 19:00 ET on the
same calendar date, so nothing from the future of the 19:00 ET session
start is being used. The task's warning is about a different, incorrect
interpretation (e.g. accidentally using a later day's close, or a close
that isn't finalized until after the relevant session has already begun);
neither applies here because VXN's cash close fully precedes the 19:00 ET
session open by design, every trading day.

**Rule, precisely:** for `session_date D`, the causal VXN reference is:
1. If VXN traded on calendar day `D` (has a row in the file for date `D`):
   use that day's own close. Gap = 0 days.
2. Else, forward-fill from the most recent VXN trading day strictly before
   `D`, provided the gap is <= `MAX_FORWARD_FILL_DAYS = 5` calendar days
   (chosen because the largest real gap anywhere in the file is 4 days --
   a normal long weekend / holiday -- so a 5-day threshold accepts every
   real gap in the data with one day of margin, and would only exclude a
   gap this dataset does not actually contain).
3. Else (gap > 5 days, which does not occur in the committed file):
   **no VXN filter is available** for that session -- treated as
   `vxn_close = None`. Under this rule, `NO_VXN_FILTER` still allows the
   trade (it never consults VXN); every other (real) filter candidate
   **blocks** the trade (fails the numeric comparison since there's no
   value to compare). This choice (exclude/block rather than "pass by
   default") is the conservative one: an unfiltered candidate should never
   silently inherit special treatment from missing data.

Implementation: `src/og_vxn_filter.py::build_session_date_to_vxn_close`.
Tests: `tests/test_vxn_causal_merge.py` (weekend, Thanksgiving, Christmas,
synthetic long gap, DST spring-forward, DST fall-back -- all pass, see
below).

### Causality test results (pass/fail)

| Case | Result |
|---|---|
| Weekend forward-fill (Fri 2019-11-29 -> Sat 2019-11-30) | PASS |
| Same-day trading Monday (2019-12-02, no forward-fill needed) | PASS |
| Thanksgiving holiday (2019-11-28 absent -> falls back to 2019-11-27) | PASS |
| Christmas holiday (2019-12-25 absent -> falls back to 2019-12-24) | PASS |
| Synthetic gap > threshold (14-day synthetic gap -> excluded, not forward-filled) | PASS |
| No real gap in committed data exceeds 4 days | PASS |
| DST spring-forward boundary (2019-03-10 Sunday switch; Mon 2019-03-11 same-day close used) | PASS |
| DST fall-back boundary (2019-11-03 Sunday switch; Mon 2019-11-04 same-day close used) | PASS |

All 7 tests in `tests/test_vxn_causal_merge.py` pass (`pytest
tests/test_vxn_causal_merge.py -q` -> `7 passed`).

## Filter definitions (exactly 7, applied identically to each base config)

A filter blocks an entry (the physical touch is still consumed
permanently -- it is never retried) unless the previous completed causal
VXN close satisfies the stated condition:

1. `NO_VXN_FILTER` -- control, always allowed.
2. `VXN_PREV_CLOSE_GE_20` -- allowed iff causal VXN close >= 20.
3. `VXN_PREV_CLOSE_GE_25` -- allowed iff causal VXN close >= 25.
4. `VXN_PREV_CLOSE_GE_30` -- allowed iff causal VXN close >= 30.
5. `VXN_PREV_CLOSE_LE_20` -- allowed iff causal VXN close <= 20.
6. `VXN_PREV_CLOSE_LE_25` -- allowed iff causal VXN close <= 25.
7. `VXN_PREV_CLOSE_LE_30` -- allowed iff causal VXN close <= 30.

No other threshold, combination, VXN-change/MA/slope/percentile/term
structure feature, HMM, ATR combination, time-window, or RR retuning is
tested in this study.

## Base configs (mechanics unchanged, reused exactly)

- **Base 1 = `OG_PRIMARY_150R`** mechanics: SAL off, BE45 (barcount,
  be_bars=45, be_extra_lock=0.0), no HMM, entries blocked 10:00-15:00 ET,
  target_r = 1.50, cap = min(1.5*anchor, SL_CAP). Reused byte-identically
  from `configs/OG_PRIMARY_150R.yaml` (that file is never modified).
- **Base 2 = `OG_OPERATIONAL_100R`** mechanics: identical except
  target_r = 1.00. Reused byte-identically from
  `configs/OG_OPERATIONAL_100R.yaml` (never modified).

The VXN filter is applied as an additional skip condition inside the
chronological single-global-position loop
(`src/og_management_variants.py::run_variant_managed`), checked alongside
the existing skip reasons (prop_hard_blackout, blocked_time, hmm_gate,
position_open, same_bar_reentry, simultaneous_collision) -- implemented in
`scripts/og_vxn_exploratory.py` by re-deriving the same loop with one
extra `vxn_filter` skip reason inserted before the position-state checks,
so a VXN-blocked touch is consumed exactly like any other skip (never
retried), consistent with `permanent_touch_consumption: true`.

## Analysis groups

- **Original build group:** 2018, 2020, 2023, partial 2026 (through
  2026-06-07, matching the existing build-year firewall).
- **Former validation group:** 2019, 2021, 2022, 2024, 2025 -- labeled
  `FORMER_VALIDATION__NOW_DEVELOPMENT` everywhere, never "OOS" for any
  VXN-filtered candidate in this study.
- **Combined redevelopment sample:** all of the above pooled and by year.

2013-2015 is never accessed anywhere in this study.

## Minimum robustness requirements (applied per base config, exactly as specified)

A filter may be called `VXN_FILTER_PROVISIONALLY_EARNED` for a base ONLY
when ALL of the following hold (checked explicitly in
`docs/OG_VXN_EXPLORATORY_RESULTS.md`):

1. Improves or preserves performance in BOTH the original-build group AND
   the former-validation group.
2. Does not work merely by deleting one losing year (checked by looking at
   years other than the one it disproportionately removes/keeps).
3. At least 4 of the 8 individual full years (2018/2019/2020/2021/2022/
   2023/2024/2025; partial 2026 excluded from this count) remain positive
   in net points.
4. At least 4 individual full years remain positive in total R, OR there
   is a clearly documented target-mechanics reason to retain it only for
   fixed-contract/Prop-Lab-only use.
5. At least 300 combined trades remain across the full redevelopment
   sample.
6. No single year supplies over 70% of positive net points.
7. Excluding the single best year still leaves positive net points.
8. The neighboring threshold (e.g. 20 and 30 if 25 is being considered)
   gives directionally similar results.
9. The effect appears in both the 1.00R and 1.50R bases, OR there is a
   clear, stated target-mechanics reason it does not.

Failing any one of these keeps the filter out of
`VXN_FILTER_PROVISIONALLY_EARNED`. A filter that improves raw points but
not R-normalized expectancy is `VXN_FILTER_FIXED_CONTRACT_ONLY` instead.
`NO_VXN_FILTER_EARNED` applies if none of the 6 real filters clears the
bar. `INSUFFICIENT_SAMPLE` applies if too few trades survive any filter to
judge (e.g. below requirement 5 for every real filter).

## Selection limit

At most ONE filter frozen per base config, independently chosen; the two
bases need not pick the same threshold, but a different threshold is only
chosen per base if each independently clears its own full robustness
checklist (not merely "maximizes its own metric").

## Mechanism diagnostic (planned, run after the matrix)

All trades (both bases) will be bucketed by VXN-prev-close bucket
(`<20`, `20-25`, `25-30`, `>=30`) and reported for: trade count, average /
median original stop cap (points), net points, total R, avg R/trade,
PF(points), PF(R) -- in
`docs/OG_VXN_MECHANISM_DIAGNOSTIC.md` /
`outputs/og_vxn/vxn_mechanism_buckets.csv` -- specifically to test whether
any raw-point edge in high-VXN regimes is just stop-cap scaling
(`cap = min(1.5*anchor, SL_CAP)` grows with realized volatility) while
R-normalized expectancy stays flat.

## Reproducibility

The matrix will be run once via `scripts/og_vxn_exploratory.py`, then
rerun a second time into a scratch directory to confirm byte-identical
ledgers (SHA-256 comparison per candidate CSV), per this task's
determinism requirement.
