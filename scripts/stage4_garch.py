"""Stage 4 Part A: causal GARCH(1,1)-Student-t regime forecast.

For a given research session S: fit GARCH(1,1)-t on the trailing (up to
120, minimum 20) completed sessions' 5-minute log returns, EXCLUDING
session S itself. Then recurse the conditional-variance equation forward
through S's own completed 5-minute bars, using the fitted omega/alpha/beta
(never re-estimated intra-session), to produce a one-step-ahead forecast
available immediately before each trade entry.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from arch import arch_model

from scripts.stage4_regime_data import trailing_sessions

warnings.filterwarnings("ignore", category=UserWarning)

MAX_SESSIONS = 120
MIN_SESSIONS = 20


def fit_garch_for_session(bars_5m, all_sessions, session):
    """Returns (omega, alpha, beta, nu, h_end) fit on trailing sessions'
    returns, where h_end is the fitted conditional variance at the LAST
    trailing observation (used to initialize the intra-session recursion).
    Returns None if insufficient trailing history."""
    trailing = trailing_sessions(all_sessions, session, MAX_SESSIONS, MIN_SESSIONS)
    if trailing is None:
        return None
    trailing_set = set(trailing)
    ret = bars_5m.loc[bars_5m["session_date"].isin(trailing_set), "log_return"].dropna()
    ret = ret[np.isfinite(ret)]
    if len(ret) < 200:
        return None

    # arch_model expects returns scaled to a reasonable magnitude for its optimizer
    scaled = ret * 100.0
    am = arch_model(scaled, mean="Zero", vol="Garch", p=1, q=1, dist="t")
    res = am.fit(disp="off", show_warning=False)
    omega = res.params["omega"] / (100.0 ** 2)
    alpha = res.params["alpha[1]"]
    beta = res.params["beta[1]"]
    nu = res.params["nu"]
    h_end = float(res.conditional_volatility.iloc[-1] ** 2) / (100.0 ** 2)
    return {"omega": omega, "alpha": alpha, "beta": beta, "nu": nu, "h_end": h_end}


def intra_session_forecasts(bars_5m_session, params):
    """Given the fitted params and the session's own 5-min bars (in
    chronological order), returns a Series of one-step-ahead conditional
    variance forecasts indexed by the timestamp of the NEXT bar they
    predict (i.e. forecast_at[t] is available using data strictly before
    bar t)."""
    omega, alpha, beta = params["omega"], params["alpha"], params["beta"]
    h = params["h_end"]
    returns = bars_5m_session["log_return"].fillna(0.0).to_numpy()
    idx = bars_5m_session.index
    forecasts = {}
    for i in range(len(returns)):
        # h is the forecast for bar i (available before bar i occurs)
        forecasts[idx[i]] = h
        h = omega + alpha * (returns[i] ** 2) + beta * h
    return pd.Series(forecasts)


def build_garch_forecast_cache(bars_5m, all_sessions, sessions_needed):
    """Fits once per distinct session in `sessions_needed`, returns a dict
    session_date -> Series(timestamp -> one-step-ahead variance forecast)."""
    cache = {}
    fit_cache = {}
    for sess in sessions_needed:
        if sess not in fit_cache:
            fit_cache[sess] = fit_garch_for_session(bars_5m, all_sessions, sess)
        params = fit_cache[sess]
        if params is None:
            continue
        sess_bars = bars_5m[bars_5m["session_date"] == sess]
        cache[sess] = intra_session_forecasts(sess_bars, params)
    return cache


def forecast_before(cache, session, entry_ts):
    """The forecast (conditional variance) available immediately before
    `entry_ts`: only 5-min bars that COMPLETED strictly before entry_ts
    (bar_start + 5min <= entry_ts) are used -- never the in-progress bar
    containing the entry."""
    series = cache.get(session)
    if series is None or series.empty:
        return None
    cutoff = entry_ts - pd.Timedelta(minutes=5)
    prior = series[series.index <= cutoff]
    if prior.empty:
        return None
    return float(prior.iloc[-1])
