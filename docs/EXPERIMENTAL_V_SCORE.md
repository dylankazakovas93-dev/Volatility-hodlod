# EXPERIMENTAL — V-Score Entry Gate

**Status: EXPERIMENTAL. NOT part of the frozen baseline. NOT authorized as
a replacement or update to `configs/nq_current_config.yaml`.** This lives
on branch `experimental/v-score-gate`, separate from `handoff/nq-strict-engine-v1`.

## What this is

A causal entry filter proposed externally (packaged as ready-to-integrate
code + an instruction prompt) on top of the frozen strict engine. Rather
than integrate the proposed toy skeleton (which had no anchor/cap sizing,
no BE, no SAL, no session windows — a different, much simpler backtest),
`src/experimental_v_score_engine.py` reuses the actual verified state
machine from `src/strict_engine.py` and adds exactly one new gate, so the
V-Score threshold is the only new variable, not a wholesale re-implementation.

## V-Score definition (causal, no lookahead)

For the 15 bars strictly before the touch bar:

```
v_score = abs(close[-1] - open[0]) / sum(volume)
```

A trade is only taken if `v_score >= v_score_threshold`. A touch that fails
the gate is still consumed (matches the frozen "once touched, always
consumed" rule) — it does not become eligible again.

## Why the threshold is a fixed sweep, not a fitted value

The originally-proposed instructions said to set the threshold to *"the
median value derived from the 2026 data"* — that is in-sample parameter
fitting, exactly what the handoff's README explicitly states is not yet
authorized. Instead, four thresholds were fixed **before running anything**:

```
V_SCORE_THRESHOLDS = [0.0, 0.01, 0.05, 0.1]
```

`0.0` is a control (should reproduce the frozen baseline exactly, proving
the gate wiring doesn't silently alter anything when inactive). The other
three are round numbers spanning a plausible range, chosen without having
looked at the metric's actual distribution on this data.

## Corrected invariant

The originally-proposed code asserted `len(consumed_sides) <= 1841`. This
conflates two different populations: **1,841** is the eligible-candidate
gate (after entry-window/anchor/cutoff filters); the actual upper bound on
any touch-attempt count is the **3,486** physical touches found across the
whole dataset. The corrected assertion in
`src/experimental_v_score_engine.py::_assert_invariants` checks
`len(executed) <= total_physical_touches (3486)`, plus a genuine
no-overlap check (`entry[i] >= exit[i-1]` for every consecutive pair,
sorted by entry time). Both pass at every threshold tested.

## Results (illustrative sweep, none selected/recommended)

| Threshold | Rejected | Executed | Net pts | PF | Negative years |
|---|---|---|---|---|---|
| 0.0 (control) | 0 | 1,107 | +6,648.17 | 1.2924 | 2019, 2023, 2024 |
| 0.01 | 1,372 | 194 | +2,262.77 | 1.5877 | 2018, 2021, 2025 |
| 0.05 | 1,691 | 0 | — | — | — |
| 0.1 | 1,691 | 0 | — | — | — |

**Control passes:** threshold 0.0 reproduces the frozen baseline exactly
(1,107 / +6,648.17 / 1.2924) — the gate has zero effect when set to a
no-op threshold, confirming the integration doesn't silently change
anything on its own.

**Read with caution, not enthusiasm:** 0.01 shows a higher PF (1.59 vs
1.29) but on 194 trades instead of 1,107 — an 82% reduction in sample size,
with a *different* set of negative years (2018/2021/2025 instead of
2019/2023/2024), not a strict improvement on the same population. This is
exactly the kind of result that looks attractive on a headline PF number
and would require the full robustness apparatus (fold gates, walk-forward,
parameter-neighborhood stability) explicitly withdrawn earlier in this
project before it could mean anything. 0.05 and 0.1 reject every single
touch — the metric's typical range on this data sits below 0.01, so those
two thresholds are degenerate (all-reject), not informative.

## What this is not

- Not a validated strategy improvement.
- Not merged into `src/strict_engine.py` or `configs/nq_current_config.yaml`.
- Not run through the alternating-fold gates, walk-forward selection, or
  any of the robustness machinery specified (and withdrawn) earlier.
- Not evidence that V-Score filtering "works" — a 194-trade sample with a
  different set of losing years than the baseline needs the full
  robustness apparatus before that claim could be made honestly.

## Reproducing this sweep

```
python3 -m src.experimental_v_score_engine \
    --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
    --vxn  data/vxn_daily_2018_2026.csv \
    --out-dir outputs_experimental
```
