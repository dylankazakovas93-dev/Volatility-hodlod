# OG Regime Kill-Switch — Mechanism Specifications

## Scope and purpose

This is a **diagnostic monitoring study**, not a strategy re-optimization.
Nothing here touches level generation (`src/strict_engine.py`), management
(`src/og_management_variants.py`), RR, or window/blackout logic. Every
mechanism below is a pure post-hoc filter over an **already-simulated**
trade sequence for `OG_PRIMARY_150R` and `OG_OPERATIONAL_100R`: at trade
index `i`, the mechanism outputs a boolean "flat" state and, if flat, that
trade's pnl and R are set to 0 (the touch is treated as skipped). No
mechanism ever changes which trades occur, their entry/exit prices, or their
un-gated pnl/cap.

## Causality requirement

At any index `i` in the chronological trade sequence, the kill-switch state
applied to trade `i` may depend only on trades `0..i-1` (strictly before
`i`) plus fixed pre-registered constants. It must never depend on trade `i`
itself or any later trade. All four mechanisms below are implemented as a
single left-to-right scan over the sequence (`src/og_regime_killswitch.py`)
where the flat/on decision for row `i` is recorded **before** that row's own
outcome is folded into the running statistic. This is verified directly by
`tests/test_regime_killswitch_causality.py`, which asserts that appending
future trades never changes the recorded state of any earlier trade
(prefix-invariance test, in the same style as `tests/test_og_hmm_causality.py`
for the Stage D HMM forward filter).

## Mechanism 1 — Rolling PF over a trailing trade-count window

`rolling_pf_killswitch(df, window, threshold, reentry_threshold=None)`

- At trade `i`, compute PF (points-based, `sum(gains)/sum(losses)`) over the
  trailing `window` trades `i-window .. i-1` (strictly prior).
- Go flat when trailing PF drops below `threshold`.
- Resume when trailing PF recovers:
  - **symmetric** re-entry: recovers to `>= threshold` (same bar).
  - **hysteretic** re-entry: recovers to `>= threshold + 0.15` (a higher
    bar, to reduce whipsawing right at the edge of the threshold).
- Preregistered grid: `window in {50, 100, 150, 200}` (a handful of
  round trade counts spanning roughly 1-4 months of this strategy's trade
  cadence), `threshold in {0.90, 1.00, 1.10}` (below breakeven, at
  breakeven, and modestly above breakeven PF). 4 x 3 x 2 re-entry modes = 24
  variants per config, all fixed in advance, not searched adaptively.
- Causal: the trailing window strictly excludes trade `i`; the on/off state
  is a running scan depending only on past PF values and the previous
  state.

## Mechanism 2 — Rolling win rate + rolling avg R/trade (diagnostic overlay)

`rolling_diagnostics(df, window)`

- Same trailing, strictly-prior windows as Mechanism 1, but reporting
  trailing win rate and trailing avg R/trade instead of PF. This is used
  purely to characterize *why* a given rolling-PF dip happened (win-rate
  collapse vs. payoff/avg-R collapse) — it is not wired into its own
  kill-switch. We considered defining a rolling-avg-R kill-switch
  separately, but decided against it: avg R/trade and PF are highly
  collinear here (this is a fixed-target-R strategy, so PF already captures
  most of the same information as avg R), and adding a second, nearly
  redundant switch would only add whipsaw risk without new information. The
  overlay is written to
  `outputs/og_regime_killswitch/{config}_rolling_diagnostics.csv` for all 4
  windows.

## Mechanism 3 — One-sided CUSUM change-point detection on trade-level R

`cusum_killswitch(df, target_mean, k, h, cooldown_trades)`

- Standard one-sided (downward-drift) CUSUM recursion on the cap-normalized
  R-sequence:
  `S_down_i = max(0, S_down_{i-1} - (R_i - target_mean) - k)`,
  alarm when `S_down_i > h`. A symmetric upward accumulator `S_up` is also
  tracked and used only as an early "all clear" signal.
- Parameters, chosen by standard SPC (statistical process control)
  convention rather than search:
  - `target_mean` = the pooled average R/trade over the **full** historical
    sequence for that config (a fixed reference level, not adaptively
    re-estimated).
  - `k` (the reference/slack value) = half of the pooled R standard
    deviation — the textbook SPC choice for detecting a shift of
    roughly 1 sigma.
  - `h` (decision interval) = `4.5 * k`, the midpoint of the standard
    4-5x-k convention for a CUSUM chart.
  - `cooldown_trades in {20, 30, 50}` — small preregistered set for how
    many trades of no further downward alarm are required before resuming
    (in addition to resuming immediately on an upward alarm).
- Causal: `S_down_i` and `S_up_i` are updated using trade `i`'s own R
  **after** the flat/on decision for trade `i` has already been recorded
  from `S_down_{i-1}`; the alarm that gates trade `i` only ever reflects
  information through trade `i-1`.

## Mechanism 4 — Non-winning-streak tracking vs. a build-year baseline

`compute_nonwin_streaks(df)` / `streak_killswitch(df, baseline_streaks, percentile, resume_after_wins)`

- Baseline: the distribution of max non-winning-streak lengths (BE trades do
  not count as wins or as breaking the streak toward a win — only pnl > 0
  ends a streak) is computed **once**, from the build-year trades only
  (2018/2020/2023/2026 — the years never diagnosed as failing in this
  research line), separately per config. This baseline is a fixed constant
  passed into the kill-switch, not recomputed adaptively during the scan.
- Kill-switch: go flat once the current (strictly-prior) non-winning streak
  exceeds the `percentile`-th percentile of the build-year baseline,
  `percentile in {90, 95, 99}` (small preregistered set). Resume after 3
  consecutive winning trades (`resume_after_wins = 3`, fixed).
- Causal: the running streak counter used to gate trade `i` is updated with
  trade `i`'s own win/loss outcome **after** the gating decision for trade
  `i` is recorded.

## Parameter-set discipline

All grids above were fixed before running the backtest sweep in
`scripts/og_regime_killswitch_backtest.py` (24 rolling-PF variants, 3 CUSUM
variants, 3 streak variants, per config = 30 non-baseline variants x 2
configs = 60 rows, plus 2 baseline rows = 62 total rows in
`outputs/og_regime_killswitch/killswitch_summary.csv`). No parameter outside
these sets was tried and discarded; there was no iterative narrowing based on
which numbers looked best.
