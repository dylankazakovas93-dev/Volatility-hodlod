"""Causal kill-switch / regime-monitoring mechanisms for the OG dual-config
research line.

IMPORTANT SCOPE NOTE: this module never touches level generation, entry/exit
logic, management, RR, or window rules. It operates strictly as a
post-hoc filter over an already-simulated trade sequence: at trade i, each
mechanism decides "flat" (skip this trade's pnl/R -> 0) or "on" (keep the
trade as simulated), using ONLY information from trades 0..i-1 (strictly
before i). This is what "causal" means throughout this module: the kill
state assigned to row i must be a pure function of rows < i (plus fixed,
pre-registered parameters), and must never depend on row i or any row > i.

All four mechanism families are implemented as functions that take a
DataFrame with columns at least ["pnl", "cap"] (R = pnl/cap) in chronological
order, and return a boolean "flat" Series aligned to the input index (True =
flat/skip at that trade, decided using only strictly-prior history).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _cap_r(df: pd.DataFrame) -> pd.Series:
    return df["pnl"] / df["cap"]


# ---------------------------------------------------------------------------
# Mechanism 1: rolling PF (points) over trailing N trades
# ---------------------------------------------------------------------------

def rolling_pf_killswitch(
    df: pd.DataFrame,
    window: int,
    threshold: float,
    reentry_threshold: float | None = None,
) -> pd.Series:
    """Flat whenever trailing-`window`-trade PF (points, using pnl) computed
    over the `window` trades strictly before the current one drops below
    `threshold`. Re-entry: if `reentry_threshold` is None, resume normal
    trading as soon as trailing PF recovers >= `threshold` (symmetric).
    If `reentry_threshold` is given (> threshold), require trailing PF to
    recover to that higher bar before resuming (hysteretic re-entry, avoids
    whipsaw right at the threshold).

    Causal by construction: the trailing window at row i uses only pnl values
    from rows i-window..i-1 (strictly before i), and the on/off state is a
    left-to-right scan depending only on past PF values and the previous
    state -- never row i or later.
    """
    pnl = df["pnl"].to_numpy()
    n = len(pnl)
    flat = np.zeros(n, dtype=bool)
    reentry_thr = reentry_threshold if reentry_threshold is not None else threshold

    state_flat = False  # start "on" (no prior evidence of trouble)
    for i in range(n):
        if i >= window:
            trailing = pnl[i - window:i]
            gains = trailing[trailing > 0].sum()
            losses = -trailing[trailing < 0].sum()
            pf = gains / losses if losses > 0 else np.inf
            if state_flat:
                if pf >= reentry_thr:
                    state_flat = False
            else:
                if pf < threshold:
                    state_flat = True
        # if i < window: not enough history -> stay in current (initial "on") state
        flat[i] = state_flat
    return pd.Series(flat, index=df.index)


# ---------------------------------------------------------------------------
# Mechanism 2: rolling win-rate + rolling avg R/trade (diagnostic overlay)
# ---------------------------------------------------------------------------

def rolling_diagnostics(df: pd.DataFrame, window: int) -> pd.DataFrame:
    """Trailing (strictly-prior) win rate and avg R/trade over `window`
    trades, aligned to df's index. Diagnostic only -- not a kill-switch by
    itself. NaN for the first `window` rows (insufficient history)."""
    r = _cap_r(df).to_numpy()
    is_win = (df["pnl"].to_numpy() > 0).astype(float)
    n = len(r)
    win_rate = np.full(n, np.nan)
    avg_r = np.full(n, np.nan)
    for i in range(window, n):
        trailing_r = r[i - window:i]
        trailing_w = is_win[i - window:i]
        win_rate[i] = trailing_w.mean()
        avg_r[i] = trailing_r.mean()
    return pd.DataFrame({"trailing_win_rate": win_rate, "trailing_avg_R": avg_r}, index=df.index)


# ---------------------------------------------------------------------------
# Mechanism 3: one-sided CUSUM change-point detection on trade-level R
# ---------------------------------------------------------------------------

def cusum_killswitch(
    df: pd.DataFrame,
    target_mean: float,
    k: float,
    h: float,
    cooldown_trades: int,
) -> pd.DataFrame:
    """Standard one-sided (downward) CUSUM detector on the R-sequence.

    S_i = max(0, S_{i-1} - (R_i - target_mean) - k)   [downward-drift CUSUM,
    accumulates evidence of R falling below target_mean by more than slack k]
    Alarm (downward) when S_i > h.

    A symmetric upward accumulator S_up is also tracked; an upward alarm
    (S_up_i > h) is used only as an early "all clear" resume signal per the
    spec ("resume ... once an upward CUSUM alarm fires").

    Kill-switch: go flat immediately upon a downward alarm; resume once
    `cooldown_trades` consecutive trades have passed with no further downward
    alarm, OR an upward alarm fires (whichever comes first).

    Causal: S_i depends only on R_1..R_i (through the standard CUSUM
    recursion with R_i being the trade being evaluated), and the kill state
    applied when evaluating trade i is determined by the alarm state as of
    the close of trade i-1 (i.e. the state at row i is decided BEFORE trade
    i's own R is observed -- we use S_{i-1}, not S_i, to gate trade i).
    """
    r = _cap_r(df).to_numpy()
    n = len(r)
    s_down = 0.0
    s_up = 0.0
    flat = np.zeros(n, dtype=bool)
    alarm_down = np.zeros(n, dtype=bool)
    alarm_up = np.zeros(n, dtype=bool)

    state_flat = False
    trades_since_alarm = cooldown_trades  # large enough to not gate at start

    for i in range(n):
        # Decision for trade i uses state accumulated through i-1 only.
        flat[i] = state_flat

        # Now update CUSUM using trade i's own realized R (this updates the
        # state that will gate trade i+1, never trade i itself).
        s_down = max(0.0, s_down - (r[i] - target_mean) - k)
        s_up = max(0.0, s_up + (r[i] - target_mean) - k)

        down_fired = s_down > h
        up_fired = s_up > h
        alarm_down[i] = down_fired
        alarm_up[i] = up_fired

        if down_fired:
            state_flat = True
            trades_since_alarm = 0
            s_down = 0.0  # reset accumulator after alarm (standard CUSUM practice)
        elif state_flat:
            trades_since_alarm += 1
            if up_fired:
                state_flat = False
                s_up = 0.0
            elif trades_since_alarm >= cooldown_trades:
                state_flat = False

    return pd.DataFrame(
        {"flat": flat, "cusum_alarm_down": alarm_down, "cusum_alarm_up": alarm_up},
        index=df.index,
    )


# ---------------------------------------------------------------------------
# Mechanism 4: consecutive non-winning-streak tracking vs a build-year baseline
# ---------------------------------------------------------------------------

def compute_nonwin_streaks(df: pd.DataFrame) -> np.ndarray:
    """Return the max non-winning streak length observed within df (a single
    pass, non-causal helper used ONLY to build the baseline distribution from
    build years, never used to gate live trades)."""
    is_win = (df["pnl"].to_numpy() > 0)
    streaks = []
    cur = 0
    for w in is_win:
        if w:
            if cur > 0:
                streaks.append(cur)
            cur = 0
        else:
            cur += 1
    if cur > 0:
        streaks.append(cur)
    return np.array(streaks)


def streak_killswitch(
    df: pd.DataFrame,
    baseline_streaks: np.ndarray,
    percentile: float,
    resume_after_wins: int,
) -> pd.Series:
    """Go flat once the current non-winning streak (counting strictly-prior
    trades) exceeds the `percentile`-th percentile of `baseline_streaks`
    (computed once, in advance, from build-year data only -- passed in as a
    fixed constant, not recomputed on the fly). Resume after
    `resume_after_wins` consecutive winning trades are observed.

    Causal: the streak length used to gate trade i counts only trades
    strictly before i; the win/loss outcome of trade i itself is applied to
    the running streak AFTER the gating decision for trade i is made.
    """
    threshold = np.percentile(baseline_streaks, percentile) if len(baseline_streaks) else np.inf
    is_win = (df["pnl"].to_numpy() > 0)
    n = len(is_win)
    flat = np.zeros(n, dtype=bool)

    cur_nonwin_streak = 0
    cur_win_streak = 0
    state_flat = False

    for i in range(n):
        flat[i] = state_flat  # decision for i uses streak state through i-1

        if is_win[i]:
            cur_win_streak += 1
            cur_nonwin_streak = 0
        else:
            cur_win_streak = 0
            cur_nonwin_streak += 1

        if not state_flat and cur_nonwin_streak > threshold:
            state_flat = True
        elif state_flat and cur_win_streak >= resume_after_wins:
            state_flat = False

    return pd.Series(flat, index=df.index)


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------

def apply_flat_mask(df: pd.DataFrame, flat: pd.Series) -> pd.DataFrame:
    """Return a copy of df with pnl (and derived R) zeroed out on flat rows.
    This models "skip the touch" -- no P&L, no R, for that trade."""
    out = df.copy()
    out["pnl_effective"] = np.where(flat.to_numpy(), 0.0, out["pnl"].to_numpy())
    out["R_effective"] = out["pnl_effective"] / out["cap"]
    out["is_flat"] = flat.to_numpy()
    return out


def summarize(df_eff: pd.DataFrame, pnl_col: str = "pnl_effective", r_col: str = "R_effective") -> dict:
    from src.metrics import profit_factor, max_drawdown

    pnl = df_eff[pnl_col]
    r = df_eff[r_col]
    n = len(df_eff)
    return {
        "n_trades": n,
        "net_pts": float(pnl.sum()),
        "total_R": float(r.sum()),
        "PF_pts": profit_factor(pnl),
        "PF_R": profit_factor(r),
        "avg_R_per_trade": float(r.mean()) if n else 0.0,
        "max_dd_pts": max_drawdown(pnl),
        "max_dd_R": max_drawdown(r),
        "n_flat_trades": int(df_eff["is_flat"].sum()) if "is_flat" in df_eff.columns else 0,
    }
