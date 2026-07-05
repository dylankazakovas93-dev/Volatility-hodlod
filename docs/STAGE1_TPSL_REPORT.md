# Stage 1 Report -- Dynamic TP/SL Discovery

Research branch: `research/claude-stage1-tpsl-v1`

## 1. Reproduction of required Stage 0 populations (section 5)

Reproduced exactly on this branch before any Stage 1 work began:

| Metric | Required | Reproduced |
|---|---|---|
| Total level sides | 4,338 | 4,338 |
| Physical first touches | 3,486 | 3,486 |
| Qualifying independent signal paths | 3,331 | 3,331 |
| Excluded gap touches | 137 | 137 |
| Excluded 15:59-bar touches | 17 | 17 |
| Excluded no-valid-path touches | 1 | 1 |
| Cutoff-only executed | 1,393 | 1,393 |
| Cutoff-only position-open skips | 1,938 | 1,938 |
| Cutoff-only net (pts) | +3,334.90 | +3,334.9 |
| Cutoff-only PF | 1.0448 | 1.0448 |
| Cutoff-only win rate | 48.53% | 48.53% |
| Cutoff-only avg trade | +2.394 | +2.394 |
| Cutoff-only max DD (pts) | -4,567.93 | -4,567.93 |

## 2. Stage 0 definition corrections (section 6)

- Signed path extrema retained verbatim as `signed_mfe_pts` / `signed_mae_pts`.
- Conventional (nonnegative) fields added: `conventional_mfe_pts = max(0, signed_mfe_pts)`,
  `conventional_mae_pts = max(0, -signed_mae_pts)`.
- Reconciled exactly: **72** negative signed MFE, **76** positive signed MAE
  (both match the spec's expected counts exactly).
- Session-anchored RVOL rebuilt (18:00 ET-anchored, non-overlapping
  30/60/120-minute buckets, historical comparison against the same bucket
  index over the prior 15/20/30 completed sessions only): `rvol_120m`
  missing rate improved from Stage 0's ~65% (fixed-clock alignment defect)
  to **~9.2%** -- a large, real improvement, though not quite the spec's
  anticipated 3-4% (see `docs/STAGE1_KNOWN_LIMITATIONS.md` for why the
  residual gap is expected). `rvol_30m`/`rvol_60m` missing rates are ~5-7%.
- Rank-stability diagnostic replaced: Spearman rho between the
  with-2026/ex-2026 CoV rankings = **0.825**; top-3 membership **changes**
  between the two (with 2026: atr14_60m, prev_session_range, range_30m;
  ex-2026: range_15m, range_30m, range_60m) -- a real, non-degenerate
  result, unlike the old all-1.0 self-correlation artifact.

## 3. Required controls (section 25)

| Control | Executed 2018-2025 | Net (pts) | PF | avg R |
|---|---|---|---|---|
| Cutoff-only (no TP/SL) | 1,393 | +3,334.9 | 1.0448 | n/a |
| 1.0x range_30m | 2,102 | -3,457.74 | 0.9226 | -0.0766 |
| 1.0x atr14_60m | 2,251 | -2,723.93 | 0.9394 | -0.0585 |
| 1.0x prev_session_range | 1,468 | -2,263.25 | 0.9692 | -0.0154 |
| 1.0x geomean(range30,atr60) | 2,153 | -2,791.56 | 0.9354 | -0.0710 |

All four naive 1:1 simple-scale controls are unprofitable -- any candidate
worth selecting needs to beat these, not just the cutoff-only baseline.

## 4. Simple family: 980 candidates + walk-forward (sections 9-12, 15-16)

All 980 preregistered candidates (4 scales x 5 gammas x 7 TP-mult x 7
SL-mult) were replayed once via full 2018-2026 chronological one-position
first passage (`outputs/stage1_simple_all_candidates.csv`).

Robust-neighborhood walk-forward selection (`outputs/stage1_neighbourhoods.csv`,
`outputs/stage1_outer_test_results.csv`) shows **no scale produces a stable,
consistently-profitable medoid across the 5 outer folds**:

- Several (scale, fold) combinations have **no profitable training-period
  neighborhood at all** (S1_range30m misses folds 2021/2025; S2_atr60m
  misses 2021; S4_geomean misses 2021/2022/2025) -- the grid simply
  doesn't contain a connected profitable region in training for those years.
- Where a medoid *is* selected, test-year outcomes swing between
  near-total wins (PF = inf, e.g. S1 in 2022: +1,294 pts, 0 losers in a
  246-trade sample) and near-total losses (PF = 0.0, e.g. S1 in 2024:
  -783 pts) -- a classic signature of an unstable, non-generalizing
  parameter region rather than a genuine edge.
- S3_prevsessrange is the only scale with all 5 folds populated; its
  aggregate test-year net is **-1,513.56 pts** (3 of 5 years profitable,
  but the 2 losing years erase more than the 3 winners combined).

**Volume-increment test** (section 22, `outputs/stage1_volume_increment.csv`):
across all 784 paired (nonzero-gamma vs. gamma=0) comparisons in the
2018-2025 development ledger, gamma-adjusted variants beat their no-volume
control only **51.0%** of the time, with a median improvement of **+0.0001
avg R** and **+0.00045 PF** -- statistically indistinguishable from no
effect. **RVOL adds no repeatable value in the simple family; the
conclusion is stated plainly: omit it.**

**Conclusion: the simple family does not produce a candidate that clears
even the "positive aggregate outer-test net" gate criterion, let alone
PF > 1.05.**

## 5. Learned family: 36 candidates + walk-forward (section 13, 15)

Fit via `sklearn.linear_model.QuantileRegressor` per outer fold (see
`docs/STAGE1_KNOWN_LIMITATIONS.md` for the post-hoc coefficient-clipping
simplification). Full per-fold ledger: `outputs/stage1_learned_walkforward.csv`;
aggregated per-candidate: `outputs/stage1_learned_all_candidates.csv`.

**Important metric correction, caught during review:** the first pass
computed each candidate's "aggregate PF" via `profit_factor()` over the 5
per-fold **net-point totals**, effectively treating each test year as a
single trade. This badly overstates PF whenever wins/losses cluster by
year -- the best candidate showed PF = 2.4185 under this method. Recomputed
correctly by pooling actual trade-level gains/losses across all 1,253
pooled out-of-sample trades: **PF = 1.0481**. All learned-family results
below use the corrected, true trade-level PF.

Top candidates by corrected aggregate PF:

| candidate | feature set | net (pts) | PF (true) | median avg R | profitable folds |
|---|---|---|---|---|---|
| F2, mfeq=0.50, maeq=0.50 | range_30m + prev_session_range + RVOL_60 | +1,706.53 | **1.0481** | 0.0339 | 4/5 |
| F4, mfeq=0.65, maeq=0.50 | range_30m + atr14_60m + prev_session_range (no RVOL) | +1,417.65 | 1.0343 | 0.0435 | 3/5 |
| F3, mfeq=0.50, maeq=0.50 | atr14_60m + prev_session_range + RVOL_60 | +1,035.78 | 1.0285 | 0.0254 | 4/5 |

A clear pattern: **only mae_quantile=0.50 candidates are ever profitable**
-- every mfeq/maeq=0.65 or 0.80 combination across all four feature sets
is unprofitable (PF well below 1.0), because higher MAE quantiles predict
wider stops that dilute the R-multiple without a compensating increase in
TP hit rate.

### Best candidate in detail: `learned|fs=F2|mfeq=0.50|maeq=0.50`

Per-fold (`outputs/stage1_learned_walkforward.csv`):

| test year | executed | net (pts) | PF | avg R |
|---|---|---|---|---|
| 2021 | 236 | +887.14 | 1.1541 | 0.0339 |
| 2022 | 271 | +1,064.00 | 1.1361 | 0.0377 |
| 2023 | 242 | +704.08 | 1.1323 | 0.0470 |
| 2024 | 268 | -1,203.08 | 0.8538 | -0.0584 |
| 2025 | 236 | +254.39 | 1.0304 | 0.0146 |

Pooled (1,253 trades): net +1,706.53, **PF 1.0481**, avg R 0.0139, max DD
-30.13R. TP/SL/cutoff = 580/508/165. Long (lower-touch) trades: 610
trades, net +931.25, avg R 0.0180; short (upper-touch): 643 trades, net
+775.29, avg R 0.0100 -- both directions contribute, no side dominates.
2024 is the worst year but doesn't erase all other years' combined gains
(-1,203 vs. +2,910 combined positive years) -- passes that specific gate
criterion in isolation, but the headline PF gate still fails.

**A single formula fit once on the full 2018-2025 period** (the version
that would be frozen for the 2026 diagnostic) performs *worse* than the
walk-forward pooled figure: PF 1.0027 at 1-point cost, and the RVOL
coefficient in the TP equation saturates at its **imposed +0.30 bound in
every one of the 5 outer folds** -- an explicit disqualifier under the
learned-family's additional gate ("no coefficient repeatedly hits an
imposed bound"). Cost sensitivity on this frozen fit:

| cost (pts) | PF | net (pts) |
|---|---|---|
| 0.0 | 1.0407 | +2,040.08 |
| 0.5 | 1.0215 | +1,088.08 |
| 1.0 | 1.0027 | +136.08 |
| 2.0 | 0.9660 | -1,767.92 |

Even at **zero cost**, PF stays below 1.05. There is no cost level at
which this candidate clears the gate.

**2026 diagnostic** (partial year, 98 trades, not used for selection): net
+2,093.32, PF 1.6191, avg R 0.2135. A strong recent-regime number on a
small sample -- reported per section 24's instructions, explicitly not
used to alter the frozen formula or the pass/fail verdict.

## 6. Gate evaluation (section 23)

The best candidate examined (`learned|fs=F2|mfeq=0.50|maeq=0.50`) **fails**
the pass gate at its first substantive criterion:

- Aggregate outer-test PF > 1.05: **FAIL** (1.0481, and 1.0027-1.0407
  across the full 0-2 point cost range on the frozen single-fit version).
- Learned-family additional gate (no coefficient repeatedly at an imposed
  bound): **FAIL** (RVOL/TP coefficient at +0.30 in all 5 folds).

No simple candidate produces a positive, stable aggregate outer-test net
at all (section 4), so the simple family fails even earlier in the gate
sequence.

**Given the core PF gate already fails for the best candidate found by
either family, the remaining battery (full perturbation sweep,
causal-roll sensitivity replay, 5,000-simulation bootstrap) was not run to
completion for a candidate that would not pass regardless** -- see
`docs/STAGE1_KNOWN_LIMITATIONS.md` and `outputs/stage1_summary.json` for
exactly what was and wasn't executed. The causal-roll sensitivity
*bars series itself* was built and is available
(`outputs/nq_causal_roll_2018_2026_1m.csv`, 33 of 2,624 days have a
changed selected contract vs. the same-day rule, 1 fallback logged for the
very first day) for whoever runs the next stage, but was not replayed
against a formula that already fails.

## 7. Final status: STAGE1_FAIL

No preregistered simple or learned TP/SL mechanism clears the required
aggregate outer walk-forward PF > 1.05 threshold under correct trade-level
accounting. The single most promising candidate
(`learned|fs=F2|mfeq=0.50|maeq=0.50`) reaches PF 1.0481 pooled
out-of-sample and additionally exhibits an unstable, bound-saturating RVOL
coefficient -- not a result to build a further stage on.
