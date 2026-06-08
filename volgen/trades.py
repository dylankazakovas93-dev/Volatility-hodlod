"""Simple fixed-bracket trade simulation at level touches — answers the blunt
question "is there ANY raw edge here, or is one direction just a loser?"

No trend conditioning, no filters: enter at the touch, fixed target/stop in
points, walk forward bar-by-bar, see which is hit first. This is deliberately
dumb so the numbers reflect the raw behavior of the level, not a curve-fit.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class TradeOutcome:
    session_date: object
    side: str          # "upper" / "lower"
    direction: str     # "fade" (bet on reversal) / "continuation" (bet on breakout)
    touched_at: pd.Timestamp
    entry: float
    target: float
    stop: float
    result: str        # "target" / "stop" / "timeout"
    bars_held: int
    pts: float         # realized points (signed: + = winner, - = loser, target/stop magnitude if hit, else mark-to-market at timeout)


def _trade_direction_sign(side: str, direction: str) -> float:
    """+1 = expect price to rise from entry, -1 = expect price to fall."""
    if side == "upper":
        return -1.0 if direction == "fade" else +1.0
    else:  # lower
        return +1.0 if direction == "fade" else -1.0


def simulate_bracket_trade(
    ohlcv_1m: pd.DataFrame,
    side: str,
    direction: str,
    touched_at: pd.Timestamp,
    level: float,
    target_pts: float,
    stop_pts: float,
    max_bars: int = 240,
) -> TradeOutcome | None:
    """Enter at the close of the touch bar; walk forward until target, stop,
    or max_bars is reached (whichever comes first, checked intrabar via
    high/low — ties (both hit in the same bar) are resolved conservatively
    in favor of the stop)."""
    sign = _trade_direction_sign(side, direction)
    future = ohlcv_1m.loc[touched_at:]
    if future.empty:
        return None
    entry = float(future["close"].iloc[0])
    target = entry + sign * target_pts
    stop = entry - sign * stop_pts

    path = future.iloc[1 : max_bars + 1]
    for i, (_, bar) in enumerate(path.iterrows(), start=1):
        hi, lo = bar["high"], bar["low"]
        hit_target = (hi >= target) if sign > 0 else (lo <= target)
        hit_stop = (lo <= stop) if sign > 0 else (hi >= stop)
        if hit_target and hit_stop:
            return TradeOutcome(None, side, direction, touched_at, entry, target, stop, "stop", i, -stop_pts)
        if hit_stop:
            return TradeOutcome(None, side, direction, touched_at, entry, target, stop, "stop", i, -stop_pts)
        if hit_target:
            return TradeOutcome(None, side, direction, touched_at, entry, target, stop, "target", i, target_pts)

    last_close = float(path["close"].iloc[-1]) if len(path) else entry
    pts = sign * (last_close - entry)
    return TradeOutcome(None, side, direction, touched_at, entry, target, stop, "timeout", len(path), pts)


def run_raw_edge_test(
    ohlcv_1m: pd.DataFrame,
    levels: pd.DataFrame,
    target_pts: float,
    stop_pts: float,
    max_bars: int = 240,
    search_window: pd.Timedelta = pd.Timedelta(days=5),
) -> pd.DataFrame:
    """For every level, find its first touch, then simulate BOTH a fade trade
    and a continuation trade from that touch. Returns one row per
    (level, direction)."""
    from volgen.reactions import _first_touch  # local import to avoid cycles

    records = []
    for _, row in levels.iterrows():
        for side, level_col in (("upper", "upper_level"), ("lower", "lower_level")):
            level = float(row[level_col])
            window = ohlcv_1m.loc[row["created_at"] : row["created_at"] + search_window]
            touched_at = _first_touch(window, level)
            if touched_at is None:
                continue
            for direction in ("fade", "continuation"):
                out = simulate_bracket_trade(
                    ohlcv_1m, side, direction, touched_at, level, target_pts, stop_pts, max_bars
                )
                if out is None:
                    continue
                records.append(
                    {
                        "session_date": row["session_date"],
                        "side": side,
                        "direction": direction,
                        "touched_at": touched_at,
                        "result": out.result,
                        "bars_held": out.bars_held,
                        "pts": out.pts,
                    }
                )

    return pd.DataFrame(records)


def summarize_raw_edge(trades: pd.DataFrame) -> pd.DataFrame:
    """Win rate + raw point expectancy per (side, direction) and overall."""
    rows = []
    for (side, direction), sub in trades.groupby(["side", "direction"]):
        n = len(sub)
        win_rate = (sub["result"] == "target").mean()
        loss_rate = (sub["result"] == "stop").mean()
        timeout_rate = (sub["result"] == "timeout").mean()
        rows.append(
            {
                "side": side,
                "direction": direction,
                "n": n,
                "win_rate": round(win_rate, 3),
                "loss_rate": round(loss_rate, 3),
                "timeout_rate": round(timeout_rate, 3),
                "avg_pts_per_trade": round(sub["pts"].mean(), 3),
                "total_pts": round(sub["pts"].sum(), 1),
            }
        )

    overall = trades.groupby("direction").agg(
        n=("pts", "size"),
        win_rate=("result", lambda s: (s == "target").mean()),
        avg_pts_per_trade=("pts", "mean"),
        total_pts=("pts", "sum"),
    ).round(3)
    for direction, r in overall.iterrows():
        rows.append(
            {
                "side": "ALL",
                "direction": direction,
                "n": int(r["n"]),
                "win_rate": round(r["win_rate"], 3),
                "loss_rate": float("nan"),
                "timeout_rate": float("nan"),
                "avg_pts_per_trade": round(r["avg_pts_per_trade"], 3),
                "total_pts": round(r["total_pts"], 1),
            }
        )

    return pd.DataFrame(rows)
