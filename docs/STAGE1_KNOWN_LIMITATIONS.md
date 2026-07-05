# Stage 1 Known Limitations

- **Starting commit substitution.** The requested starting commit
  (`verification/codex-stage0-v1` @ `9408dae...`) does not exist in this
  repository. This branch starts from `research/claude-stage0-excursions`
  @ `05fd1c8` instead, per explicit user direction. All required section-5
  population numbers were re-verified to match exactly before proceeding.
- **Canonical bars file byte-hash.** Still `9f427eb0...`, not `3d0228fc...`
  -- carried over from Stage 0/verification; content-equivalence already
  established as rigorously as this environment allows (see
  `verification/claude-baseline-v1`).
- **Learned-formula coefficient constraints are post-hoc, not in-loop.**
  `sklearn.linear_model.QuantileRegressor` has no bounded/sign-constrained
  solver option; nonnegativity (range/ATR) and the RVOL bound are enforced
  by clipping the fitted coefficients after an unconstrained fit, not via a
  constrained quantile LP. See `docs/STAGE1_TPSL_REPORT.md` for how often
  clipping actually changed a coefficient.
- **`rvol_120m` residual missing rate ~9%**, not the ~3-4% the spec
  anticipated, after the session-anchored fix (down from Stage 0's ~65%
  fixed-clock-alignment defect). The remaining gap is touches occurring
  within the first 120 minutes of a research session (no completed
  same-session bucket yet) plus early-2018 sessions lacking a full 15-30
  session history. This is a real, explainable residual, not a
  re-introduced alignment bug -- `RVOL_30`/`RVOL_60` are ~5-7% missing.
- **Perturbation lookback-window substitutions.** The spec asks for
  range/ATR lookback perturbations at 20/45-minute granularity; the
  underlying Stage 0 feature table only has 15/30/60/120-minute range and
  5/15/30/60-minute ATR windows. Where an exact requested window doesn't
  exist, the nearest already-computed preregistered window is substituted
  and logged explicitly in the perturbation output, never silently.
- **Month-block bootstrap resamples calendar months, not fixed-length
  blocks**, since trade density varies significantly across months/years;
  this preserves within-month trade order as required but means block
  "length" (trade count) varies by which month is drawn.
- **2026 diagnostic uses partial-year data** (through the archives'
  2026-06-07 cutoff) -- reported as a partial year, not annualized.
