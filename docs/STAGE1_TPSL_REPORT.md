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

## 3-14. [Populated once background computation completes]

Sections covering the 980 simple candidates, walk-forward selection, 36
learned candidates, controls, volume-increment test, perturbations,
causal-roll sensitivity, and bootstrap are completed in the next report
revision once the corresponding scripts finish running (see task list /
final chat response for live status).
