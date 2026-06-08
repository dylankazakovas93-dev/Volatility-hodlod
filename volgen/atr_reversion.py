"""Reversion-only (fade) test on the RAW, unfiltered mu+/-k*sigma levels, with
TP/SL scaled to the prevailing daily ATR instead of fixed point values.

Per the user's latest directive: drop the FracDiff filter (joint signal was too
rare to say anything useful either way — confirmed independently by both
agents' tests), go back to the raw levels, and find the "common denominator" of
which touches actually produce clean reversions by sweeping:
  - TP = `atr_pct` x prior-session ATR(14)   (e.g. 10/15/20/25/40% of ATR)
  - SL = TP / `rr`                            (rr = reward:risk multiple, 1-4)
No slippage/commission (per the user: "they aren't existent in this
environment"). Results are broken out year-by-year so a single hot year can't
silently carry the average ("perturb it y/y").
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from volgen.atr import atr_as_of
from volgen.reactions import _first_touch

_FADE_SIGN = {"lower": +1.0, "upper": -1.0}  # fade: buy lower-level touches, sell upper-level touches


@dataclass
class AtrFadeOutcome:
    session_date: object
    side: str
    touched_at: pd.Timestamp
    entry: float
    atr: float
    atr_pct: float
    rr: float
    target_pts: float
    stop_pts: float
    result: str          # "target" / "stop" / "timeout"
    bars_held: int
    pts: float
    max_dd: float        # worst point-deficit reached before exit (>= 0)


def simulate_fade_with_dd(
    ohlcv_1m: pd.DataFrame,
    side: str,
    touched_at: pd.Timestamp,
    level: float,
    target_pts: float,
    stop_pts: float,
    max_bars: int = 240,
):
    """Fade-direction bracket simulation (same mechanics/conventions as
    `volgen.trades.simulate_bracket_trade`: enter at touch-bar close, intrabar
    target/stop, ties favor the stop) that ALSO tracks the running maximum
    adverse excursion (drawdown) up to the exit bar — answers "how much DD do
    you have to tolerate to let this trade play out?"."""
    sign = _FADE_SIGN[side]
    future = ohlcv_1m.loc[touched_at:]
    if future.empty:
        return None
    entry = float(future["close"].iloc[0])
    target = entry + sign * target_pts
    stop = entry - sign * stop_pts

    path = future.iloc[1 : max_bars + 1]
    max_dd = 0.0
    for i, (_, bar) in enumerate(path.iterrows(), start=1):
        hi, lo = bar["high"], bar["low"]
        # adverse excursion this bar = how far price moved against the fade
        adverse = sign * (entry - lo) if sign > 0 else sign * (hi - entry)
        max_dd = max(max_dd, float(adverse))

        hit_target = (hi >= target) if sign > 0 else (lo <= target)
        hit_stop = (lo <= stop) if sign > 0 else (hi >= stop)
        if hit_stop:
            return _outcome("stop", i, -stop_pts, max_dd, locals())
        if hit_target:
            return _outcome("target", i, target_pts, max_dd, locals())

    last_close = float(path["close"].iloc[-1]) if len(path) else entry
    pts = sign * (last_close - entry)
    return _outcome("timeout", len(path), pts, max_dd, locals())


def _outcome(result, bars_held, pts, max_dd, ctx):
    return AtrFadeOutcome(
        session_date=None, side=ctx["side"], touched_at=ctx["touched_at"], entry=ctx["entry"],
        atr=float("nan"), atr_pct=float("nan"), rr=float("nan"),
        target_pts=ctx["target_pts"], stop_pts=ctx["stop_pts"],
        result=result, bars_held=bars_held, pts=pts, max_dd=max_dd,
    )


def run_atr_fade_test(
    ohlcv_1m: pd.DataFrame,
    levels: pd.DataFrame,
    atr_lookup: pd.Series,
    atr_pct: float,
    rr: float,
    max_bars: int = 240,
    search_window: pd.Timedelta = pd.Timedelta(days=5),
    min_pts: float = 1.0,
) -> pd.DataFrame:
    """For every level (upper AND lower — both faded, per the reversion-only
    mandate), find the first touch, size TP = atr_pct*ATR and SL = TP/rr off
    the prior session's ATR(14), and simulate the fade. `min_pts` floors the
    bracket size so degenerate near-zero ATR days don't produce 0-point
    brackets (rare, but possible early in the ATR warmup / quiet regimes)."""
    records = []
    for _, row in levels.iterrows():
        atr = atr_as_of(atr_lookup, row["session_date"])
        if atr is None or atr <= 0:
            continue
        target_pts = max(atr_pct * atr, min_pts)
        stop_pts = max(target_pts / rr, min_pts)

        for side, level_col in (("upper", "upper_level"), ("lower", "lower_level")):
            level = float(row[level_col])
            window = ohlcv_1m.loc[row["created_at"] : row["created_at"] + search_window]
            touched_at = _first_touch(window, level)
            if touched_at is None:
                continue
            out = simulate_fade_with_dd(ohlcv_1m, side, touched_at, level, target_pts, stop_pts, max_bars)
            if out is None:
                continue
            records.append(
                {
                    "session_date": row["session_date"],
                    "side": side,
                    "touched_at": out.touched_at,
                    "entry": out.entry,
                    "atr": atr,
                    "atr_pct": atr_pct,
                    "rr": rr,
                    "target_pts": target_pts,
                    "stop_pts": stop_pts,
                    "result": out.result,
                    "bars_held": out.bars_held,
                    "pts": out.pts,
                    "max_dd": out.max_dd,
                }
            )
    return pd.DataFrame(records)


def summarize_atr_fade(trades: pd.DataFrame) -> pd.DataFrame:
    """Win rate, expectancy, drawdown stats per side and overall."""
    rows = []
    groups = list(trades.groupby("side")) + [("ALL", trades)]
    for side, sub in groups:
        if sub.empty:
            continue
        rows.append(
            {
                "side": side,
                "n": len(sub),
                "win_rate": round(float((sub["result"] == "target").mean()), 3),
                "loss_rate": round(float((sub["result"] == "stop").mean()), 3),
                "avg_pts": round(float(sub["pts"].mean()), 3),
                "median_pts": round(float(sub["pts"].median()), 3),
                "total_pts": round(float(sub["pts"].sum()), 1),
                "avg_dd": round(float(sub["max_dd"].mean()), 3),
                "p90_dd": round(float(sub["max_dd"].quantile(0.9)), 3),
                "avg_target_pts": round(float(sub["target_pts"].mean()), 2),
                "avg_stop_pts": round(float(sub["stop_pts"].mean()), 2),
            }
        )
    return pd.DataFrame(rows)


def summarize_by_year(trades: pd.DataFrame) -> pd.DataFrame:
    """Year-by-year breakdown — the user's "perturb it y/y" robustness check:
    does the average get carried by a single hot year, or hold up broadly?"""
    t = trades.copy()
    t["year"] = pd.to_datetime(t["touched_at"]).dt.year
    rows = []
    for (year, side), sub in t.groupby(["year", "side"]):
        rows.append(
            {
                "year": year,
                "side": side,
                "n": len(sub),
                "win_rate": round(float((sub["result"] == "target").mean()), 3),
                "avg_pts": round(float(sub["pts"].mean()), 3),
                "total_pts": round(float(sub["pts"].sum()), 1),
                "avg_dd": round(float(sub["max_dd"].mean()), 3),
            }
        )
    for year, sub in t.groupby("year"):
        rows.append(
            {
                "year": year,
                "side": "ALL",
                "n": len(sub),
                "win_rate": round(float((sub["result"] == "target").mean()), 3),
                "avg_pts": round(float(sub["pts"].mean()), 3),
                "total_pts": round(float(sub["pts"].sum()), 1),
                "avg_dd": round(float(sub["max_dd"].mean()), 3),
            }
        )
    return pd.DataFrame(rows).sort_values(["year", "side"])
