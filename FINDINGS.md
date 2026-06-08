# Initial test results — μ ± k·σ/√(dev) levels on GC, 2023-06 → 2026-05

## LATEST — FracDiff filter dropped; ATR-scaled reversion sweep on raw levels (2026-06-08)

**Per direct user instruction: forget continuation, fade/reversion-only. We
first tried gating fades with the user's second indicator (FracDiff Gate, 5m
z-score, "trend sense": lower-level fade needs z ≥ +band, upper-level fade
needs z ≤ −band — see `indicator/fracdiff_gate.pine` / `volgen/fracdiff.py` /
`volgen/fracdiff_reversion.py`). Both agents independently found the SAME
problem and the user told us to drop it: the joint event (level touch AND
FracDiff trend-sense confirmation) is rare — confirmed-touch counts ranged
from ~3 (instant) to ~50-200 (loose 30m lookback) out of ~900 raw touches over
3 years, the configs with the best-looking raw stats turned negative or paper-
thin under a realistic bracket simulation, and several of the "good" small
samples were dominated by clusters of near-simultaneous, correlated touches
(the same underlying price move counted as 3-5 separate "trades").**

So: **dropped FracDiff entirely, went back to the raw, unfiltered levels**, and
ran the user's requested ATR-scaled reversion (fade-only, both sides) sweep:
`target_pts = atr_pct × prior-session ATR(14)`, `stop_pts = target_pts / rr`
for `rr ∈ {1, 1.5, 2, 3, 4}` and `atr_pct` from 10% to 60% of ATR — see
`volgen/atr.py`, `volgen/atr_reversion.py`,
`scripts/atr_reversion_sweep.py`. No slippage/commission modeled (per the
user, not present in this environment). Full grid in `out/atr_fade_sweep.csv`
/ `out/atr_fade_sweep_by_year.csv` / `out/lower_fade_sweep.csv`.

**Headline results:**

1. **Every single (atr_pct, rr) combo loses money when fading BOTH sides**
   (n=908 fades each, totals ranging from −160 to −1,300 pts). Fading is not
   a viable blanket strategy on these levels, full stop.

2. **But there's a robust upper/lower asymmetry**: lower-level fades (buying
   support) are consistently much less bad — and in some configs net
   positive — while upper-level fades (selling resistance) are robust,
   consistent losers (e.g. atr_pct=0.40/rr=4: lower +256 pts vs upper −456
   pts; atr_pct=0.20/rr=2: lower +86 vs upper −287). This is the same
   "resistance keeps breaking, support sees real bounces" asymmetry already
   seen in the earlier reaction/continuation and raw-edge analyses — gold has
   been trending up hard, so it's most parsimoniously a **regime property**,
   not something specific to the lower-level formula.

3. **Isolating lower-only fades and doing the "perturb y/y" robustness check
   the user asked for is where this falls apart**: every apparently-decent
   lower-fade config's total P&L is overwhelmingly carried by **2026 alone**.
   E.g. the best lower-fade combo (atr_pct=0.40, rr=1.0, ~21pt brackets):

   | year | n  | win% | avg pts | total pts |
   |---|---|---|---|---|
   | 2023 | 78  | 21.8% | +0.40 | +31.4 |
   | 2024 | 132 | 16.7% | −0.05 | −6.3 |
   | 2025 | 132 | 25.8% | +1.08 | +142.9 |
   | 2026 | 66  | 25.8% | **+5.71** | **+376.9** |

   2026 is 16% of the trades and ~70% of the total points; in several other
   top combos it's 80-90%+. **2023-2024 are flat-to-negative for every
   config we tried.**

4. **Drilling into *why* 2026 looks good is the real finding**: of the 66
   lower-fade trades in 2026, the **top 5 winners alone contribute +348.6 of
   the +376.9 total** (i.e. the other 61 trades roughly cancel out). Several
   of those "wins" are also clustered/duplicated — e.g. four nearly-identical
   entries within 5 minutes on 2026-01-16 (one stop, three ~+30pt targets —
   the same underlying spike counted 4x), two on 2026-04-12 at the exact same
   minute. And because `atr_pct=0.40` against 2026's blown-out ATR produces
   50-90pt-wide brackets, more than half the "trades" (36/66) never resolve
   within the 4-hour window and are just marked-to-market at an arbitrary
   cutoff — not real completed trades.

**Bottom line — answering "what's the common denominator of a real
reversion?": there isn't one that generalizes here.** The only thing that
looks like an "edge" is a handful (≈5) of enormous, partly-correlated tail
moves clustered in early-to-mid 2026 — i.e. **a regime/tail-event artifact of
one unusually volatile stretch**, not a structural property of these levels
that would survive out-of-sample or hold up in a calmer market. Scaling
TP/SL to ATR doesn't fix this — it just makes the brackets wide enough to
occasionally catch one of those tail moves, at the cost of being un-tradeable
(50-90pt stops) the rest of the time.

**Suggested next direction** (not yet run): rather than more bracket-config
sweeps, characterize the ~5 winning 2026 setups directly — what time of day,
what GVZ level, was there a specific catalyst/news regime, how far had price
already moved before the touch — to see if there's a *filterable*
precondition that would have flagged "this specific touch is different," or
whether they're simply unpredictable tail events that happened to land near a
level. If it's the latter, that's a strong signal to stop iterating on this
indicator's levels for a reversion strategy and look elsewhere.

---

# Initial test results — μ ± k·σ/√(dev) levels on GC, 2023-06 → 2026-05 (superseded sections below)

Status: **ran a significance/permutation control — the honest headline is
that the indicator's specific level placement is mostly indistinguishable
from a random reference point of similar size near the day's open. The "raw
edge" found in the bracket-trade test below most likely reflects the
2023-2026 GC uptrend regime (any reference point near the open tends to see
continuation-biased follow-through in a strong trend), not something specific
to this indicator's sigma/IB math. Read the "Significance test" section first
— it reframes everything that follows it.**

## Significance test — is this distinguishable from luck/regime?

`scripts/significance_test.py`: a permutation/randomization control. For each
session, keep the real `cash_open` and `created_at` (so timing & context stay
real), but replace `level − cash_open` with an offset **resampled from the
empirical distribution of real offsets, shuffled across sessions** — same
typical size/touch-likelihood, but the link between *that day's specific
sigma/IB inputs* and the resulting level is broken. Re-run the identical
touch + net-bias measurement on these "fake" levels 100 times to build a null
distribution, then check where the real indicator's result falls in it
(empirical p-value = fraction of random trials at least as extreme).

| metric (60m horizon) | real | random-offset null (mean ± std) | p-value |
|---|---|---|---|
| upper mean net bias | −0.96 | −0.62 ± 0.67 | 0.59 |
| upper median net bias | −0.59 | −0.56 ± 0.51 | 0.95 |
| upper % reaction wins | 46.6% | 47.4% ± 2.4% | 0.71 |
| lower mean net bias | +0.12 | −1.43 ± 1.07 | 0.20 |
| lower median net bias | +1.00 | +0.58 ± 0.57 | 0.39 |
| lower % reaction wins | 57.1% | 52.5% ± 2.3% | **0.05** |

**5 of 6 metrics land squarely inside the null distribution** (p from 0.20 to
0.95 — statistically indistinguishable from a randomly-sized-and-placed
reference point). The one borderline result (lower % reaction wins, p=0.05)
is exactly what you'd expect to see by chance when testing 6 metrics
(multiple-comparisons) — not strong evidence on its own.

**Conclusion: I cannot currently show that the indicator's specific
sigma/IB-derived level placement does anything a random offset of similar
size wouldn't.** The earlier "continuation wins on upper levels" pattern is
most parsimoniously explained as **a property of the regime** — GC trended
hard over this whole window, so *any* reference point near the day's open
would tend to see continuation-biased follow-through — rather than something
the indicator's specific math contributes.

This doesn't mean "the indicator is useless" — it means **we haven't yet
found evidence it beats a naive random/structural baseline** on this dataset.
Worth checking before concluding either way:
- Re-run the permutation test over a flatter/choppier sub-period (if one
  exists in this window) — a real level-placement effect should show up (or
  at least not vanish) outside of a strong trend; a regime artifact should
  weaken or flip.
- Compare against *structural* (non-random) baselines too — e.g. prior day's
  high/low, overnight session high/low, round numbers — since "any nearby
  reference point works in a trend" is itself a useful (if humbling) finding,
  but a structural baseline comparison tells you whether *this specific
  formula* adds anything over simpler, well-known reference levels.
- Increase `--n-perm` (currently 100, giving ~0.01 p-value resolution) for
  tighter confidence on the borderline lower-level result.

---

## Raw edge test — "is there ANY edge, or is something just a clear loser?"

> **Read the significance-test section above first.** The numbers below were
> the basis for the "fade upper = loser, continuation = winner" framing, but
> the permutation test suggests this is very likely a regime effect (GC
> trending hard) rather than something specific to these levels — i.e. a
> randomly-placed reference point of similar size would likely show a similar
> pattern over this same window. Keeping this section for the raw mechanics
> and because the *magnitude* findings (huge 2026 moves) still stand
> regardless of *which* reference point you measure from.


Per the user's ask: skip trend-conditioning for now, just test the dumbest
possible thing — at every first touch of a level, simulate a fixed
target/stop bracket trade in **both** directions (no filters at all):

- **fade** = bet price reverses off the level (the "obvious" reversal trade)
- **continuation** = bet price blows through the level (the breakout trade)

Run with `scripts/raw_edge_test.py --target N --stop N`. Tested 5 bracket
configs (5/5, 10/10, 20/20, 15/10, 10/15 — i.e. R:R from 0.67 to 1.5), n≈919
trades per direction each time. **The result is the same shape every time:**

| config (target/stop) | ALL continuation: total pts (win%) | ALL fade: total pts (win%) | upper continuation | upper fade |
|---|---|---|---|---|
| 5 / 5   | **+76.6**  (47.0%) | −276.6 (43.0%) | **+284.9** (52.4%) | −334.9 (40.2%) |
| 10 / 10 | **+350.0** (36.2%) | −450.0 (30.7%) | **+424.4** (38.4%) | −464.4 (29.1%) |
| 20 / 20 | **+948.8** (20.3%) | −988.8 (15.9%) | **+886.9** (19.9%) | −886.9 (14.5%) |
| 15 / 10 | **+607.1** (23.7%) | −482.7 (18.9%) | **+476.0** (23.5%) | −437.0 (18.9%) |
| 10 / 15 | **+432.7** (39.9%) | −657.1 (33.7%) | **+437.0** (42.0%) | −476.0 (33.1%) |

**Every single config, with zero exceptions:**
- **Continuation (breakout) is net positive overall**, and **fade is net
  negative overall**.
- The effect is **driven almost entirely by upper levels**: upper-level
  continuation is positive and upper-level fade is sharply, consistently
  negative (−335 to −887 pts depending on bracket). Lower levels are much
  closer to a wash and flip sign across configs (mildly +/− depending on R:R) —
  i.e. the "support bounces" intuition is *not* showing up as a robust raw
  edge, but "resistance keeps breaking" very much is.
- This is the opposite of the "obvious" trade (fading a level that looks like
  resistance) — and it's consistent with the trend-asymmetry already seen in
  the reaction/continuation breakdown: gold has been in a strong uptrend, so
  upper levels function as continuation/breakout markers, not walls.

**Bottom line: don't build a fade strategy off these levels — it's a robust
loser, especially on the upper side. The raw, untuned edge is in trading the
breakout through upper levels.** That's a strong, decisive starting point for
strategy design — a much better place to be than "everything's a coin flip."

Caveats before getting too excited: (1) this is *raw* — no slippage/commission,
single fixed bracket, first-touch only, no position sizing; (2) it's tested
over a single strong-uptrend regime (2023-06→2026-05) so it may be partly
"long bias wins in an uptrend" rather than something specific to these levels —
worth checking against a flat/down period or comparing to a naive "always buy
breakouts of any round-number level" baseline to isolate the indicator's value-add.

---

## Earlier pass: reaction-vs-continuation analysis (kept for context)

The headline numbers below were from before the raw-edge test above — they
showed the *aggregate* picture looked like a coin flip, which under-sold the
real, robust asymmetry the bracket-trade test surfaced. Keeping this section
because the year/side breakdown is still useful color (e.g. why 2026 felt so
violent), but **the raw edge test above is the more decisive read**.

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
