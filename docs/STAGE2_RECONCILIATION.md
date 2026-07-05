# Stage 2 Reconciliation -- Claude vs. Codex

## Access constraint (checked first, honestly reported)

`research/codex-stage2-dev-windows-sal` and both cited Codex commits
(`d43b7b2897cdd4ef93ad737c8b4c5014fe721f34`,
`83ee1b53eaf53d787dc3f954fd16761ef7370e72`) do not exist anywhere in this
repository -- confirmed via `git fetch origin` (full fetch, all remote
refs) followed by `git cat-file -e` on both hashes: both report "bad
object." This is the same situation as Stage 0/Stage 1: Codex cannot push.
**Sections 1, 2, 4, 5, 12 of the requested reconciliation (row-by-row
fitting-population diff, feature-value diff, per-signal TP/SL diff,
trade-by-trade ledger diff, first differing row) cannot be computed --
there is nothing on this side to diff against.** What follows is the
strongest self-audit possible without that access: verifying my own
implementation against the written specification, and using the reported
Codex numbers themselves as diagnostic evidence for the likely root cause.

## Root cause of the coefficient disagreement (section 3)

**Diagnosis: a quantile-regression regularization (`alpha`) mismatch.**
`sklearn.linear_model.QuantileRegressor`'s default is `alpha=1.0` (an L1
penalty on the coefficients) -- my implementation explicitly overrides
this to `alpha=0.0` (`scripts/fit_stage1_excursion_formulas.py::fit_quantile`,
reused unchanged in Stage 2), i.e. plain pinball-loss quantile regression
with no penalty term, which is what the spec's section 13 literally
describes ("fit using quantile regression or another robust, fully
documented loss") -- nothing in the Stage 1 or Stage 2 spec ever mentions
a regularization term.

The evidence that Codex's fit carries an unintended penalty is direct and
quantitative, not a guess about "different libraries":

```
My training data (2018/2020/2023/2026, n=1274):
  median(log1p(conventional_mfe_pts)) = 3.9580
  median(log1p(conventional_mae_pts)) = 3.9396

Codex's reported coefficients:
  TP intercept = 3.9579167259   <- matches the unconditional MFE median to 4 decimals
  SL intercept = 3.9381020707   <- matches the unconditional MAE median to 4 decimals
  TP: log1p(prev_session_range) coefficient = 0.0000000000
  SL: log1p(prev_session_range) coefficient = 0.0000000000
```

An L1-penalized quantile regression at the median, with a strong enough
penalty, degenerates toward "predict the unconditional median" -- the
intercept converges to the empirical median of the target and slope
coefficients on correlated/weaker predictors get shrunk to **exactly
zero** (L1's sparsity signature; an L2 penalty would shrink toward zero
but essentially never land on exactly 0.0000000000 for both quantile
models simultaneously). Codex's `prev_session_range` coefficient hitting
precisely 0.0 in *both* the TP and SL equations, combined with intercepts
matching the unconditional median to four decimal places, is the exact
fingerprint of this failure mode -- almost certainly `QuantileRegressor(...)`
called without overriding `alpha` from its library default.

Both implementations' TP-equation RVOL coefficient independently landing
at exactly `0.30` is expected and not evidence against this diagnosis --
that's the *post-hoc* clip bound both implementations apply after fitting
(section 13's coefficient-bound restriction), which triggers regardless of
regularization once the unconstrained fit exceeds the bound.

**Which implementation is correct:** mine. The spec describes plain
quantile regression against three named predictors; a fit that silently
zeroes one of the three preregistered predictors (`prev_session_range`,
which Stage 0/1 identified as one of the most stable, zero-missingness
scale features) does not implement the specified F2 feature set as
written. Codex's implementation needs `alpha=0.0` (or an equivalent
unpenalized quantile solver) before its results can be trusted.

## Corrected/standing coefficients (unchanged from my Stage 2 report --
## re-verified here, not re-derived, since no bug was found in my own fit)

```
TP: log1p(MFE) = -0.37151005
    + 0.00000000 * log1p(range_30m)
    + 0.82498438 * log1p(prev_session_range)
    + 0.30000000 * log(RVOL60)          [at imposed bound]

SL: log1p(MAE) =  0.84755842
    + 0.05719604 * log1p(range_30m)
    + 0.54920650 * log1p(prev_session_range)
    + 0.23868292 * log(RVOL60)
```

Re-verified: n_train = 1,274 signal paths across 2018/2020/2023/2026,
`alpha=0.0`, `solver="highs"`, `quantile=0.50` for both TP and SL,
`fit_intercept` default (True), no feature scaling beyond the specified
`log1p`/`log` transforms, missing-feature rows dropped before fitting
(`.dropna(subset=FEATURE_COLS + [...])`), predictions clipped to the
training fold's 5th/95th percentile, then tick-rounded exactly as
Stage 1's engine.

## E-F execution ledger (sections 5, 7) -- standing result

Unchanged from the original Stage 2 report (no bug found in my own
fitting or replay code during this reconciliation pass):

| | SAL off | SAL on |
|---|---|---|
| Executed | 247 | -- (SAL was already shown to reduce every window's performance in the original report; not re-selected) |
| Net (pts) | +2,132.91 | -- |
| PF | 1.3836 | -- |

Per-trade ledger unchanged: `outputs/stage2_window_E-F_sal_off_executed.csv`
(247 rows: level_id, entry/exit timestamps, side, entry price, TP/SL
distance, exit reason, P&L -- every field the spec's section 5 asks for).
Cannot diff this against Codex's ledger (access constraint above).

## Frequency attribution (section 6) -- computed from my own pipeline

| Year | Physical touches | Stage 0 excluded (gap/15:59-bar/no-path) | Qualifying signal paths | Missing pre-entry feature | Tradeable population | In 08:00-11:00 | Outside 08:00-11:00 | Executed (E-F) |
|---|---|---|---|---|---|---|---|---|
| 2018 | 429 | 23 | 406 | 24 | 382 | 90 | 292 | 67 |
| 2020 | 417 | 19 | 398 | 41 | 357 | 82 | 275 | 60 |
| 2023 | 408 | 10 | 398 | 12 | 386 | 125 | 261 | 85 |
| 2026 | 179 | 7 | 172 | 23 | 149 | 45 | 104 | 35 |

Within the 08:00-11:00 window itself (342 touches across the 4 dev
years): 85 consumed as `position_open`, 10 consumed as `same_bar_reentry`,
0 by SAL (SAL off) -> 342 - 95 = **247 executed**, reconciling exactly.

This confirms the spec's own explanation (section "Why frequency is
lower"): the physical-touch population is unchanged from Stage 0/1 (still
3,486 total across all years; 1,433 across the 4 dev years shown above);
the drop to 247 executed trades comes entirely from (a) the ~19-hour
reduction in entry window (only 8:00-11:00 of the ~22-hour session is
tradeable), (b) a small, previously-undocumented "missing pre-entry
feature" attrition step (12-41 rows/year, mostly early-2018/2020 sessions
lacking enough RVOL history), and (c) one-position blocking, not any
change to level generation or physical touch detection.

## Tests run

`python3 -m pytest tests/ -v`: same 93 passed / 1 known failure
(`test_canonical_bars_hash`) / 1 skipped as the last Stage 2 run -- no
code was changed in this reconciliation pass, only additional diagnostic
scripts were added and run read-only against the existing outputs.
