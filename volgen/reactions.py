"""Touch detection + reaction measurement for levels produced by volgen.levels.

The question we're testing: when price reaches one of these statistically-
derived levels, does it tend to *react* (reverse), or just blow through?
This module finds the first touch of each level after it goes live, then
measures what price did over the following bars.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def _first_touch(bars: pd.DataFrame, level: float) -> pd.Timestamp | None:
    """Mirrors the Pine touch test: level falls inside the bar's range, or
    close crosses it intrabar-to-intrabar."""
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev_close = close.shift(1)
    touched = (
        ((high >= level) & (low <= level))
        | ((close >= level) & (prev_close < level))
        | ((close <= level) & (prev_close > level))
    )
    hits = bars.index[touched]
    return hits[0] if len(hits) else None


@dataclass
class ReactionResult:
    session_date: object
    side: str  # "upper" or "lower"
    level: float
    created_at: pd.Timestamp
    touched_at: pd.Timestamp | None
    bars_to_touch: int | None
    # Reaction = move back toward/through cash_open after the touch.
    reaction_pts: dict[int, float]  # horizon (minutes) -> signed move away from level, toward reversal
    continuation_pts: dict[int, float]  # horizon (minutes) -> signed move past the level, away from reversal
    reversed_within: dict[int, bool]  # horizon -> did price move >= reaction_threshold back through the level


def measure_level(
    ohlcv_1m: pd.DataFrame,
    side: str,
    level: float,
    created_at: pd.Timestamp,
    session_date,
    horizons_minutes: tuple[int, ...] = (5, 15, 30, 60, 120),
    reaction_threshold: float = 0.0,
    search_window: pd.Timedelta = pd.Timedelta(days=5),
) -> ReactionResult:
    """Find the first touch of `level` at/after `created_at` and measure the
    subsequent move.

    `side="upper"` means a reaction = price falling back below the level
    (reversal down); `side="lower"` means a reaction = price rising back
    above the level (reversal up). `continuation` is the opposite: price
    pushing further through the level.
    """
    window = ohlcv_1m.loc[created_at : created_at + search_window]
    touched_at = _first_touch(window, level)

    reaction: dict[int, float] = {}
    continuation: dict[int, float] = {}
    reversed_within: dict[int, bool] = {}
    bars_to_touch = None

    if touched_at is not None:
        bars_to_touch = int(window.index.get_indexer([touched_at])[0])
        future = ohlcv_1m.loc[touched_at:]
        sign = -1.0 if side == "upper" else 1.0  # direction that counts as "reaction"

        for h in horizons_minutes:
            cutoff = touched_at + pd.Timedelta(minutes=h)
            seg = future.loc[touched_at:cutoff]
            if seg.empty:
                continue
            # Reaction extreme: best move in the reversal direction relative to the level.
            reaction_extreme = sign * (seg["low"].min() - level) if side == "upper" else sign * (seg["high"].max() - level)
            # Continuation extreme: best move in the breakout direction relative to the level.
            continuation_extreme = (-sign) * (seg["high"].max() - level) if side == "upper" else (-sign) * (seg["low"].min() - level)

            reaction[h] = float(reaction_extreme)
            continuation[h] = float(continuation_extreme)
            reversed_within[h] = bool(reaction_extreme >= reaction_threshold)

    return ReactionResult(
        session_date=session_date,
        side=side,
        level=level,
        created_at=created_at,
        touched_at=touched_at,
        bars_to_touch=bars_to_touch,
        reaction_pts=reaction,
        continuation_pts=continuation,
        reversed_within=reversed_within,
    )


def evaluate_levels(
    ohlcv_1m: pd.DataFrame,
    levels: pd.DataFrame,
    horizons_minutes: tuple[int, ...] = (5, 15, 30, 60, 120),
    reaction_threshold: float = 0.0,
) -> pd.DataFrame:
    """Run measure_level over every upper/lower level and return a tidy
    DataFrame, one row per (session, side)."""
    records = []
    for _, row in levels.iterrows():
        for side, level_col in (("upper", "upper_level"), ("lower", "lower_level")):
            res = measure_level(
                ohlcv_1m,
                side=side,
                level=float(row[level_col]),
                created_at=row["created_at"],
                session_date=row["session_date"],
                horizons_minutes=horizons_minutes,
                reaction_threshold=reaction_threshold,
            )
            rec = {
                "session_date": res.session_date,
                "side": res.side,
                "level": res.level,
                "created_at": res.created_at,
                "touched_at": res.touched_at,
                "bars_to_touch": res.bars_to_touch,
            }
            for h in horizons_minutes:
                rec[f"reaction_{h}m"] = res.reaction_pts.get(h, np.nan)
                rec[f"continuation_{h}m"] = res.continuation_pts.get(h, np.nan)
                rec[f"reversed_{h}m"] = res.reversed_within.get(h, np.nan)
            records.append(rec)

    return pd.DataFrame(records)


def summarize(results: pd.DataFrame, horizons_minutes: tuple[int, ...] = (5, 15, 30, 60, 120)) -> pd.DataFrame:
    """Aggregate hit-rate / reaction-size stats across all levels."""
    touched = results.dropna(subset=["touched_at"])
    n_total, n_touched = len(results), len(touched)

    rows = [{"metric": "levels generated", "value": n_total}]
    rows.append({"metric": "levels touched", "value": n_touched})
    rows.append({"metric": "touch rate", "value": n_touched / n_total if n_total else float("nan")})

    for h in horizons_minutes:
        rcol, ccol, vcol = f"reaction_{h}m", f"continuation_{h}m", f"reversed_{h}m"
        sub = touched.dropna(subset=[rcol])
        if sub.empty:
            continue
        rows.append({"metric": f"[{h}m] reversal rate (>= threshold)", "value": sub[vcol].mean()})
        rows.append({"metric": f"[{h}m] median reaction (pts, +=toward reversal)", "value": sub[rcol].median()})
        rows.append({"metric": f"[{h}m] median continuation (pts, +=through level)", "value": sub[ccol].median()})
        rows.append({"metric": f"[{h}m] mean reaction (pts)", "value": sub[rcol].mean()})
        rows.append({"metric": f"[{h}m] mean continuation (pts)", "value": sub[ccol].mean()})

    return pd.DataFrame(rows)
