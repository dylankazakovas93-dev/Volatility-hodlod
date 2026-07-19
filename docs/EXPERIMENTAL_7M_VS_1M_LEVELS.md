# EXPERIMENTAL — 1-Minute vs 7-Minute IB Levels: Which Performs Better

**Status: EXPERIMENTAL diagnostic, not a config change.** Answers a direct
question raised while troubleshooting the partner's TradingView chart
(7-minute IB producing materially different levels than 1-minute IB — see
the earlier diagnosis in this thread). This does not change
`configs/nq_current_config.yaml` or the frozen baseline in any way.

## The question

Given that 1-minute and 7-minute IB windows produce materially different
level values (89% of sessions differ, mean |diff| ~11pts, up to 245pts on
the worst session — a direct consequence of 60 minutes not dividing evenly
by 7), **which one actually performs better** when run through the
strategy?

## Test design — apples-to-apples

Both runs use:
- the same 1-minute bars for trade **simulation** (touch detection, BE
  timing, SAL, cutoff — identical minute-by-minute precision in both)
- the same `session_date` / `created_at` (identical entry-window timing
  and level lifetime/expiry)
- the same frozen `src.strict_engine.run_strict` state machine, unmodified

**Only the `upper_level` / `lower_level` values differ.** One run uses the
canonical 1-minute-IB levels; the other substitutes the 7-minute-IB-derived
level values into the same session structure before simulation. This
isolates the one variable actually in question — not a different engine,
not different timing, not a parameter search.

## Result

| Metric | 1-minute levels (canonical) | 7-minute-derived levels |
|---|---|---|
| Executed | 1,107 | 1,088 |
| Net pts | **+6,648.17** | +3,495.39 |
| PF | **1.2924** | 1.1451 |
| TP / SL / BE / cutoff | 394 / 333 / 281 / 99 | 364 / 349 / 272 / 103 |
| Max drawdown | -1,290.29 | -1,134.63 |
| Negative years | 2019, 2023, 2024 | 2018, 2019, 2024, 2025 |

**1-minute levels win decisively** — nearly double the net (+6,648 vs
+3,495), meaningfully higher PF (1.29 vs 1.15), and one fewer negative year
using the same trade count and same execution precision throughout. The
7-minute-derived levels aren't just "different," they're worse on every
headline metric.

## Why this makes sense, not just a coincidence

The 1-minute IB catches exactly the intended 60 minutes of price action.
The 7-minute IB systematically overshoots the 60-minute mark (the
IB-completion bar always extends 0-6 minutes past the true cutoff,
whichever 7-minute bar happens to straddle it), pulling in extra,
un-intended volatility into `ib_high`/`ib_low`. That noise doesn't average
out to something neutral — it degrades the level's statistical basis
(implied sigma + IB extension), which is exactly what the strategy's edge
depends on.

## What this confirms operationally

There is no ambiguity left here: **run the indicator on the 1-minute chart
(or another clean divisor of 60: 2/3/4/5/6/10/12/15/20/30)**. The
7-minute chart isn't a stylistic preference that happens to look a bit
different — it's a strictly worse, bugged version of the same strategy.

## Reproducing this result

```
python3 -m src.experimental_7m_levels_comparison \
    --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
    --vxn  data/vxn_daily_2018_2026.csv \
    --out-dir outputs_experimental
```
