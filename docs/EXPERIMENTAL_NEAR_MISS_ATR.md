# EXPERIMENTAL — Near-Miss Entries, ATR-Scaled Tolerance

**Status: EXPERIMENTAL curiosity/diagnostic. NOT part of the frozen
baseline. Sample sizes are too small to draw a strategy conclusion.**

## The question

"Levels don't even hit — if price moved a few more points I'd have banked
it." Two sub-questions: (1) how often does that actually happen, using a
volatility-scaled distance instead of a fixed point count, and (2) if you
entered early on those near-misses, would it have helped or hurt?

## Method

- **3-minute ATR(14):** simple rolling mean of True Range over 14
  three-minute bars, looked up causally (only from a bar that has fully
  closed strictly before the reference timestamp).
- For every level side the strict touch rule never actually touches, found
  its closest approach distance to price across its whole live window,
  expressed in units of that causal ATR (`dist_in_atr = closest_distance /
  ATR_at_that_moment`).
- **Control check:** ran the full engine with near-miss entries disabled
  entirely — reproduced the frozen baseline exactly (1,107 / +6,648.17 /
  1.2924), confirming the added logic doesn't silently change anything
  when inactive.
- **Experimental variant:** for three preset tolerances (0.25, 0.5, 1.0
  ATR — fixed before running anything), treated near-misses within that
  tolerance as entry triggers, filled at the **actual price reached** (the
  bar's high or low, whichever is relevant to the side), not the pristine
  level — a resting limit order at the level itself never would have
  filled, so crediting a fill at the level would be fabricating a better
  price than was ever actually available.

## Descriptive result — how rare is a genuine near-miss?

| Tolerance | Untouched levels within range | % of untouched (852 total) | % of all level sides (4,338 total) |
|---|---|---|---|
| 0.25 ATR | 13 | 1.5% | 0.3% |
| 0.5 ATR | 29 | 3.4% | 0.7% |
| 1.0 ATR | 73 | 8.6% | 1.7% |

Median distance for an untouched level's closest approach: **6.5 ATRs**.
Most "it almost hit" moments are, objectively, much farther from the level
than they feel live. Genuine close calls are uncommon.

## Experimental result — would early entry have helped?

| Config | Trades added | Near-miss PnL | Full net | Full PF | Negative years |
|---|---|---|---|---|---|
| Control (disabled) | 0 | — | +6,648.17 | 1.2924 | 2019, 2023, 2024 |
| 0.25 ATR | 1 | +88.50 | +6,736.67 | 1.2963 | same |
| 0.5 ATR | 6 | +469.88 | +7,118.04 | 1.3131 | same |
| 1.0 ATR | 13 | +1,104.88 | +7,753.04 | 1.341 | same |

Unlike the V-Score and Anchor-Flow gates (both of which collapsed
performance when tested), this variant shows a **consistent small positive
lean at every tolerance tested** — every near-miss trade group was net
positive, PF improves slightly each step, no new negative years, drawdown
doesn't worsen.

## Why this is not a finding, just a lead

- **Sample size is tiny.** 1, 6, and 13 trades respectively across 8+
  years of data. A result that clean on 13 trades has enormous variance —
  it would take very little to flip it negative with the next handful of
  occurrences. This is not statistically meaningful on its own.
- **This is a different order type, not "the same trade happening more."**
  Filling at the actual price reached (rather than the level) means a
  systematically worse average entry than the core strategy gets — the
  fact that it still came out positive here is interesting, but conflates
  "does near-miss timing carry information" with "is the fill price
  attractive," and this test doesn't separate those two effects.
- **No robustness testing performed** — no fold gates, no walk-forward, no
  parameter-neighborhood stability check (the same apparatus withdrawn
  earlier in this project). A clean-looking result at 3 preset tolerances
  is not the same as a validated edge.

## Bottom line

Worth remembering, not worth acting on. If you want to pursue this
further, the honest next step is accumulating more sample (a much longer
history or a different but related instrument) before treating the
positive lean as real, not tuning the tolerance further on this same
852-level sample.

## Reproducing this analysis

```
python3 -m src.experimental_near_miss_analysis \
    --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
    --vxn  data/vxn_daily_2018_2026.csv \
    --out-dir outputs_experimental
```
