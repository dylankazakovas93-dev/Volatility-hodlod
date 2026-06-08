# Initial test results — μ ± k·σ/√(dev) levels on GC, 2023-06 → 2026-05

Status: **first pass complete, results are mixed — not a clean "yes the levels react"**

## Data used

- **Price**: Aidan's Databento GLBX MDP3 1-minute OHLCV dump
  (`glbx-mdp3-20230601-20260531.ohlcv-1m.csv.zst`, 2023-06-01 → 2026-05-31).
  It contains every GC/MGC contract + calendar spreads simultaneously, so I
  built a continuous front-month series: for each day, pick the standard GC
  contract (excludes micros/spreads) with the highest traded volume, and use
  only that contract's bars for the day. 15 rolls over the period, all logged
  in `data/gc_1m/gc_continuous_1m.csv` (`contract` / `roll_day` columns). This
  is **not back-adjusted** — see the caveat in `scripts/build_gc_continuous.py`.
- **Vol index**: `data/gvz_daily.csv` (CBOE GVZ, sourced from Yahoo's `^GVZ`
  since FRED is unreachable from this sandbox — see README for details).

Reproduce with:
```
python3 scripts/build_gc_continuous.py --in <decompressed_csv> --out data/gc_1m/gc_continuous_1m.csv
python3 scripts/backtest_levels.py --ohlcv data/gc_1m/gc_continuous_1m.csv \
    --out-levels out/gc_levels.csv --out-results out/gc_level_reactions.csv
python3 scripts/analyze_by_year_side.py --results out/gc_level_reactions.csv
```

## Headline numbers (all sessions, 2023-06 → 2026-05)

- 773 sessions produced levels → 1,546 levels (upper+lower).
- **60% touch rate** within 5 trading days of being placed.
- Of touched levels, whether price reacts (reverses back through the level)
  vs. continues (blows through it) is **basically a coin flip in aggregate**:
  ~49-57% "reaction wins" depending on horizon, with near-zero net bias
  (median `reaction - continuation` within ±0.5pts at every horizon from
  5m to 120m). See full table in `out/gc_level_reactions.csv`.

**On its own, the aggregate says: no consistent edge — price moves about as
far in the "rejection" direction as it does in the "blow-through" direction
after a touch.** That's consistent with these levels behaving like generic
statistical reference points rather than true magnets/walls.

## But — the year-by-year / side-by-side breakdown is more interesting

(`scripts/analyze_by_year_side.py` output, `net_bias = reaction − continuation`,
positive = price favored reversal)

- **Magnitudes balloon in 2026**: median reaction size on touched lower levels
  goes from ~2-9 pts (2023-2025) to **~16-28 pts** in 2026 — a real, large
  jump, consistent with your observation that 2026 produced unusually violent
  level reactions. GVZ itself spiked from ~17 to ~29 over the period, so this
  tracks with a genuine volatility regime change, not a fluke.
- **But the directional edge is asymmetric and regime-dependent**:
  - *Lower levels* (support-side) in 2026: 50-59% reaction-win rate, median
    net bias **positive** (+0.5 to +2.9pts) — i.e. some real lean toward
    rejection/bounce.
  - *Upper levels* (resistance-side) in 2026: only 37-51% reaction-win rate,
    median/mean net bias **strongly negative** (−4.6 to −9.5pts at 60-120m) —
    i.e. price tends to *blow through* upper levels rather than reject from
    them. This is exactly what you'd expect in a strong uptrend (gold has
    been trending up hard through 2025-2026): "resistance" levels keep
    getting run over while "support" levels see more genuine bounces.
  - 2023-2025 show smaller, noisier versions of the same lower > upper
    asymmetry, but it's much weaker — 2026 is where it really shows up.

## What this suggests

The "huge reactions" you're seeing in 2026 look real in terms of *magnitude*
(price genuinely moves a lot after touching these levels — both in the
rejection and continuation directions), but the *edge* isn't simply
"price reverses at the level." It looks more like:

- These levels mark zones of **high subsequent volatility/displacement**
  (a real, useful property — a breakout/violent-move filter), and
- The **direction** of that displacement is conditioned on the prevailing
  trend and which side of the level you're looking at (lower levels catch
  bounces in an uptrend; upper levels get run over).

A strategy built on "fade every touch" would likely get chopped up on the
upper-level side in a trending market. A trend-aware version — e.g. only
fade lower levels in uptrends / only fade upper levels in downtrends, or
treat a touch as a **volatility-expansion signal** and trade the breakout
in the direction of the larger subsequent move — looks more promising given
these numbers.

## Open items / what to check next

1. **Back-adjustment**: the continuous series isn't back-adjusted across the
   15 contract rolls. Roll-day price gaps could be creating spurious touches
   of persisted untouched levels — worth cross-checking hits against the
   `roll_day` flag in `data/gc_1m/gc_continuous_1m.csv` / filtering them out
   and re-running to see if the numbers move.
2. **Trend-conditioning**: split results further by prevailing daily trend
   (e.g. price vs. its 20/50-day MA at session open) to test the "lower
   levels bounce in uptrends, upper levels get run over" hypothesis directly.
3. **Multi-touch / retest behavior**: we currently only score the *first*
   touch of each level. Worth tracking what happens on 2nd/3rd touches.
4. **Reaction threshold tuning**: `--reaction-threshold` is currently 0 (any
   wobble counts). Once a directional hypothesis is set, tune this to match
   what a real entry/stop would look like.
