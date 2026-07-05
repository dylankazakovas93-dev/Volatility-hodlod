# EXPERIMENTAL — Anchor-Flow Divergence Gate

**Status: EXPERIMENTAL. Tested and REJECTED by the data.** Not part of the
frozen baseline. Lives on branch `experimental/v-score-gate`, not merged
anywhere near `handoff/nq-strict-engine-v1`.

## The hypothesis, as proposed

"In 2026, NQ enters our levels in a mean-reversion-ready state — price
moving against the 15-minute trend but with the 60-minute anchor. In the
losing years (2023/2024), price is moving *with* the 15-minute trend and
*with* the 60-minute anchor (a breakout-momentum move crashing into the
level)." Claimed benefit: "This filter... will not cut your trade count; it
will refine your entry probability."

## Correction made before running anything

The proposed code read `df['close'].iloc[current_idx]` — the touch bar's
**own** close — in both the 60m anchor and 15m flow legs. Using a bar's own
close to decide whether to trade on that same bar is a same-bar look-ahead:
the bar hasn't finished at the moment of touch. Both legs were re-anchored
to `iloc[touch_idx - 1]` (the last fully-closed bar strictly before the
touch), matching the same "no information from the bar you're acting on"
standard the rest of this engine already applies (e.g. the touch-bar
stop-first rule in `src/strict_engine.py`).

```
anchor_direction = close[touch_idx - 61] - close[touch_idx - 1]   # 60m lookback
flow_direction    = close[touch_idx - 15] - close[touch_idx - 1]   # 15m lookback
coherent = sign(anchor_direction) != sign(flow_direction)
```

## Result — the hypothesis does not hold on this data

```
total physical touches: 3486
incoherent_rejected:    1602
executed:               58        (vs. 1107 in the frozen baseline)
net_pts:                -680.61   (vs. +6648.17 baseline)
PF:                     0.5985    (vs. 1.2924 baseline)
max_drawdown:           -977.61
negative years:  2018, 2021, 2022, 2023, 2024, 2025  (6 of 9 years)
```

| Year | n | Net | PF |
|---|---|---|---|
| 2018 | 7 | -43.50 | 0.61 |
| 2019 | 5 | +15.38 | 1.87 |
| 2020 | 8 | +193.12 | 2.51 |
| 2021 | 4 | -162.38 | 0.00 |
| 2022 | 7 | -359.62 | 0.10 |
| 2023 | 8 | -24.75 | 0.88 |
| 2024 | 9 | -37.50 | 0.84 |
| 2025 | 9 | -393.36 | 0.10 |
| 2026 | 1 | +132.00 | inf |

## Both claims in the proposal are contradicted directly

1. **"It will not cut your trade count."** It rejects 1,602 of 1,660
   attempted trades (97%), leaving 58 — a far more aggressive cut than the
   V-Score gate's 0.01 threshold (which left 194).
2. **"It specifically targets the cause of the stop-outs... 2023/2024 are
   breakout setups, 2026 is exhaustion."** The data shows the opposite of
   the intended effect: net PF drops from 1.29 to 0.60, and the gate turns
   three of the baseline's profitable years (2018, 2021, 2022 — none of
   which were even in the original negative-years list [2019, 2023, 2024])
   negative, while barely touching the actual originally-negative years
   (2023: -24.75 on 8 trades, 2024: -37.50 on 9 trades — still losing, not
   fixed). 2026 shrinks to a single trade, too small to support any claim
   about a "2026 regime."

The premise that "2026 profitability" and "2023/2024 losses" map cleanly
onto a directional-alignment signal is not supported here. If anything,
this filter is anti-correlated with the years it was designed to protect.

## What this means

This is a negative result, reported as such. It does not get iterated on
by adjusting the lookback windows or flipping the inequality to search for
a version that "works" — that would be exactly the post-hoc curve-fitting
this project has been explicitly guarding against. If there's a genuine
regime-detection signal in the 2026 data, this specific formulation isn't
it.

## Reproducing this result

```
python3 -m src.experimental_anchor_flow_engine \
    --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
    --vxn  data/vxn_daily_2018_2026.csv \
    --out-dir outputs_experimental
```
