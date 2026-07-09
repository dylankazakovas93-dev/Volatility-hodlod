"""
Turn engine.py's candidate signals into filled trades and MAE/MFE ledgers.

Rules (all fixed by the user, not tunable here):
  - fill = next bar's OPEN after the signal bar's CLOSE (never same-bar close)
  - flat-only / zero overlap: no new entry while a prior trade's horizon
    window is still open, evaluated separately per horizon (60m/120m/EOS)
  - horizon window is truncated at the entry bar's own session close
    (17:00 ET); such trades are flagged `truncated=True`, never dropped
  - MAE/MFE measured in raw index points, direction-adjusted, entry bar's
    own high/low included in the excursion window
"""
import numpy as np
import pandas as pd


def _session_last_bar_idx(bars: pd.DataFrame) -> dict:
    last_idx = {}
    sess = bars["session"].to_numpy()
    for i, s in enumerate(sess):
        last_idx[s] = i  # overwritten until it lands on the true last row of each session
    return last_idx


def simulate(signals: pd.DataFrame, bars: pd.DataFrame, horizon_minutes: float | None,
             label: str) -> pd.DataFrame:
    """horizon_minutes=None means end-of-session."""
    if signals.empty:
        return pd.DataFrame()

    n = len(bars)
    ts = bars["ts_event"].to_numpy()
    sess = bars["session"].to_numpy()
    o = bars["open"].to_numpy(dtype=float)
    h = bars["high"].to_numpy(dtype=float)
    l = bars["low"].to_numpy(dtype=float)
    last_bar_of_session = _session_last_bar_idx(bars)

    sig = signals.sort_values("bar_index").reset_index(drop=True)

    trades = []
    next_available_time = pd.Timestamp("1970-01-01", tz="UTC")

    for _, s in sig.iterrows():
        sig_bar = int(s["bar_index"])
        entry_bar = sig_bar + 1
        if entry_bar >= n:
            continue  # no next bar to fill on (end of dataset)

        entry_time = ts[entry_bar]
        if entry_time < next_available_time:
            continue  # a previous trade's window is still open -> skip (flat-only)

        entry_session = sess[entry_bar]
        entry_price = o[entry_bar]
        session_end_idx = last_bar_of_session[entry_session]

        if horizon_minutes is None:
            exit_idx = session_end_idx
            truncated = False
        else:
            horizon_end_time = entry_time + np.timedelta64(int(horizon_minutes * 60), "s")
            mask = (ts >= entry_time) & (ts <= horizon_end_time) & (sess == entry_session)
            candidate_idx = np.where(mask)[0]
            exit_idx = int(candidate_idx.max()) if candidate_idx.size else entry_bar
            truncated = exit_idx >= session_end_idx and horizon_end_time > ts[session_end_idx]
            exit_idx = min(exit_idx, session_end_idx)

        if exit_idx < entry_bar:
            continue

        window_high = h[entry_bar:exit_idx + 1].max()
        window_low = l[entry_bar:exit_idx + 1].min()

        direction = s["direction"]
        if direction == "long":
            mfe = max(0.0, window_high - entry_price)
            mae = max(0.0, entry_price - window_low)
        else:
            mfe = max(0.0, entry_price - window_low)
            mae = max(0.0, window_high - entry_price)

        trades.append(dict(
            horizon=label,
            variant=s["variant"],
            direction=direction,
            entry_session=entry_session,
            signal_time=s["time"],
            entry_time=entry_time,
            exit_time=ts[exit_idx],
            entry_price=entry_price,
            bars_held=exit_idx - entry_bar + 1,
            mfe_pts=mfe,
            mae_pts=mae,
            premium=bool(s["premium"]),
            dist_to_dev=s["dist_to_dev"],
            truncated=bool(truncated),
            cluster_id=s["cluster_id"],
        ))

        next_available_time = ts[exit_idx]

    return pd.DataFrame(trades)


def run_all_horizons(signals: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    out = []
    for variant in signals["variant"].unique() if not signals.empty else []:
        vsig = signals[signals["variant"] == variant]
        out.append(simulate(vsig, bars, 60, "60min"))
        out.append(simulate(vsig, bars, 120, "120min"))
        out.append(simulate(vsig, bars, None, "EOS"))
    if not out:
        return pd.DataFrame()
    return pd.concat(out, ignore_index=True)
