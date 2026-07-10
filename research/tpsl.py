"""
Exit-formula fitting: instead of the fixed 60min/120min/EOS diagnostic
windows, close each trade on whichever comes first of:
  - take-profit (TP) touched,
  - stop-loss (SL) touched,
  - a hard time cutoff (15:00 or 16:00 ET) on the entry day, closed at
    that bar's mark-to-market price -- win or loss, always included.

Same entry mechanics as before (next-bar-open fill, flat-only/no-overlap,
zero lookahead). No new indicator parameters or filters: TP/SL candidates
are read directly off the population's own empirical MFE/MAE percentiles,
not free knobs.

Intrabar ambiguity: 1-minute OHLC can't tell which of TP/SL was touched
first if a single bar's range spans both. Convention used: assume the
stop was hit first (conservative). Such bars are counted and reported,
never silently ignored.
"""
import zoneinfo
import numpy as np
import pandas as pd

ET = zoneinfo.ZoneInfo("America/New_York")


def cutoff_utc_by_session(bars: pd.DataFrame, cutoff_hhmm: str) -> dict:
    """session_date -> UTC Timestamp for e.g. '15:00' or '16:00' ET on that
    session's own calendar date (the RTH-afternoon side of the session)."""
    hh, mm = (int(x) for x in cutoff_hhmm.split(":"))
    out = {}
    for s in bars["session"].unique():
        local = pd.Timestamp(s.year, s.month, s.day, hh, mm, tz=ET)
        out[s] = local.tz_convert("UTC").tz_convert(None)
    return out


def _walk_exit(entry_bar, entry_price, direction, tp_pts, sl_pts,
                cutoff_ts, session_end_idx, ts, h, l, c, breakeven_frac=None):
    """Bar-by-bar path from entry_bar forward. Returns
    (exit_idx, exit_price, outcome, pnl_pts, ambiguous).

    breakeven_frac: None disables it. Otherwise, once favorable excursion
    reaches breakeven_frac * tp_pts on bar j, the stop moves to entry price
    starting bar j+1 (never retroactively inside the arming bar itself, so
    there's no same-bar look-ahead). A stop-out after arming is outcome
    'breakeven' (pnl 0) instead of 'sl'.
    """
    j = entry_bar
    armed = False
    stop_dist = sl_pts  # distance from entry to the active stop
    while j <= session_end_idx:
        if ts[j] >= cutoff_ts:
            k = j - 1 if j > entry_bar else entry_bar
            close_px = c[k]
            pnl = (close_px - entry_price) if direction == "long" else (entry_price - close_px)
            return k, close_px, "cutoff", pnl, False

        stop_outcome = "breakeven" if armed else "sl"
        stop_pnl = 0.0 if armed else -sl_pts

        if direction == "long":
            hit_tp = h[j] >= entry_price + tp_pts
            hit_stop = l[j] <= entry_price - stop_dist
        else:
            hit_tp = l[j] <= entry_price - tp_pts
            hit_stop = h[j] >= entry_price + stop_dist

        if hit_tp and hit_stop:
            px = entry_price - stop_dist if direction == "long" else entry_price + stop_dist
            return j, px, stop_outcome, stop_pnl, True
        if hit_tp:
            px = entry_price + tp_pts if direction == "long" else entry_price - tp_pts
            return j, px, "tp", tp_pts, False
        if hit_stop:
            px = entry_price - stop_dist if direction == "long" else entry_price + stop_dist
            return j, px, stop_outcome, stop_pnl, False

        if breakeven_frac and not armed:
            trigger = breakeven_frac * tp_pts
            fav = (h[j] - entry_price) if direction == "long" else (entry_price - l[j])
            if fav >= trigger:
                armed = True
                stop_dist = 0.0
        j += 1

    close_px = c[session_end_idx]
    pnl = (close_px - entry_price) if direction == "long" else (entry_price - close_px)
    return session_end_idx, close_px, "cutoff", pnl, False


def raw_excursion_to_cutoff(signals: pd.DataFrame, bars: pd.DataFrame,
                             cutoff_hhmm: str) -> pd.DataFrame:
    """MFE/MAE from entry to the time cutoff, no TP/SL applied -- used only
    to derive percentile-based TP/SL candidates for the grid."""
    if signals.empty:
        return pd.DataFrame()
    ts = bars["ts_event"].dt.tz_convert(None).to_numpy()
    sess = bars["session"].to_numpy()
    o = bars["open"].to_numpy(dtype=float)
    h = bars["high"].to_numpy(dtype=float)
    l = bars["low"].to_numpy(dtype=float)
    n = len(bars)
    cutoffs = cutoff_utc_by_session(bars, cutoff_hhmm)
    last_idx = {s: i for i, s in enumerate(sess)}  # last row per session

    out = []
    for _, s in signals.sort_values("bar_index").iterrows():
        entry_bar = int(s["bar_index"]) + 1
        if entry_bar >= n:
            continue
        entry_session = sess[entry_bar]
        cutoff_ts = cutoffs[entry_session]
        if ts[entry_bar] >= cutoff_ts:
            continue
        session_end = last_idx[entry_session]
        mask = (ts >= ts[entry_bar]) & (ts < cutoff_ts)
        idx = np.where(mask & (sess == entry_session))[0]
        if idx.size == 0:
            continue
        entry_price = o[entry_bar]
        wh, wl = h[idx].max(), l[idx].min()
        if s["direction"] == "long":
            mfe, mae = max(0.0, wh - entry_price), max(0.0, entry_price - wl)
        else:
            mfe, mae = max(0.0, entry_price - wl), max(0.0, wh - entry_price)
        out.append(dict(mfe_pts=mfe, mae_pts=mae))
    return pd.DataFrame(out)


def simulate_tpsl(signals: pd.DataFrame, bars: pd.DataFrame, tp_pts: float,
                   sl_pts: float, cutoff_hhmm: str, breakeven_frac: float = None) -> pd.DataFrame:
    if signals.empty:
        return pd.DataFrame()
    ts = bars["ts_event"].dt.tz_convert(None).to_numpy()
    sess = bars["session"].to_numpy()
    o = bars["open"].to_numpy(dtype=float)
    h = bars["high"].to_numpy(dtype=float)
    l = bars["low"].to_numpy(dtype=float)
    c = bars["close"].to_numpy(dtype=float)
    n = len(bars)
    cutoffs = cutoff_utc_by_session(bars, cutoff_hhmm)
    last_idx = {}
    for i, s in enumerate(sess):
        last_idx[s] = i

    trades = []
    next_available_time = np.datetime64("1970-01-01")
    for _, s in signals.sort_values("bar_index").iterrows():
        entry_bar = int(s["bar_index"]) + 1
        if entry_bar >= n:
            continue
        entry_time = ts[entry_bar]
        if entry_time < next_available_time:
            continue
        entry_session = sess[entry_bar]
        cutoff_ts = cutoffs[entry_session]
        if entry_time >= cutoff_ts:
            continue  # no room left to run before the flatten time
        entry_price = o[entry_bar]
        session_end_idx = last_idx[entry_session]

        exit_idx, exit_price, outcome, pnl, ambiguous = _walk_exit(
            entry_bar, entry_price, s["direction"], tp_pts, sl_pts,
            cutoff_ts, session_end_idx, ts, h, l, c, breakeven_frac)

        trades.append(dict(
            variant=s["variant"], direction=s["direction"],
            premium=bool(s["premium"]), entry_time=entry_time,
            exit_time=ts[exit_idx], entry_price=entry_price, exit_price=exit_price,
            outcome=outcome, pnl_pts=pnl, ambiguous_bar=ambiguous,
            cluster_id=s["cluster_id"],
        ))
        next_available_time = ts[exit_idx]

    return pd.DataFrame(trades)


def grid_search_pooled(year_data: dict, cutoff_hhmm: str,
                        percentiles=(30, 40, 50, 60, 70, 80, 90)) -> tuple[pd.DataFrame, dict]:
    """year_data: {year: (signals_subset, bars)}. TP/SL candidates are drawn
    from the excursion-to-cutoff distribution pooled across all years; each
    candidate combo is then simulated per-year (bar indices are year-local)
    and the resulting trades concatenated before scoring."""
    exc_all = pd.concat(
        [raw_excursion_to_cutoff(sig, bars, cutoff_hhmm) for sig, bars in year_data.values()],
        ignore_index=True,
    )
    if exc_all.empty:
        return pd.DataFrame(), {}
    tp_candidates = sorted(set(round(exc_all["mfe_pts"].quantile(p / 100), 2) for p in percentiles))
    sl_candidates = sorted(set(round(exc_all["mae_pts"].quantile(p / 100), 2) for p in percentiles))

    rows = []
    for tp in tp_candidates:
        for sl in sl_candidates:
            if tp <= 0 or sl <= 0:
                continue
            all_trades = pd.concat(
                [simulate_tpsl(sig, bars, tp, sl, cutoff_hhmm) for sig, bars in year_data.values()],
                ignore_index=True,
            )
            if all_trades.empty:
                continue
            rows.append(dict(
                tp=tp, sl=sl, n=len(all_trades),
                win_rate=(all_trades["pnl_pts"] > 0).mean() * 100,
                mean_pnl=all_trades["pnl_pts"].mean(),
                median_pnl=all_trades["pnl_pts"].median(),
                total_pnl=all_trades["pnl_pts"].sum(),
                pct_tp=(all_trades["outcome"] == "tp").mean() * 100,
                pct_sl=(all_trades["outcome"] == "sl").mean() * 100,
                pct_cutoff=(all_trades["outcome"] == "cutoff").mean() * 100,
                pct_cutoff_win=((all_trades["outcome"] == "cutoff") & (all_trades["pnl_pts"] > 0)).mean() * 100,
                pct_ambiguous=all_trades["ambiguous_bar"].mean() * 100,
            ))
    grid = pd.DataFrame(rows)
    if grid.empty:
        return grid, {}
    best = grid.loc[grid["mean_pnl"].idxmax()].to_dict()
    return grid.sort_values("mean_pnl", ascending=False).reset_index(drop=True), best


def best_trades_pooled(year_data: dict, cutoff_hhmm: str, tp: float, sl: float) -> pd.DataFrame:
    return pd.concat(
        [simulate_tpsl(sig, bars, tp, sl, cutoff_hhmm) for sig, bars in year_data.values()],
        ignore_index=True,
    )


def trade_metrics(trades: pd.DataFrame, span_years: float) -> dict:
    """win rate / avg RR / profit factor / annualized Sharpe for one trade set."""
    if trades.empty:
        return dict(n=0)
    pnl = trades["pnl_pts"]
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    avg_win = wins.mean() if len(wins) else float("nan")
    avg_loss = abs(losses.mean()) if len(losses) else float("nan")
    n = len(trades)
    std = pnl.std(ddof=1)
    sharpe_trade = pnl.mean() / std if std and std > 0 else float("nan")
    trades_per_year = n / span_years if span_years > 0 else float("nan")
    return dict(
        n=n,
        win_rate=(pnl > 0).mean() * 100,
        avg_win=avg_win, avg_loss=avg_loss,
        avg_rr=(avg_win / avg_loss) if avg_loss else float("nan"),
        profit_factor=(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float("inf"),
        mean_pnl=pnl.mean(), median_pnl=pnl.median(), total_pnl=pnl.sum(),
        pct_tp=(trades["outcome"] == "tp").mean() * 100,
        pct_sl=(trades["outcome"] == "sl").mean() * 100,
        pct_breakeven=(trades["outcome"] == "breakeven").mean() * 100,
        pct_cutoff=(trades["outcome"] == "cutoff").mean() * 100,
        pct_ambiguous=trades["ambiguous_bar"].mean() * 100,
        sharpe_annual=sharpe_trade * (trades_per_year ** 0.5) if trades_per_year == trades_per_year else float("nan"),
    )


def fit_config(signals: pd.DataFrame, bars: pd.DataFrame,
               cutoffs=("15:00", "16:00"), breakeven_fracs=(None, 0.5),
               percentiles=(30, 40, 50, 60, 70, 80, 90),
               min_n=10, metric="sharpe_annual", span_years: float = 1.0) -> tuple[pd.DataFrame, dict]:
    """Search cutoff x TP x SL x breakeven, all read only from `signals`/`bars`
    passed in (caller is responsible for only passing the TRAIN-window slice).
    Selects the best row by `metric`, requiring at least `min_n` trades."""
    rows = []
    for cutoff in cutoffs:
        exc = raw_excursion_to_cutoff(signals, bars, cutoff)
        if exc.empty:
            continue
        tp_candidates = sorted(set(round(exc["mfe_pts"].quantile(p / 100), 2) for p in percentiles))
        sl_candidates = sorted(set(round(exc["mae_pts"].quantile(p / 100), 2) for p in percentiles))
        for tp in tp_candidates:
            if tp <= 0:
                continue
            for sl in sl_candidates:
                if sl <= 0:
                    continue
                for be in breakeven_fracs:
                    trades = simulate_tpsl(signals, bars, tp, sl, cutoff, be)
                    if len(trades) < min_n:
                        continue
                    m = trade_metrics(trades, span_years)
                    m.update(cutoff=cutoff, tp=tp, sl=sl, breakeven_frac=be)
                    rows.append(m)
    grid = pd.DataFrame(rows)
    if grid.empty:
        return grid, {}
    valid = grid[grid[metric] == grid[metric]]  # drop NaN metric rows
    if valid.empty:
        return grid, {}
    best = valid.loc[valid[metric].idxmax()].to_dict()
    return grid.sort_values(metric, ascending=False).reset_index(drop=True), best
