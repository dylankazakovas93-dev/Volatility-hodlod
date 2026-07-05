"""Shared P&L metrics used by both engine implementations. Split out of
scripts/reconcile_strict_one_position.py verbatim (no logic changes)."""
from __future__ import annotations


def profit_factor(pnl_series):
    gains = float(pnl_series[pnl_series > 0].sum())
    losses = float(-pnl_series[pnl_series < 0].sum())
    return gains / losses if losses > 0 else float("inf")


def max_drawdown(pnl_series):
    equity = pnl_series.cumsum()
    return float((equity - equity.cummax()).min())


def max_loss_streak(exit_reasons, pnls):
    best = current = 0
    for exit_reason, pnl in zip(exit_reasons, pnls):
        if pnl < -0.1 and exit_reason != "BE":
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best
