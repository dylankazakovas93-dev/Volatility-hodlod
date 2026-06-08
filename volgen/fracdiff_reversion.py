"""Combine μ±k·σ levels with the FracDiff Gate (5m) z-score confirmation to
test REVERSION (fade) trades only — per the user's explicit directive to drop
the continuation hypothesis entirely.

Trend-sense mapping from the indicator (`indicator/fracdiff_gate.pine`):
  - lower-level fade (going LONG off support) confirmed when z >= +band
  - upper-level fade (going SHORT off resistance) confirmed when z <= -band

Three entry-confirmation methods, all checked using only *closed* 5m bars as of
the touch (no lookahead — the 5m bar containing the touch may still be forming):
  - "instant":         confirmation active on the most recently closed 5m bar
  - "lookback":        confirmation was active at any closed 5m bar within the
                       last `lookback_minutes` minutes (doesn't have to be "on tap")
  - "fired_returned":  confirmation fired at some point in the lookback window
                       AND has since returned to |z| < band by the most recent
                       closed bar (the "extension resolved, now revert" filter)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from volgen.reactions import _first_touch
from volgen.trades import simulate_bracket_trade


@dataclass(frozen=True)
class EntryConfig:
    method: str = "instant"          # "instant" | "lookback" | "fired_returned"
    lookback_minutes: int = 15


_SIDE_COL = {"lower": "long_ok", "upper": "short_ok"}
_SIDE_SIGN = {"lower": +1.0, "upper": -1.0}  # fade direction: lower=long, upper=short


def _last_closed_5m_bar_start(gate_5m: pd.DataFrame, touched_at: pd.Timestamp) -> pd.Timestamp | None:
    """The 5m bar starting at `bar_start` covers [bar_start, bar_start+5m) and is
    only fully known once `bar_start + 5m` has elapsed — so the most recent
    *closed* bar as of `touched_at` always starts at or before
    `touched_at.floor('5min') - 5min`."""
    bar_start = touched_at.floor("5min") - pd.Timedelta(minutes=5)
    if bar_start < gate_5m.index[0]:
        return None
    return bar_start


def _confirmation(gate_5m: pd.DataFrame, side: str, touched_at: pd.Timestamp, cfg: EntryConfig):
    """Returns (confirmed: bool, z_at_entry: float | nan, fired_at: Timestamp | None)
    using only closed 5m bars strictly before the touch."""
    col = _SIDE_COL[side]
    bar_start = _last_closed_5m_bar_start(gate_5m, touched_at)
    if bar_start is None:
        return False, float("nan"), None

    last_row = gate_5m.asof(bar_start)
    if last_row is None or pd.isna(last_row.get(col)):
        return False, float("nan"), None
    z_now = float(last_row["z"]) if not pd.isna(last_row["z"]) else float("nan")

    if cfg.method == "instant":
        return bool(last_row[col]), z_now, (bar_start if last_row[col] else None)

    window_start = touched_at - pd.Timedelta(minutes=cfg.lookback_minutes)
    window = gate_5m.loc[window_start:bar_start].dropna(subset=[col])
    if window.empty:
        return False, z_now, None
    fired_mask = window[col].astype(bool)

    if cfg.method == "lookback":
        confirmed = bool(fired_mask.any())
        fired_at = window.index[fired_mask][0] if confirmed else None
        return confirmed, z_now, fired_at

    if cfg.method == "fired_returned":
        fired = bool(fired_mask.any())
        returned_now = not bool(last_row[col])
        confirmed = fired and returned_now
        fired_at = window.index[fired_mask][0] if fired else None
        return confirmed, z_now, fired_at

    raise ValueError(f"unknown entry method: {cfg.method!r}")


def find_confirmed_touches(
    ohlcv_1m: pd.DataFrame,
    levels: pd.DataFrame,
    gate_5m: pd.DataFrame,
    cfg: EntryConfig,
    search_window: pd.Timedelta = pd.Timedelta(days=5),
) -> pd.DataFrame:
    """For every level, find its first touch, then check whether the FracDiff
    gate confirms a fade in that level's direction (per `cfg`). Returns one row
    per level with confirmation status, regardless of whether it was confirmed
    (so callers can compute confirmation rates), with `confirmed` flagging the
    tradeable subset."""
    records = []
    for _, row in levels.iterrows():
        for side, level_col in (("upper", "upper_level"), ("lower", "lower_level")):
            level = float(row[level_col])
            window = ohlcv_1m.loc[row["created_at"] : row["created_at"] + search_window]
            touched_at = _first_touch(window, level)
            if touched_at is None:
                continue
            confirmed, z_at_entry, fired_at = _confirmation(gate_5m, side, touched_at, cfg)
            records.append(
                {
                    "session_date": row["session_date"],
                    "side": side,
                    "level": level,
                    "created_at": row["created_at"],
                    "touched_at": touched_at,
                    "confirmed": confirmed,
                    "z_at_entry": z_at_entry,
                    "fired_at": fired_at,
                    "entry_method": cfg.method,
                }
            )
    return pd.DataFrame(records)


def measure_fade_reactions(
    ohlcv_1m: pd.DataFrame,
    confirmed_touches: pd.DataFrame,
    horizons_minutes: tuple[int, ...] = (30, 60),
) -> pd.DataFrame:
    """For each CONFIRMED touch, walk the path forward bar-by-bar and record,
    per horizon: net points (signed for the fade direction), max favorable
    excursion (MFE, the best the trade ever looked) and max adverse excursion
    / drawdown (MAE, the worst it ever looked) — raw material for picking
    sensible TP/SL levels. `entry` = close of the touch bar (matches the
    bracket-trade simulator's convention)."""
    records = []
    confirmed = confirmed_touches[confirmed_touches["confirmed"]]
    max_h = max(horizons_minutes)
    for _, row in confirmed.iterrows():
        side = row["side"]
        sign = _SIDE_SIGN[side]
        touched_at = row["touched_at"]
        future = ohlcv_1m.loc[touched_at:]
        if future.empty:
            continue
        entry = float(future["close"].iloc[0])
        path = future.iloc[1 : max_h + 1]
        if path.empty:
            continue

        rec = {
            "session_date": row["session_date"],
            "side": side,
            "level": row["level"],
            "touched_at": touched_at,
            "entry": entry,
            "z_at_entry": row["z_at_entry"],
            "entry_method": row["entry_method"],
        }
        for h in horizons_minutes:
            sub = path.iloc[:h]
            if sub.empty:
                for k in ("pts", "mfe", "mae", "max_dd"):
                    rec[f"{k}_{h}m"] = float("nan")
                continue
            # favorable excursion = how far price moved IN the fade's favor;
            # adverse excursion / drawdown = how far it moved against it first
            fav_excursion = sign * (sub["high"] - entry) if sign > 0 else sign * (sub["low"] - entry)
            adv_excursion = sign * (sub["low"] - entry) if sign > 0 else sign * (sub["high"] - entry)
            close_pts = sign * (float(sub["close"].iloc[-1]) - entry)
            rec[f"pts_{h}m"] = close_pts
            rec[f"mfe_{h}m"] = float(fav_excursion.max())
            rec[f"mae_{h}m"] = float(adv_excursion.min())  # most negative = worst drawdown
            rec[f"max_dd_{h}m"] = float(-adv_excursion.min()) if adv_excursion.min() < 0 else 0.0
        records.append(rec)

    return pd.DataFrame(records)


def run_fade_bracket_test(
    ohlcv_1m: pd.DataFrame,
    confirmed_touches: pd.DataFrame,
    target_pts: float,
    stop_pts: float,
    max_bars: int = 240,
) -> pd.DataFrame:
    """Run the existing fixed-bracket simulator in the FADE direction only, on
    the CONFIRMED-touch subset. Reuses `volgen.trades.simulate_bracket_trade`
    so the mechanics (entry = touch-bar close, intrabar target/stop resolution,
    ties favor the stop) are identical to the earlier raw-edge test."""
    records = []
    confirmed = confirmed_touches[confirmed_touches["confirmed"]]
    for _, row in confirmed.iterrows():
        out = simulate_bracket_trade(
            ohlcv_1m,
            side=row["side"],
            direction="fade",
            touched_at=row["touched_at"],
            level=row["level"],
            target_pts=target_pts,
            stop_pts=stop_pts,
            max_bars=max_bars,
        )
        if out is None:
            continue
        records.append(
            {
                "session_date": row["session_date"],
                "side": row["side"],
                "z_at_entry": row["z_at_entry"],
                "entry_method": row["entry_method"],
                "touched_at": out.touched_at,
                "result": out.result,
                "bars_held": out.bars_held,
                "pts": out.pts,
            }
        )
    return pd.DataFrame(records)


def summarize_confirmation_rates(confirmed_touches: pd.DataFrame) -> pd.DataFrame:
    """How often does each side's touch get FracDiff confirmation? (sanity
    check on sample size before drawing conclusions from small confirmed-n)."""
    rows = []
    for side, sub in confirmed_touches.groupby("side"):
        rows.append(
            {
                "side": side,
                "n_touches": len(sub),
                "n_confirmed": int(sub["confirmed"].sum()),
                "confirmation_rate": round(float(sub["confirmed"].mean()), 4),
            }
        )
    return pd.DataFrame(rows)
