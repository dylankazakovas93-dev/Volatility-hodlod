# Locked Out-of-Sample Holdout Test -- PRE_OOS_LOCK

Status: `LOCKED_NONCONSECUTIVE_HOLDOUT`

This is a **one-shot, locked, nonconsecutive holdout test**, not a walk-forward
test. The strategy configuration below was fully developed (TP/SL, management,
window, cutoff, regime gate) using development years 2018, 2020, 2023, and
partial 2026 -- years that are not chronologically contiguous with, and in the
case of 2026 lie chronologically *after*, some of the reserved years being
tested here. Describing this as a "walk-forward test" would misstate what it
is. It is a locked, nonconsecutive holdout evaluation.

Reserved (locked holdout) years: **2019, 2021, 2022, 2024, 2025**.
Development years (never re-examined by this test): 2018, 2020, 2023, 2026.

This document, the OOS runner code, the invariant tests, and all hashes below
are committed as `PRE_OOS_LOCK` **before** any reserved-year strategy
performance is calculated. Nothing in this commit contains a reserved-year
P&L, trade count, or any other performance number.

## Frozen configuration (unchanged from Stage 5, no re-optimization)

| Component | Value | Source (reused unchanged) |
|---|---|---|
| Instrument | NQ | `src/level_generation.py`, `src/strict_engine.py` |
| Level generation / physical first touch | unchanged | `outputs/stage1_corrected_excursions.parquet` (built once, covers all years) |
| TP/SL formula | F2, quantile regression, `mfeq=0.50`, `maeq=0.50`, alpha=0.0 | `scripts.stage2_engine.fit_frozen_formula` fit on `DEV_YEARS` only |
| TP/SL clipping and tick rounding | unchanged | `scripts.stage1_engine.round_tp` / `round_sl`, 5th/95th pctile clip |
| Entry window | 05:00-11:00 ET (blocks E+F+G+H+I) | `scripts.stage5_engine.BLOCKS`, `SELECTED_BLOCKS` in `scripts.oos_engine` |
| Forced-liquidation cutoff | 15:59 ET (minute 1319) | `scripts.stage5_engine.session_cutoff_ts` |
| Regime model | causal rolling 3-state Gaussian HMM, diagonal covariance, trailing max 120 / min 20 sessions, forward-filtered (no smoothing, no Viterbi) | `scripts.stage4_hmm.fit_hmm_for_session`, `causal_forward_filter` |
| Regime gate | `hmm3_exclude_LOW_VOL` (block LOW_VOL only; MID_VOL and HIGH_VOL both permitted) | unchanged since Stage 5 (explicit override; not `exclude_MID_VOL`, not `HIGH_VOL_only`) |
| Management | `profit_lock_0.75R`: trigger at +0.75R favourable (detected on completed 1-min bars only), stop moves to +0.10R starting the NEXT 1-min bar, original TP unchanged, no trailing, no partials | `scripts.stage3_engine.simulate_exact_r_be(trigger_r=0.75, lock_r=0.10)` |
| SAL | off | n/a |
| Position | one global position | `scripts.oos_engine.run_oos_replay` |
| Costs | gross points only | no cost model applied |

Frozen Pine-compatible HMM (kept entirely separate, see below): fit once on
2018+2020+2023 only, frozen parameters in
`outputs/stage5_pine_hmm_frozen_params.json`, never refit.

## Two independently labeled systems (never pooled)

- `ROLLING_PYTHON_HMM` -- the causal rolling per-session-refit HMM, evaluated
  on all 5 reserved years (2019, 2021, 2022, 2024, 2025).
- `FROZEN_PINE_HMM` -- the frozen (2018+2020+2023-fit, never refit) HMM,
  evaluated **only** on 2024 and 2025. Applying it to 2019, 2021, or 2022
  would use parameters fit on data chronologically after those years, which
  would not be a causally valid holdout for those years, so those three years
  are not reported for this system.

## Chronological replay methodology

One continuous chronological replay runs over the ENTIRE 2018-2026 master
table (all years, all touches), sorted by physical touch timestamp. Raw
1-minute bars and 5-minute HMM features from all years feed causal lagged
HMM training (a reserved-year session's trailing-120/min-20 HMM fit may
legitimately include prior development-year or prior reserved-year sessions --
never a session on or after the session being evaluated). Only touches whose
`year` is in the tradeable set for that system are ever eligible for entry;
all other years' touches are skipped immediately
(`blocked_non_tradeable_year`) without influencing position state (since a
skipped touch, by construction, never opens a position). The physical-touch
ledger itself is never reset at a year boundary -- there is exactly one
`position_open_until` variable for the whole replay, and no explicit
per-year simulation resets. No position ever carries past its own session's
15:59 ET forced liquidation, so no cross-year position-state question can
arise in practice, but the replay does not artificially special-case year
boundaries either way.

## Pass/fail criteria (preregistered, fixed before viewing results)

For `ROLLING_PYTHON_HMM`, pooled across all 5 reserved years:

- **OOS_STRONG_PASS** requires ALL of: pooled PF (points) >= 1.20; pooled
  total R > 0; >= 3 of 5 reserved years with positive total R; >= 3 of 5
  reserved years with PF (points) > 1.05; >= 200 pooled trades; pooled total R
  remains positive after excluding the single best year; no causality/
  execution invariant fails.
- **OOS_MARGINAL_PASS** if strong-pass fails but ALL of: pooled PF (points) >
  1.05; pooled total R > 0; >= 2 of 5 years with positive total R; >= 150
  pooled trades; no invariant fails.
- **OOS_FAIL** if: pooled PF <= 1.05; OR pooled total R <= 0; OR fewer than 2
  years have positive total R; OR any causality/execution invariant fails.

These thresholds are fixed here, in the PRE_OOS_LOCK commit, and are not
redefined after viewing reserved-year performance. `scripts/run_oos_holdout.py`
applies them mechanically (`apply_verdict`).

## Exact reproduction commands

```
python3 scripts/build_oos_hmm3_cache.py --bars data/nq_1m/nq_continuous_2018_2026_1m.csv --out-dir outputs
python3 scripts/run_oos_holdout.py --bars data/nq_1m/nq_continuous_2018_2026_1m.csv --out-dir outputs
python3 -m pytest tests/test_oos_holdout.py -v
```

## Data and code hashes (recorded at PRE_OOS_LOCK time)

Bars file used in this environment:
`data/nq_1m/nq_continuous_2018_2026_1m.csv`
SHA-256: `9f427eb053b6c63e50f79baf666f239f851558d1558e706fc126cbe69f3a5af4`

Note: this differs from the SHA-256 recorded in `configs/nq_current_config.yaml`
(`3d0228fc...`) from the original handoff verification. This discrepancy was
already identified and documented as a pre-existing, environment-local data
artifact during Stage 5 (`tests/test_data.py::test_canonical_bars_hash`
fails in this environment for the same reason, unrelated to any code in this
repository). It is disclosed again here rather than silently reconciled.

Upstream physical-touch / feature tables (built once, unchanged since Stage 0/1):
- `outputs/stage1_corrected_excursions.parquet`: `a92cfebe1bd2e059619cf2a61073cfed49c3f31dbd650109b158130a5f5ae192`
- `outputs/stage0_features.csv`: `7723ec126130bb7cbbe7d11d9aaca9a3c391c86191d7c956b10dad62c64508bd`
- `outputs/stage1_session_anchored_rvol.parquet`: `409a6096d28bb4ccf195492b739e7c1c552556b850aeb54b631a7d3abb052d9f`
- `outputs/stage5_pine_hmm_frozen_params.json`: `4992944ae69919cf40d1808b23cbe8587f684888c263f56762d7bd62e184735e`

Frozen engine code (unchanged from Stage 5, hashed at PRE_OOS_LOCK time):
- `scripts/stage2_engine.py`: `660e6dd3fb5426a0c694eef3b78506d964babf733ef5ed883172df2723f383b7`
- `scripts/stage3_engine.py`: `fa5e13fd6f5542ee4e8230101102d3bb9ddd1f68f899ad20006746ee64b9c3cc`
- `scripts/stage4_hmm.py`: `4a2edf106816e79ee6a524b347e26db9aca933b3b9dd043093d461a4688db14c`
- `scripts/stage4_regime_data.py`: `29ba128a4fbb57dab1570dcbd82c579414ffb94326a1738a5e2352499b8a0dd7`
- `scripts/stage5_engine.py`: `fc0bab379c81a3fadb8378069495cd1c016831ffb218ee41c05a376b3db9f65d`
- `scripts/fit_stage1_excursion_formulas.py`: `451f47cd4535302fde4f61fd1caa0382e63d310524f19e65aa8a37867de9322b`
- `scripts/stage1_engine.py`: `7d83b4d7922830f6801088bc2ba71f238b26b9ae2f9b5be95221c712c92ab5b1`
- `src/level_generation.py`: `6e7edf10265c66f0dc41164ad8e1aec5dfa18ece1af663d307bb39365557df9c`
- `src/strict_engine.py`: `9ffc0224310ef4904f012d946a56b0db94d777290b07fd5b3ee5d38fadf539f5`

New OOS-specific code added in this commit (additive only, does not modify
any of the frozen files above):
- `scripts/oos_engine.py`
- `scripts/build_oos_hmm3_cache.py`
- `scripts/run_oos_holdout.py`
- `tests/test_oos_holdout.py`

## Invariant tests (16 required, all committed here)

See `tests/test_oos_holdout.py`. 7 of the 16 are pure structural/causality
tests runnable without any reserved-year ledger (all pass as of this commit);
the remaining 9 assert properties of the executed ledger and will run once
`scripts/run_oos_holdout.py` has produced it (they `pytest.skip` until then,
never silently pass).

## What happens if a bug is found after viewing OOS performance

Per instruction: the run is marked invalid, the bug is explained, the
original (buggy) results are preserved as-is, and no silent fix-and-rerun
happens without explicit further instruction.
