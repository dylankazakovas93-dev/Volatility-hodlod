"""GC (gold futures) fade strategy: level generator + FracDiff momentum gate
+ trade logic, consolidated into one reproducible script.

This is the RR=0.5 configuration from this session's exploration -- not a
new/different idea, just all three pieces (level gen, FracDiff indicator,
trade logic) put together in one place instead of scattered across ad-hoc
one-off scripts. Does not modify any frozen engine file in src/ -- only
imports and calls src/level_generation.py and src/strict_engine.py
functions unmodified.

STATUS: retrospectively fit on this exact ~3-year GC sample (2023-06 to
2026-05). Every parameter below (level-gen sigma_mult/offset_pct, the
FracDiff band=3.0, the 15min-range stop/target, RR=0.5) was chosen because
it looked best after searching over many alternatives on this SAME data --
none of it has been checked on data it hasn't already seen. Treat the
printed results as a description of the past, not a claim about the
future, until it's been walk-forward validated.

===============================================================================
THE THREE PIECES, IN ORDER
===============================================================================

1. LEVEL GENERATOR (unmodified frozen code: src/level_generation.py)
   Each session, using the prior day's VXN close and the session's own
   30-minute Initial Balance range, draws one upper and one lower
   statistically-derived "fade" level. First touch of either level is a
   trade candidate. GC_PARAMS: sigma_mult=2.0, offset_pct=0.08,
   ib_minutes=30 -- the least-bad cell of a 144-combo excursion grid search
   earlier this session (see docs/gc_mae_mfe_study/FINAL_FORMULA_RECOMMENDATION.md
   for why "least-bad", not "good": no combo in that grid produced
   favorable excursion on net).

2. FRACDIFF GATE (Python port of the user's Pine v6 indicator)
   At the exact moment a level is touched, look at the last FULLY-CLOSED
   5-minute candle (never the one still forming) and compute a
   fractional-differencing momentum z-score over the trailing 100 such
   candles (d=0.45, matches the Pine script's binomial weight recurrence
   exactly, verified against it earlier this session). Only take the trade
   if that z-score is >= 3 standard deviations extreme, in the SAME
   direction as the move that just caused the touch ("reversion sense" --
   the mirror image of the Pine script's own "trend sense" condition; see
   module-level note in `reversion_gate_pass()` below for why the sign is
   flipped from what the Pine script specifies).

3. TRADE LOGIC (stop/target sizing + race simulation)
   If the gate passes: stop = 1x the previous FULLY-CLOSED 15-minute
   candle's high-low range; target = 0.5x that same range (RR=0.5, half
   the size of the stop). Walk forward minute by minute from the touch;
   whichever level is hit first decides the trade. Same-bar stop+target
   ambiguity resolves stop-first (conservative, matches
   src/strict_engine.py's own convention). If neither is hit by the
   15:00 ET prop-firm forced-flat time, mark the trade to market at that
   bar's close -- counted as a real win/loss/scratch, never discarded.
"""
from __future__ import annotations

import os
import sys
from dataclasses import replace

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_loader import load_1m_ohlcv, load_gvz_daily          # frozen, unmodified
from src.level_generation import GC_PARAMS, generate_levels         # frozen, unmodified
from src.strict_engine import physical_touches, session_cutoff      # frozen, unmodified

ET = "America/New_York"

# =============================================================================
# CONFIG -- every number that defines this exact strategy, in one place
# =============================================================================

BARS_PATH = "data/gc_1m/gc_continuous_2023_2026_1m.csv"
VOL_PATH = "data/vxn_daily_2018_2026.csv"     # VXN -- best-performing vol feed for GC found earlier this session

# 1. Level generator (GC_PARAMS overrides -- unchanged from the excursion grid winner)
LEVEL_GEN_SIGMA_MULT = 2.0
LEVEL_GEN_OFFSET_PCT = 0.08
LEVEL_GEN_IB_MINUTES = 30

# 2. FracDiff gate (verbatim from the Pine script's own inputs)
FD_D = 0.45            # integration order
FD_N = 100             # max lag truncation
FD_ZLEN = 100           # rolling window for the z-score's mean/stdev
FD_FAST_THRESH = 1e-3   # weight-cutoff for the "fast calculation" mode
FD_BAND = 3.0           # how extreme the z-score must be to confirm (session default was 1.0; this is the cranked-up version)

# 3. Trade logic
STOP_TF = "15min"       # timeframe for the prior-completed-candle range used as the stop
STOP_MULT = 1.0          # stop = STOP_MULT x that range
TARGET_RR = 0.5          # target = TARGET_RR x that range (RR=0.5 = half-sized TP)
CUTOFF_HHMM = "15:00"    # prop-firm forced-flat time, ET (same as the frozen engine's own session_cutoff)


# =============================================================================
# PIECE 2: FracDiff Gate -- Python port of the Pine v6 indicator
# =============================================================================

def ffd_weights(d: float, N: int, thresh: float) -> list[float]:
    """Binomial fractional-difference weights. Line-for-line match of the
    Pine script's recurrence: wk := wk * (k - 1 - d) / k, stopping once a
    weight's magnitude drops below `thresh` (the "fast calculation" cutoff).
    Verified earlier this session: effN=48 for d=0.45, N=100, thresh=1e-3."""
    w = [1.0]
    wk = 1.0
    for k in range(1, N + 1):
        wk = wk * (k - 1 - d) / k
        if abs(wk) < thresh:
            break
        w.append(wk)
    return w


def resample_ohlc(bars_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Standard non-overlapping OHLC downsample. label='left', closed='left'
    means each output row aggregates only the 1-minute bars strictly inside
    its own window -- no future leakage into an earlier-labeled bar."""
    return bars_1m.resample(freq, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()


def compute_fracdiff_z(bars_1m: pd.DataFrame) -> pd.Series:
    """FracDiff z-score, computed entirely on 5-minute bars (per the Pine
    script's own instruction: "apply this on a 5-MINUTE chart"). Returns a
    Series indexed by each 5m bar's OWN start time -> that bar's z-score.

    Causality: `fd` is built via N vectorized `.shift(k)` calls for k >= 0
    only (current bar + strictly PAST bars, never negative/future shifts),
    so every fd value only depends on closes at-or-before its own bar's
    close. The z-score's rolling mean/stdev use pandas `.rolling()`, which
    is trailing-only by construction (never centered)."""
    bars_5m = resample_ohlc(bars_1m, "5min")
    close = bars_5m["close"]

    w = ffd_weights(FD_D, FD_N, FD_FAST_THRESH)
    fd = pd.Series(0.0, index=close.index)
    for k, wk in enumerate(w):
        fd = fd.add(wk * close.shift(k), fill_value=0.0)
    fd.iloc[: len(w) - 1] = np.nan  # not enough history yet for a full weight window

    fd_mean = fd.rolling(FD_ZLEN).mean()
    fd_std = fd.rolling(FD_ZLEN).std(ddof=0)   # population stdev, matches Pine's ta.stdev default
    return (fd - fd_mean) / fd_std


def prior_bar_start(ts: pd.Timestamp, freq: str) -> pd.Timestamp:
    """The start of the most recently FULLY-CLOSED bar at this frequency,
    strictly before `ts` -- never the bar `ts` itself sits inside, even if
    `ts` lands exactly on a boundary. Same convention as the frozen
    engine's own `prev_completed_range()`, just generalized to any freq."""
    return ts.floor(freq) - pd.Timedelta(freq)


def reversion_gate_pass(sign: float, z: float) -> bool:
    """True if the FracDiff gate confirms this trade, REVERSION sense.

    NOTE on the sign flip: the Pine script's own "TREND sense" comment says
    long-fade needs z >= +band and short-fade needs z <= -band. Checked
    against this data earlier this session: at an actual lower-level touch
    (long fade), the prior 5m momentum is almost always deeply NEGATIVE
    (mean z ~ -2.4, since price fell hard to reach the level) -- the
    opposite of what "trend sense" requires -- so that version passes only
    0.8% of touches. This reversion-sense flip (confirm in the SAME
    direction the market just moved) is what the data naturally supports;
    it passes ~24% of touches and is what every result in this script uses.
    Still worth checking against your own TradingView chart before trusting it.
    """
    if pd.isna(z):
        return False
    if sign > 0:   # long fade (lower-level touch)
        return z <= -FD_BAND
    else:          # short fade (upper-level touch)
        return z >= FD_BAND


# =============================================================================
# PIECE 3: trade logic -- stop/target sizing + race simulation
# =============================================================================

def race(entry: float, sign: float, cap: float, rr: float,
         path_high: np.ndarray, path_low: np.ndarray, cutoff_close: float):
    """Bar-by-bar race to stop or target. Same-bar ambiguity resolves
    stop-first (conservative). If neither level is hit before the session
    cutoff, marks to market at the cutoff bar's close -- always returns a
    real outcome, never silently drops the trade."""
    target = entry + sign * cap * rr
    stop = entry - sign * cap
    for h, l in zip(path_high, path_low):
        if sign > 0:
            hit_stop, hit_target = l <= stop, h >= target
        else:
            hit_stop, hit_target = h >= stop, l <= target
        if hit_stop:
            return "SL", -cap
        if hit_target:
            return "TP", cap * rr
    return "mtm_cutoff", sign * (cutoff_close - entry)


# =============================================================================
# PIECE 1 + orchestration: build touches, apply the gate, run the trade logic
# =============================================================================

def build_trades(bars: pd.DataFrame, vol: pd.Series) -> pd.DataFrame:
    params = replace(
        GC_PARAMS,
        sigma_mult=LEVEL_GEN_SIGMA_MULT, offset_pct=LEVEL_GEN_OFFSET_PCT,
        ib_minutes=LEVEL_GEN_IB_MINUTES, fixed_offset=None,
    )
    levels = generate_levels(bars, vol, params=params, rth_start="09:30", rth_end="16:00")
    lvls = list(levels.itertuples(index=False))
    events = physical_touches(bars, lvls)
    touched = [e for e in events if e["touched_at"] is not None]

    z_series = compute_fracdiff_z(bars)
    stop_range = resample_ohlc(bars, STOP_TF)
    stop_range = stop_range["high"] - stop_range["low"]

    rows = []
    for e in touched:
        ts = e["touched_at"]
        cutoff = session_cutoff(ts)
        if cutoff is None:
            continue
        path = bars.loc[ts:cutoff]
        if path.empty:
            continue

        entry = e["level"]
        sign = 1.0 if e["side"] == "lower" else -1.0
        z = z_series.get(prior_bar_start(ts, "5min"), np.nan)
        cap = stop_range.get(prior_bar_start(ts, STOP_TF), np.nan)

        if pd.isna(cap) or cap <= 0:
            continue
        if not reversion_gate_pass(sign, z):
            continue

        outcome, pnl = race(
            entry, sign, cap * STOP_MULT, TARGET_RR,
            path["high"].to_numpy(), path["low"].to_numpy(), float(path["close"].iloc[-1]),
        )
        rows.append({
            "touched_at": ts, "year": ts.year, "side": e["side"],
            "z_gate": z, "cap": cap, "outcome": outcome, "pnl": pnl,
        })

    return pd.DataFrame(rows)


def summarize_by_year(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for yr, g in trades.groupby("year"):
        gp, gl = g.loc[g.pnl > 0, "pnl"].sum(), -g.loc[g.pnl < 0, "pnl"].sum()
        pf = gp / gl if gl > 0 else None
        rows.append({
            "year": yr, "n": len(g), "net_pts": round(g.pnl.sum(), 2),
            "PF": round(pf, 4) if pf else None, "win_%": round((g.pnl > 0).mean() * 100, 1),
            "avg_pts": round(g.pnl.mean(), 3), "median_pts": round(g.pnl.median(), 3),
            "TP": int((g.outcome == "TP").sum()), "SL": int((g.outcome == "SL").sum()),
            "mtm_cutoff": int((g.outcome == "mtm_cutoff").sum()),
        })
    gp, gl = trades.loc[trades.pnl > 0, "pnl"].sum(), -trades.loc[trades.pnl < 0, "pnl"].sum()
    pf = gp / gl if gl > 0 else None
    rows.append({
        "year": "ALL", "n": len(trades), "net_pts": round(trades.pnl.sum(), 2),
        "PF": round(pf, 4) if pf else None, "win_%": round((trades.pnl > 0).mean() * 100, 1),
        "avg_pts": round(trades.pnl.mean(), 3), "median_pts": round(trades.pnl.median(), 3),
        "TP": int((trades.outcome == "TP").sum()), "SL": int((trades.outcome == "SL").sum()),
        "mtm_cutoff": int((trades.outcome == "mtm_cutoff").sum()),
    })
    return pd.DataFrame(rows)


def main():
    bars = load_1m_ohlcv(BARS_PATH)
    vol = load_gvz_daily(VOL_PATH)

    trades = build_trades(bars, vol)
    os.makedirs("outputs/gc_fracdiff_study", exist_ok=True)
    trades.to_csv("outputs/gc_fracdiff_study/final_config_rr0.5_trades.csv", index=False)

    summary = summarize_by_year(trades)
    summary.to_csv("outputs/gc_fracdiff_study/final_config_rr0.5_summary.csv", index=False)

    pd.set_option("display.width", 200)
    print(f"config: sigma_mult={LEVEL_GEN_SIGMA_MULT} offset_pct={LEVEL_GEN_OFFSET_PCT} "
          f"ib_minutes={LEVEL_GEN_IB_MINUTES} | FD band={FD_BAND} d={FD_D} | "
          f"stop_tf={STOP_TF} RR={TARGET_RR} cutoff={CUTOFF_HHMM} ET")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
