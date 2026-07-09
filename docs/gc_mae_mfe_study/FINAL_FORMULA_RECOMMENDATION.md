# Final Formula Recommendation — GC Level-Generator MAE/MFE Study

## Verdict, stated first

**None of the fitted formulas in this study are suitable for prospective/live
use.** They are **descriptive and retrospectively fitted only**. This is a
negative result, reached honestly rather than forced into a positive one —
see the evidence below. This conclusion applies to both the excursion-grade
level-generator grid search and the MAE/MFE formulas fit on top of it.

## Part 1 — level-generator grid search (773 sessions, 1,014-1,267 touches
depending on params, GC 2023-06 to 2026-05, VXN as the vol feed)

144 combinations of `sigma_mult in {0.5..2.0}` x `offset_pct in {0.0..0.08}`
x `ib_minutes in {15,30,45}` were graded by median(MFE_R) - median(MAE_R)
across every physical touch, measured from entry to the fixed prop-firm
15:00 ET session cutoff (Definition C, `LABEL_DEFINITION.md`) — decoupled
from the strategy's own 1:1 TP/SL exit.

**Every single one of the 144 combinations produced a negative median
excursion asymmetry** (adverse excursion exceeds favorable excursion, by
this measure, at every tested parameterization). The least-bad cell —
`sigma_mult=2.0, offset_pct=0.08, ib_minutes=30` — only reaches
`median(MFE_R) - median(MAE_R) = -0.0084` (essentially flat, not positive)
and `frac(MFE_R > MAE_R) = 0.479` (still under half). The frozen baseline
(`sigma_mult=1.15, offset_pct=0.02, ib_minutes=30`) sits at -0.144, notably
worse. Full grid: `outputs/gc_level_gen_grid/grid_results.csv`.

**What this means:** under an uncensored, deadline-bound horizon, GC's raw
price action does not structurally favor the fade direction at any tested
level-generation parameterization — the closest to neutral is still not
positive. The strategy's actual positive (if thin) PF on GC at baseline
params in the earlier cross-asset study (PF ~1.03 with VXN) is therefore
better explained by the **tight 1:1 realized exit discipline cutting
losers early and banking winners quickly**, not by the underlying
excursion profile being tilted in the trade's favor. This is a materially
different (and more honest) claim than "the best level generator produces
favorable excursion" — it does not, in this sample, at any grid point
tested.

`sigma_mult=2.0, offset_pct=0.08, ib_minutes=30` is still used as *the*
parameterization for Part 2 below (it is the least-unfavorable point in
the grid and the one explicitly requested to carry forward), but it should
not be read as "found a good level generator" — only as "found the
least-bad one in this bounded grid."

## Part 2 — MAE/MFE interpretable formulas (fit at the Part 1 winning params)

Data: 1,014 touches, chronological split train=535 (2023-06 to 2024-12),
validation=350 (2025), test=129 (2026-01 to 2026-05, touched once at the
very end). Full detail: `SPLIT_MANIFEST.json`, `FORMULA_CANDIDATES.csv`,
`WALK_FORWARD_RESULTS.csv`, `CALIBRATION_REPORT.md`.

### Failure conditions actually triggered (not hypothetical — observed)

1. **A more complex formula barely beats, or loses to, a simple
   baseline** — confirmed. Across the 5 expanding-window walk-forward
   folds (`WALK_FORWARD_RESULTS.csv`), the unconditional-median baseline
   has a **lower** mean absolute error than the linear-regression formula
   in 9 of 10 fold x target combinations (both `mae_R` and `mfe_R`, folds
   1-5). The one exception (`mfe_R`, fold 3) is a razor-thin margin
   (1.022 vs. 1.088). A formula with 10 fitted coefficients underperforming
   a single constant is disqualifying on its own.

2. **Performance degrades materially out of sample** — confirmed. Linear
   regression validation -> test: `mae_R` RMSE 1.47R -> 3.21R, mean bias
   flips from -0.015R (near-unbiased) to +1.59R (badly underpredicting);
   `mfe_R` RMSE 1.78R -> 3.78R. Quantile coverage also degrades
   (e.g. `mae_R` q0.9 coverage: 0.911 on validation, drops to 0.752 on
   test — a supposedly-90th-percentile line is only covering 75% of test
   actuals).

3. **The formula produces impossible negative excursion magnitudes** —
   confirmed, for both candidates, checked directly against the full
   1,014-row dataset: linear regression predicts negative `mae_R` for 131
   rows (13%, min -9.69) and negative `mfe_R` for 82 rows (8%, min -9.28);
   quantile regression (q=0.5) predicts negative `mae_R` for 74 rows (7%,
   min -4.56) and negative `mfe_R` for 77 rows (8%, min -4.64). Neither
   linear nor plain quantile regression enforces the non-negativity
   constraint the label contract requires. A log-linear or
   strictly-positive-link formulation (explicitly suggested as an option
   in the task brief) was not fit in this pass and would be required
   before either candidate could even be considered structurally valid,
   separate from the predictive-power problems above.

4. **Regime instability in the volatility-tercile stratification** — the
   validation-period stratification by `sigma_day` tercile (boundaries fit
   on train) puts 348 of 350 validation touches in the "high" tercile and
   only 2 in "mid," with **zero** in "low" — i.e. the 2025 vol regime sits
   almost entirely outside the range the tercile boundaries were fit on in
   2023-2024. This alone is enough to explain much of the validation/test
   miscalibration above: the training period's volatility distribution is
   not representative of the later periods.

5. **Coefficient/bias direction is not stable across folds** — the
   `mfe_R` linear-model bias alternates sign across the 5 folds (+0.27,
   +0.69, +0.08, -0.81, -0.13) rather than converging toward zero or a
   consistent sign, which is the walk-forward "coefficient stability"
   check the task requires, and it fails it.

### What did NOT clearly fail

- **Causality/leakage**: `LEAKAGE_AUDIT.md` passes every check — every
  feature used is provably knowable at or before `touched_at`, labels are
  provably >=0, the R-denominator is provably >0, and the chronological
  split embargo dropped 0 rows (no touch's label horizon crossed a split
  boundary in this dataset, verified programmatically).
- **Sample-size-vs-terms ratio** is thin (535 training rows / 10 features
  = ~53 rows per term) but not absurd on its own; the walk-forward and
  test-set degradation are better explained by regime non-stationarity
  (point 4 above) than by bare overfitting to noise.

## Explicit classification (per the task's required categories)

- Descriptive only: **yes** — the fitted coefficients describe patterns in
  the 2023-2024 training window.
- Retrospectively fitted: **yes** — every parameter (grid selection,
  regression coefficients, split boundaries, vol terciles) was chosen by
  looking at this exact historical sample.
- Validated on later untouched data: **no** — validation and test both
  show the formula losing to a naive baseline and/or degrading materially.
- Sufficiently stable for prospective monitoring: **no** — bias sign flips
  across folds, tercile stratification collapses out-of-training-range,
  test-set coverage misses badly.
- Suitable for live use: **no.**

## What would need to change before revisiting this

1. A strictly-positive-link formulation (log-linear or gamma-GLM-style) to
   satisfy the non-negativity constraint structurally, not by luck.
2. Either materially more GC history (the ~3-year sample here is short
   relative to the regime drift observed) or an explicit, causal
   regime-normalization of `sigma_day`/`vol_close_prior` fit only on
   trailing data (not train-then-frozen) so tercile boundaries track the
   live regime instead of a stale training-period snapshot.
3. Re-running the walk-forward comparison against the naive baseline as
   the primary go/no-go gate — a candidate formula should not be reported
   as "the recommendation" unless it beats the unconditional median on a
   majority of held-out folds, which none did here.

No further parameter search, redesign, or optimization is authorized
beyond what's reported here without further instruction — per the task's
own framing, this is a diagnostic study, and the diagnostic conclusion is
that this class of simple interpretable formula, on this sample, does not
yet earn its keep over doing nothing more sophisticated than reporting the
unconditional median.
