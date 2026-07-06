# Stage 5: Entry-Window and Forced-Liquidation-Cutoff Search
## (frozen F2 TP/SL + profit_lock_0.75R + hmm3_exclude_LOW_VOL)

Branch: `research/claude-stage5-window-cutoff`

Everything below is layered on top of frozen, unchanged prior-stage output:
- TP/SL formula: F2 (learned quantile-regression, `mfeq=0.50`, `maeq=0.50`), fit on dev
  years only (2018, 2020, 2023, 2026), never refit in this stage.
- Trade management: `profit_lock_0.75R` (stop moved to +0.10R once price reaches
  +0.75R favourable excursion, next-bar activation) -- unchanged from Stage 3.
- Regime gate: `hmm3_exclude_LOW_VOL` -- a causal, per-session-refit 3-state Gaussian
  HMM (diag covariance) on 5-minute NQ features (`ret`, `vol30`, `trend30`), forward-
  filtered (not smoothed/Viterbi), states ordered ascending by fitted realized-vol
  mean. Trades are blocked only in `LOW_VOL`; `MID_VOL` and `HIGH_VOL` are both
  allowed. This is the exact rule the user specified for Stage 5 -- **not**
  `exclude_MID_VOL` and **not** `HIGH_VOL_only`, both of which were also produced (and
  one of which was previously mis-selected) in Stage 4.
- SAL: off. One global position at a time, no overlap. Gross points only (no
  transaction costs modeled). Development years only: 2018, 2020, 2023, partial 2026.
  Reserved years (2019, 2021, 2022, 2024, 2025) are never entered, never reported --
  enforced identically to Stage 2/3/4 via the `year not in DEV_YEARS` guard inside
  `run_replay` (verified by `test_no_reserved_year_in_any_stage5_ledger`).

None of TP/SL, profit-lock parameters, HMM states, or the state-exclusion rule were
touched. GARCH was not retested this stage, per instruction.

---

## 1. New session-relative blocks (Stage 5 only -- distinct lettering from Stage 2's A-H)

| Block | ET clock time | Minutes since 18:00 ET session start |
|---|---|---|
| A | 18:00 - 00:00 | 0 - 360 |
| B | 00:00 - 02:00 | 360 - 480 |
| C | 02:00 - 03:00 | 480 - 540 |
| D | 03:00 - 05:00 | 540 - 660 |
| E | 05:00 - 06:00 | 660 - 720 |
| F | 06:00 - 08:00 | 720 - 840 |
| G | 08:00 - 09:00 | 840 - 900 |
| H | 09:00 - 09:30 | 900 - 930 |
| I | 09:30 - 11:00 | 930 - 1020 |

Contiguous ranges of these 9 blocks give 45 distinct windows (`9*10/2`), all tested in
Part 2. Verified programmatically: every minute 0-1019 maps to exactly one block, and
adjacent blocks share a boundary with no gap/overlap (`test_blocks_cover_18_to_11_with_no_gap_or_overlap`,
`test_every_minute_0_to_1019_maps_to_exactly_one_block`).

Broken-session definitions (Part 3):
- Asia = `{A}` (18:00-00:00)
- London = `{C, D, E}` (02:00-06:00)
- New York = `{H, I}` (09:00-11:00)

---

## 2. Part 1 -- Forced-liquidation cutoff sweep (window fixed at 08:00-11:00 = G+H+I)

| cutoff | n | net_pts | total_R | avg_R | PF | max_dd_pts | true_TP_winrate |
|---|---|---|---|---|---|---|---|
| 11:00 | 214 | 1349.03 | 19.11 | 0.0893 | 1.414 | -237.19 | 0.304 |
| 12:00 | 214 | 1104.88 | 10.59 | 0.0495 | 1.276 | -392.72 | 0.365 |
| 13:00 | 214 | 1362.95 | 14.69 | 0.0687 | 1.331 | -447.47 | 0.407 |
| 14:00 | 214 | 1431.64 | 16.13 | 0.0754 | 1.343 | -433.27 | 0.421 |
| 15:00 | 214 | 1587.01 | 18.57 | 0.0868 | 1.378 | -393.44 | 0.435 |
| **15:59** | 214 | **1699.13** | **20.38** | 0.0952 | 1.410 | -387.19 | 0.439 |

Trade count is identical across cutoffs (214) because the window and entry logic don't
change -- only how long a position is allowed to run before forced flat. 15:59 is
monotonically best or tied-best on net_pts, total_R, and true win rate, and is also the
"do nothing extra" baseline (same forced-liquidation time used in every prior stage).
15:59 (1319 minutes) is carried forward as the cutoff for the rest of Stage 5.

---

## 3. Part 2 -- Contiguous window sweep (45 windows, cutoff = 15:59)

Candidates with **all four development years individually net-positive in points**
(the first selection criterion), ranked by total R:

| window | blocks | n | net_pts | total_R | avg_R | PF | max_dd_pts |
|---|---|---|---|---|---|---|---|
| **contig_EFGHI** | 05:00-11:00 | 250 | **1929.89** | **21.44** | 0.0857 | 1.400 | -429.78 |
| contig_FGHI | 06:00-11:00 | 234 | 1824.12 | 21.27 | 0.0909 | 1.409 | -425.43 |
| contig_GHI | 08:00-11:00 | 214 | 1699.13 | 20.38 | 0.0952 | 1.410 | -387.19 |
| contig_HI | 09:00-11:00 | 189 | 1587.43 | 16.58 | 0.0877 | 1.434 | -358.19 |
| contig_GH | 08:00-09:30 | 40 | 643.28 | 10.28 | 0.2569 | 1.880 | -215.30 |
| contig_BC | 00:00-03:00 | 29 | 499.09 | 9.81 | 0.3382 | 2.000 | -197.75 |
| contig_C | 02:00-03:00 | 19 | 407.46 | 8.22 | 0.4325 | 2.138 | -148.25 |
| contig_H | 09:00-09:30 | 13 | 577.58 | 8.19 | 0.6300 | 4.936 | -96.75 |
| contig_E | 05:00-06:00 | 20 | 373.42 | 2.83 | 0.1416 | 2.041 | -131.65 |

9 of 45 windows clear the all-4-years-profitable bar. **contig_EFGHI (05:00-11:00 ET,
blocks E+F+G+H+I) is the best normal window**: highest total R and highest net points
of any qualifying window, with a materially wider trade sample (250 vs 214) than the
current control. Its average R/trade (0.0857) is slightly below the narrower
G-H-I control (0.0952), consistent with the instructed preference for "a wider window
with slightly lower average R but materially higher annual R."

2020 is worth flagging explicitly: contig_EFGHI's 2020 total_R is -1.976 (avg_R
-0.0335) even though 2020 net_pts is +240.91 -- i.e. 2020 is profitable in raw points
but marginally loses on a normalized R basis (larger average loser relative to risk
than average winner that year). All four years are net-point-positive; not all four
are R-positive. This is disclosed rather than smoothed over.

---

## 4. Part 3 -- Broken (non-contiguous) session windows (cutoff = 15:59)

| window | blocks | n | net_pts | total_R | avg_R | PF | max_dd_pts | years profitable (net_pts) |
|---|---|---|---|---|---|---|---|---|
| **newyork_only** | H+I (09:00-11:00) | 189 | 1587.43 | 16.58 | 0.0877 | 1.434 | -358.19 | 4/4 |
| **london_or_newyork** | C+D+E or H+I | 261 | 1432.06 | 15.92 | 0.0610 | 1.270 | -650.77 | 4/4 |
| asia_or_london_or_newyork | A or C+D+E or H+I | 325 | 1345.92 | 14.13 | 0.0435 | 1.186 | -622.19 | 2/4 |
| asia_or_newyork | A or H+I | 258 | 1345.26 | 11.98 | 0.0464 | 1.234 | -516.49 | 3/4 |
| london_only | C+D+E (02:00-06:00) | 77 | 81.31 | 3.70 | 0.0480 | 1.049 | -382.32 | 2/4 |
| asia_or_london | A or C+D+E | 141 | -4.83 | 1.90 | 0.0135 | 0.999 | -732.40 | 2/4 |
| asia_only | A (18:00-00:00) | 69 | -242.17 | -4.60 | -0.0666 | 0.885 | -779.88 | 2/4 |

The explicitly required broken-session example (`02:00-06:00 OR 09:00-11:00`, i.e.
`london_or_newyork`) clears all four dev years and produces total_R 15.92 -- solidly
positive but below the plain contiguous G-H-I/E-F-G-H-I windows. `newyork_only`
(H+I) is numerically identical to `contig_HI` from Part 2 (same block set, same span
900-1020), which is a useful internal consistency check: the two independently-run
sweeps agree to the point/R decimal, confirming the replay engine is deterministic
and window-membership logic is applied identically in both code paths.

**Best broken-session window: `london_or_newyork`** (all 4 years profitable, highest
total R among broken windows).

---

## 5. Part 4 -- Window x cutoff interaction (5 windows x 3 neighboring cutoffs)

Neighboring cutoffs of 15:59 (1319 min) are 15:00 (1260 min) and none above (15:59 is
the last defined cutoff), so each window was run at {1260, 1319}.

| candidate | cutoff | n | net_pts | total_R | avg_R | PF | max_dd_pts | years profitable |
|---|---|---|---|---|---|---|---|---|
| **best_contig_EFGHI** | **1319** | 250 | **1929.89** | **21.44** | 0.0857 | 1.400 | -429.78 | 4/4 |
| best_contig_EFGHI | 1260 | 250 | 1803.78 | 19.20 | 0.0768 | 1.369 | -450.03 | 4/4 |
| best_broken_london_or_ny | 1319 | 261 | 1432.06 | 15.92 | 0.0610 | 1.270 | -650.77 | 4/4 |
| best_broken_london_or_ny | 1260 | 261 | 1320.20 | 14.12 | 0.0541 | 1.246 | -657.02 | 4/4 |
| control_08_11_GHI | 1319 | 214 | 1699.13 | 20.38 | 0.0952 | 1.410 | -387.19 | 4/4 |
| control_08_11_GHI | 1260 | 214 | 1587.01 | 18.57 | 0.0868 | 1.378 | -393.44 | 4/4 |
| best_PF_HI_0900_1100 | 1319 | 189 | 1587.43 | 16.58 | 0.0877 | 1.434 | -358.19 | 4/4 |
| best_PF_HI_0900_1100 | 1260 | 189 | 1475.31 | 14.77 | 0.0782 | 1.398 | -364.44 | 4/4 |
| old_19_11 | 1319 | 375 | 1508.01 | 19.70 | 0.0525 | 1.185 | -803.48 | 2/4 |
| old_19_11 | 1260 | 375 | 1356.09 | 16.97 | 0.0453 | 1.165 | -886.54 | 2/4 |

15:59 beats 15:00 for every one of the 5 windows -- confirms the Part 1 finding holds
across window shapes, not just the G-H-I control.

**Best overall window/cutoff combination: `contig_EFGHI` at cutoff 15:59.**

---

## 6/7/8. Comparisons

**vs current 08:00-11:00 (G-H-I) control, both at cutoff 15:59:**

| | n | net_pts | total_R | avg_R | PF | max_dd_pts |
|---|---|---|---|---|---|---|
| control 08:00-11:00 | 214 | 1699.13 | 20.38 | 0.0952 | 1.410 | -387.19 |
| **EFGHI (05:00-11:00)** | 250 | **1929.89** | **21.44** | 0.0857 | 1.400 | -429.78 |
| delta | +36 | +230.76 | +1.06 | -0.0095 | -0.010 | -42.59 |

EFGHI adds 36 trades/year of study period and +230.76 net pts / +1.06 total R, at the
cost of a slightly thinner average R per trade and slightly larger drawdown. PF is
essentially unchanged (1.400 vs 1.410).

**vs old 19:00-11:00 window** (the pre-Stage-2 legacy window, tested here at cutoff
15:59 for a fair comparison): 375 trades, net 1508.01, total_R 19.70, PF 1.185, max_dd
-803.48, only 2 of 4 dev years individually net-positive. EFGHI (250 trades, net
1929.89, total_R 21.44, PF 1.400, max_dd -429.78, 4/4 years profitable) dominates it on
every selection criterion: more total R, better annual consistency, better PF, less
than half the drawdown, despite fewer trades. The old 19:00-11:00 window is
decisively inferior under this frozen management/regime stack and is not recommended.

**Final Stage 5 selected window/cutoff: `contig_EFGHI` (05:00-11:00 ET, blocks
E+F+G+H+I) with a 15:59 ET forced-liquidation cutoff.**

---

## 9/10/11. Rolling HMM vs frozen Pine-compatible HMM (2026 only)

A second, separate 3-state Gaussian HMM (`scripts/build_stage5_pine_hmm.py`) was fit
**once**, only on sessions labeled 2018, 2020, or 2023 (`FREEZE_YEARS`), and never
refit -- its standardization (mean/std), transition matrix, state means/variances, and
state ordering (ascending by fitted `vol30` mean) are frozen and saved verbatim to
`outputs/stage5_pine_hmm_frozen_params.json`. The exact same causal forward-filter
algorithm used by the rolling (per-session-refit) HMM was then applied to all 149
2026 touches, without any refitting on 2026 data.

Of the 149 2026 touches, 53 occur at minutes-elapsed >= 1020 (i.e. after 11:00 ET,
outside every window tested in this study -- Stage 5's rolling HMM cache
(`stage5_hmm3_features.csv`) was only ever built for the 18:00-11:00 span, so those 53
have no rolling-HMM counterpart to compare against). Restricting to the 96 touches
that both models can classify (all of them within the tested trading windows):

**State agreement: 81.25%** (78/96 touches). Confusion breakdown:

| rolling \ pine | LOW_VOL | MID_VOL | HIGH_VOL |
|---|---|---|---|
| LOW_VOL | 13 | 1 | 0 |
| MID_VOL | 5 | 15 | 0 |
| HIGH_VOL | 1 | 11 | 50 |

Disagreements are concentrated in MID_VOL vs HIGH_VOL boundary cases (11), not in
LOW_VOL vs trade-allowed cases (only 6 of 96 touches cross the LOW_VOL boundary
differently between models), which is the boundary that actually matters for the
`exclude_LOW_VOL` trading rule.

**Trade-level comparison** -- re-ran the full `contig_EFGHI` @ cutoff 15:59 replay for
2026 only, once gating on the rolling HMM state (as used everywhere else in this
report) and once substituting the frozen Pine-HMM state for every 2026 touch:

| | n (2026) | net_pts | total_R | avg_R |
|---|---|---|---|---|
| rolling HMM | 39 | 892.51 | 10.12 | 0.2595 |
| frozen Pine HMM | 37 | 975.16 | 11.02 | 0.2979 |

37 vs 39 trades, and net/R both *higher* under the frozen model for this partial-2026
sample -- i.e. the frozen, Pine-portable HMM is reasonably close to the rolling
per-session-refit HMM on the only year where they can be compared (2026 is the only
development year not in `FREEZE_YEARS`). This clears the "reasonably close" bar the
instructions set for writing the Pine indicator.

**Documented limitation:** 2026 is a partial year with only 39 (rolling) / 37 (Pine)
qualifying trades -- this comparison is informative but not a large-sample
robustness claim; no reserved year was used to extend the comparison sample, per
instruction.

---

## 12. Pine Script v6 indicator

`pine/stage5_hmm_regime_filter.pine` -- implements the identical causal forward-filter
algorithm as the Python engine, with all frozen parameters (standardization, start
distribution, transition matrix, per-state means/variances) embedded as literals
copied verbatim from `outputs/stage5_pine_hmm_frozen_params.json`. Uses only
completed 5-minute bars (`ret`, `vol30 = ta.stdev(ret,6)` i.e. trailing 30 minutes,
`trend30` = sum of the trailing 6 log-returns), updates its persistent `var` alpha
state only `if barstate.isconfirmed` (no repainting), and plots P(LOW/MID/HIGH),
a red/green background, a state label, and `alertcondition`s that fire only on a
LOW_VOL <-> trade-allowed transition. Intended for a 5-minute NQ chart; running it on
any other timeframe changes the feature definitions (documented in-file).

---

## 13. Final trade frequency and annual R (selected config: contig_EFGHI, cutoff 15:59)

| year | n | net_pts | PF | avg_R | total_R |
|---|---|---|---|---|---|
| 2018 | 67 | 48.28 | 1.044 | 0.0037 | 0.247 |
| 2020 | 59 | 240.91 | 1.171 | -0.0335 | -1.976 |
| 2023 | 85 | 748.20 | 1.469 | 0.1534 | 13.043 |
| 2026 (partial) | 39 | 892.51 | 2.243 | 0.2595 | 10.122 |
| **all dev years** | **250** | **1929.89** | **1.400** | **0.0857** | **21.436** |
| ex-2026 (2018+2020+2023) | 211 | 1037.38 | 1.253 | -- | 11.314 |

True TP-only win rate (excludes BE/LOCK/scratch exits from the win count): 42.4%.
Roughly 65-85 trades/year at full-year cadence (2020/2023/2018 range 59-85); 2026 is
partial-year only.

---

## 14. No-overlap and no-lookahead confirmation

- **No overlap**: `run_replay` maintains one global `position_open_until` timestamp;
  a new touch is skipped (`position_open` or `same_bar_reentry` skip reasons) unless
  it occurs strictly after the prior trade's exit. Verified for the selected
  `contig_EFGHI` ledger by `test_no_overlap_in_selected_window_ledger`, which asserts
  `entry_time[i] >= exit_time[i-1]` for every consecutive pair once sorted by
  `entry_time`.
- **No lookahead**: entry-window membership, cutoff-timestamp computation, and the
  HMM regime gate all use only `touched_at` and strictly-prior bar/session history;
  the HMM forward-filter is the same causal (not forward-backward) implementation
  reused unchanged from Stage 4, verified there by dedicated adversarial lookahead
  tests. `test_every_minute_0_to_1019_maps_to_exactly_one_block` and
  `test_blocks_cover_18_to_11_with_no_gap_or_overlap` confirm the new A-I block
  arithmetic has no gap/overlap that could cause silent double-classification.
  `test_no_reserved_year_in_any_stage5_ledger` confirms no reserved-year (2019/2021/
  2022/2024/2025) touch ever appears in any Stage 5 ledger.

All 8 new Stage 5 tests pass (`tests/test_stage5_window_cutoff.py`); the full repo
suite passes except for the pre-existing, unrelated `test_canonical_bars_hash` check
in `tests/test_data.py`, which fails only because the large, gitignored local
`data/nq_1m/nq_continuous_2018_2026_1m.csv` copy in this environment has a different
SHA-256 than the one recorded in `configs/nq_current_config.yaml` -- a known
environment-data artifact predating and unrelated to Stage 5, not a Stage 5 defect.
