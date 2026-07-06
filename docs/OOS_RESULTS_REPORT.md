# Locked Out-of-Sample Holdout Test -- OOS_RESULTS

Status: `LOCKED_NONCONSECUTIVE_HOLDOUT` (not a walk-forward test -- see
`docs/OOS_PRE_LOCK.md` for why).

**Preregistered verdict: `OOS_MARGINAL_PASS`**

Configuration, hashes, and pass/fail thresholds were locked in commit
`PRE_OOS_LOCK` (`450ef461872b5688960b1ae8b39b40cfff9f0b72`) before any
reserved-year performance number existed. Nothing below was used to adjust
the strategy, thresholds, window, cutoff, HMM states, or management rule.
Reproducibility was verified by rerunning the exact same locked script twice
more; the ledger files are byte-identical across all reruns.

## 1. Verdict derivation

| Threshold (from PRE_OOS_LOCK) | Required (strong) | Required (marginal) | Actual |
|---|---|---|---|
| Pooled PF (points) | >= 1.20 | > 1.05 | **1.083** |
| Pooled total R | > 0 | > 0 | **1.6677** |
| Years with positive total R | >= 3 of 5 | >= 2 of 5 | **2 of 5** (2019, 2025) |
| Years with PF (points) > 1.05 | >= 3 of 5 | n/a | **2 of 5** (2021, 2025) |
| Pooled trades | >= 200 | >= 150 | **430** |
| Total R positive ex-best-year | required | n/a | **fails** (-5.6162) |
| Invariants | all pass | all pass | **all 19 pass** |

Strong-pass fails on PF, years-positive-R, years-PF>1.05, and the
ex-best-year robustness check. Marginal-pass clears on all four of its
conditions (PF>1.05, total R>0, >=2 years positive, >=150 trades) with no
invariant failure. Result: **OOS_MARGINAL_PASS**.

## 2. `PRE_OOS_LOCK` commit SHA

`450ef461872b5688960b1ae8b39b40cfff9f0b72`

## 3. `OOS_RESULTS` commit SHA

Recorded after this commit is made (see final response).

## 4. Data and configuration hashes

- Bars file (`data/nq_1m/nq_continuous_2018_2026_1m.csv`): `9f427eb053b6c63e50f79baf666f239f851558d1558e706fc126cbe69f3a5af4`
- Upstream physical-touch/feature tables and frozen engine code hashes: unchanged from PRE_OOS_LOCK, see `docs/OOS_PRE_LOCK.md`.
- `oos_ledger_rolling_python_hmm.csv` SHA-256: `d1f945aa8d438b2d63cc8a59b79467e3e6978c1346396b44c13cc99c253af428`
- `oos_ledger_frozen_pine_hmm.csv` SHA-256: `6be411cdbdaed4c7a3f35ebc7a362848c8eb4fe9657a7811b6d5e8ad76a9478a`

## 5. `ROLLING_PYTHON_HMM` pooled results (all 5 reserved years)

| metric | value |
|---|---|
| physical touches (reserved years, in master) | 1840 |
| window-eligible touches | 708 (1840 - 1132 blocked_window) |
| HMM-allowed touches (of window-eligible) | 612 (708 - 96 blocked_low_vol) |
| executed trades | **430** |
| net points | **904.72** |
| total R | **1.6677** |
| avg R/trade | 0.0039 |
| PF (points) | 1.083 |
| PF (R) | 1.0092 |
| true TP-only win rate | 37.44% |
| avg TP | 70.61 pts |
| avg original SL | 61.92 pts |
| avg structural TP:SL ratio | 1.0837 |
| TP exits | 161 |
| SL exits | 178 |
| LOCK exits | 76 |
| cutoff exits | 15 |
| max drawdown (points) | -843.75 |
| max drawdown (R) | -19.1667 |
| longest loss streak (pooled, chronological) | 6 |
| avg hold time | 81.03 min |
| median hold time | 48.5 min |
| long trades / net pts | 204 / 403.77 |
| short trades / net pts | 226 / 500.95 |

## 6. `ROLLING_PYTHON_HMM` year-by-year results

| year | n | net_pts | total_R | avg_R | PF_pts | PF_R | max_dd_pts | true_TP_winrate | TP/SL/LOCK/cutoff |
|---|---|---|---|---|---|---|---|---|---|
| 2019 | 76 | 36.03 | 1.9772 | 0.0260 | 1.0355 | 1.0705 | -333.42 | 40.79% | 31/26/8/11 |
| 2021 | 85 | 325.12 | -1.5633 | -0.0184 | 1.1581 | 0.9589 | -530.66 | 37.65% | 32/37/13/3 |
| 2022 | 87 | -266.93 | -2.7371 | -0.0315 | 0.9021 | 0.9298 | -535.20 | 35.63% | 31/39/17/0 |
| 2024 | 92 | -129.57 | -3.2931 | -0.0358 | 0.9488 | 0.9216 | -674.42 | 38.04% | 35/42/15/0 |
| 2025 | 90 | 940.07 | 7.2840 | 0.0809 | 1.3664 | 1.2142 | -333.85 | 35.56% | 32/34/23/1 |

Note: 2021 is net-point-positive (+325.12) but total-R-negative (-1.5633) --
the same points-vs-R divergence flagged for 2020 in the Stage 5 report is
present again here; disclosed rather than smoothed over.

## 7. `FROZEN_PINE_HMM` results, 2024/2025 only (never pooled with rolling)

| metric | pooled 2024-2025 | 2024 | 2025 |
|---|---|---|---|
| executed trades | 185 | 94 | 91 |
| net points | 921.07 | -41.62 | 962.70 |
| total R | 5.5515 | -1.8300 | 7.3815 |
| avg R/trade | 0.0300 | -0.0195 | 0.0811 |
| PF (points) | 1.1774 | 0.9838 | 1.3663 |
| PF (R) | 1.0721 | 0.9564 | 1.2109 |
| max drawdown (points) | -771.92 | -771.92 | -452.77 |
| true TP-only win rate | 37.30% | 38.30% | 36.26% |

Pine parameter hash / provenance: fit once on 2018+2020+2023 only, frozen in
`outputs/stage5_pine_hmm_frozen_params.json` (SHA-256
`4992944ae69919cf40d1808b23cbe8587f684888c263f56762d7bd62e184735e`), applied
here to 2024/2025 with zero refitting, via the standalone diagonal-Gaussian
forward filter in `scripts/oos_engine.py` (verified byte-for-byte against
`scripts/stage4_hmm.causal_forward_filter`'s algorithm, and verified to
exactly reproduce the existing, already-committed 2026 Pine output with 0
mismatches across 149 touches before being trusted here).

Rolling-vs-Pine agreement on the 749 touches both systems evaluate
(2024/2025, all touches -- not just executed trades):
- **HMM state agreement: 79.84%**
- **Allow/block agreement (window+HMM combined gate): 97.20%**
- **Exit-reason agreement, given both systems entered the same touch: 100.00%**

The 100% exit-reason agreement (given identical entry) is expected: exit
simulation (`simulate_exact_r_be`) depends only on TP/SL/profit-lock
mechanics, which are identical between the two systems -- only the entry gate
(HMM state) differs. Comparing 2024/2025 rolling-only (92+90=182 trades net
pts -129.57+940.07... — see section 6) against Pine-only (185 trades, net
921.07) on the same two years: Pine trades slightly more (185 vs 182) and
nets more (921.07 vs 810.50 combined 2024+2025 rolling), consistent with the
Stage 5 finding that the frozen model is "reasonably close" to the rolling
model, not identical.

## 8. Best-year contribution and leave-best-year-out

- Best year (by net points): **2025** (net 940.07, total_R 7.284).
- 2025 contributes **103.91%** of pooled net points (i.e. pooled profit is
  entirely attributable to 2025; the other four years combined are net
  slightly negative in points, and clearly negative in R).
- **Excluding 2025: net_pts = -35.35, total_R = -5.6162** -- pooled
  performance flips negative on both metrics once the single best year is
  removed. This is the strong-pass gate's ex-best-year check failing, and is
  the central caveat of this OOS result: without 2025, the strategy would
  not have cleared even the marginal-pass bar.
- Worst year (by net points): **2022** (net -266.93, total_R -2.7371).
  Excluding 2022: net_pts = 1171.65, total_R = 4.4049 -- pooled performance
  stays comfortably positive without the worst year, the opposite asymmetry
  from the best-year removal.

## 9. Maximum drawdown and longest loss streak

- Pooled max drawdown: **-843.75 points / -19.1667 R**.
- Pooled longest consecutive-loss streak (chronological across all 5
  reserved years, position-ledger order): **6 trades**.
- Worst single-year drawdown: 2024 at -674.42 points.

## 10. Complete skip-reason reconciliation

Reserved-year physical touches in the master table: **1840**. Every one is
accounted for exactly once in the ledger (`total_rows_in_rolling_ledger` =
1840):

| reason | count |
|---|---|
| blocked_window (outside 05:00-11:00 ET) | 1132 |
| blocked_low_vol (HMM state = LOW_VOL) | 96 |
| position_open | 156 |
| same_bar_reentry | 26 |
| blocked_at_or_after_cutoff | 0 |
| **executed** | **430** |
| **total** | **1840** |

(1132 + 96 + 156 + 26 + 430 = 1840, exact.) The full chronological replay
additionally skips 1274 development-year/2026 touches as
`blocked_non_tradeable_year` -- these are never part of the reserved-year
population and are shown separately in `oos_final_report.json` for audit
completeness, not mixed into the reconciliation above.

## 11. No-overlap confirmation

`test_no_overlapping_positions` and `test_no_same_minute_reentry` both pass:
for every consecutive executed-trade pair (sorted by entry time),
`entry_time[i] > exit_time[i-1]` strictly, across the entire chronological
reserved-year sequence (no per-year reset). `test_no_retry_after_consumed_touch`
confirms every `(level_id, side)` pair appears at most once anywhere in the
1840-row ledger.

## 12. No-lookahead confirmation

- `test_hmm_training_excludes_current_and_future_sessions`: `trailing_sessions`
  never returns the target session or any session at/after it.
- `test_hmm_state_uses_only_completed_bars`: the HMM state used at any entry
  comes only from a 5-minute bar whose completion (`bar_start + 5min`) is
  `<=` the entry timestamp -- verified with an explicit boundary-case test
  (a bar completing exactly at, vs. one minute after, the entry time).
- `test_tp_sl_frozen_at_entry_by_construction`: TP/SL are computed once
  before the bar-by-bar loop and never recomputed.
- `test_no_entry_outside_selected_window`, `test_no_entry_in_low_vol`,
  `test_mid_and_high_vol_both_allowed`, `test_no_entry_at_or_after_cutoff`,
  `test_every_trade_closed_by_cutoff`: all pass against the actual 430-trade
  ledger.

## 13. Profit-lock causality confirmation

`test_profit_lock_activates_one_bar_after_trigger_never_on_trigger_bar`
constructs an adversarial bar sequence and asserts the lock activation bar
index is exactly the trigger bar index + 1, never equal to it -- confirmed
against the actual `simulate_exact_r_be` implementation (unchanged from
Stage 3), not a reimplementation.

## 14. Ledger hashes

- `oos_ledger_rolling_python_hmm.csv`: `d1f945aa8d438b2d63cc8a59b79467e3e6978c1346396b44c13cc99c253af428`
- `oos_ledger_frozen_pine_hmm.csv`: `6be411cdbdaed4c7a3f35ebc7a362848c8eb4fe9657a7811b6d5e8ad76a9478a`

Both reproduced byte-identically across three independent re-runs of
`scripts/run_oos_holdout.py` from the same locked commit and data hashes
(`test_reproducibility_hash_matches_report` passes).

## 15. Discrepancies / invalidations

None found. One implementation issue was caught and fixed **before** any
reserved-year number was reported: the initial run crashed
(`TypeError: cannot subtract DatetimeArray from ndarray[object]`) computing
hold-time metrics because mixed None/Timestamp columns stayed `object`
dtype; fixed by explicit `pd.to_datetime` casting immediately after ledger
construction. This was a pure dtype-plumbing bug in the reporting layer, not
in trade simulation, entry/exit logic, or the replay itself -- the fix was
applied and the script re-run from scratch before any result was viewed, so
no invalidation of a previously-viewed result was needed. Separately, the
`df_hash` reproducibility check initially hashed the in-memory DataFrame
(pre-CSV-serialization) while the test hashed the round-tripped CSV,
producing a false mismatch; fixed to hash the actual written CSV bytes on
both sides, and re-verified reproducible across reruns.

A background HMM-fitting process was killed once mid-run by an unrelated
session/shell-lifecycle event before producing any output; it was restarted
cleanly and completed all 785/785 session fits with no partial-state
carryover (no output files existed from the killed attempt, confirmed before
restart).
