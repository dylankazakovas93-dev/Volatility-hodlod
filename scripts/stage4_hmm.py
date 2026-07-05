"""Stage 4 Part B: causal Gaussian HMM regime filter.

For a given research session S: standardize [5-min log return, trailing
30-min realized vol, trailing 30-min trend] using only the trailing (up to
120, min 20) completed sessions strictly before S, fit a Gaussian HMM
(diagonal covariance) on that trailing window, then compute FILTERED
(forward-algorithm, not smoothed/Viterbi) state probabilities bar-by-bar
through S's own completed bars using the fitted parameters (never
re-estimated intra-session). States are labeled by their fitted average
realized-volatility feature, ascending (LOW-VOL, [MID-VOL,] HIGH-VOL) --
never by looking at P&L.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM

from scripts.stage4_regime_data import trailing_sessions

warnings.filterwarnings("ignore")

MAX_SESSIONS = 120
MIN_SESSIONS = 20
N_ITER = 30
SEED = 42


def build_features(bars_5m):
    """[log_return, trailing_30min_realized_vol, trailing_30min_trend],
    each using only bars completed at or before the current bar (a
    6-bar = 30-minute trailing window of 5-min bars, inclusive of the
    current bar, matching 'completed 5-minute observations only')."""
    r = bars_5m["log_return"].fillna(0.0)
    vol30 = r.rolling(6, min_periods=6).std()
    trend30 = r.rolling(6, min_periods=6).sum()
    feat = pd.DataFrame({"ret": r, "vol30": vol30, "trend30": trend30}, index=bars_5m.index)
    feat["session_date"] = bars_5m["session_date"].to_numpy()
    return feat


def _standardize_params(train_feat):
    mu = train_feat[["ret", "vol30", "trend30"]].mean()
    sd = train_feat[["ret", "vol30", "trend30"]].std().replace(0, 1.0)
    return mu, sd


def fit_hmm_for_session(features, all_sessions, session, n_states):
    trailing = trailing_sessions(all_sessions, session, MAX_SESSIONS, MIN_SESSIONS)
    if trailing is None:
        return None
    trailing_set = set(trailing)
    train = features[features["session_date"].isin(trailing_set)].dropna(subset=["ret", "vol30", "trend30"])
    if len(train) < 200:
        return None

    mu, sd = _standardize_params(train)
    X = ((train[["ret", "vol30", "trend30"]] - mu) / sd).to_numpy()

    model = GaussianHMM(n_components=n_states, covariance_type="diag",
                         n_iter=N_ITER, random_state=SEED, tol=1e-3)
    model.fit(X)

    # order states by fitted avg realized-vol feature (index 1 = vol30), ascending
    vol_means = model.means_[:, 1]
    order = np.argsort(vol_means)
    return {"model": model, "mu": mu, "sd": sd, "state_order": order}


def causal_forward_filter(model, X):
    """Manual forward-algorithm filtering (NOT hmmlearn's predict_proba,
    which is smoothed). Returns array (n_obs, n_states) of P(state_t |
    obs_1..t), each row using only observations up to and including t."""
    n_states = model.n_components
    log_probs = model._compute_log_likelihood(X)  # (n_obs, n_states), per-obs per-state
    startprob = model.startprob_
    transmat = model.transmat_

    n_obs = X.shape[0]
    alpha = np.zeros((n_obs, n_states))
    probs = np.exp(log_probs - log_probs.max(axis=1, keepdims=True))  # stabilized likelihoods (relative)

    a = startprob * probs[0]
    a = a / a.sum() if a.sum() > 0 else np.full(n_states, 1.0 / n_states)
    alpha[0] = a
    for t in range(1, n_obs):
        a = (alpha[t - 1] @ transmat) * probs[t]
        s = a.sum()
        a = a / s if s > 0 else np.full(n_states, 1.0 / n_states)
        alpha[t] = a
    return alpha


def build_hmm_state_cache(features, all_sessions, sessions_needed, n_states):
    """Returns dict session_date -> DataFrame(index=bar ts, columns=
    state_label (ordered LOW/[MID]/HIGH), max_state, max_prob)."""
    cache = {}
    fit_cache = {}
    labels_2 = ["LOW_VOL", "HIGH_VOL"]
    labels_3 = ["LOW_VOL", "MID_VOL", "HIGH_VOL"]
    labels = labels_2 if n_states == 2 else labels_3

    for sess in sessions_needed:
        key = (sess, n_states)
        if key not in fit_cache:
            fit_cache[key] = fit_hmm_for_session(features, all_sessions, sess, n_states)
        fitted = fit_cache[key]
        if fitted is None:
            continue
        sess_feat = features[features["session_date"] == sess].dropna(subset=["ret", "vol30", "trend30"])
        if sess_feat.empty:
            continue
        X = ((sess_feat[["ret", "vol30", "trend30"]] - fitted["mu"]) / fitted["sd"]).to_numpy()
        alpha = causal_forward_filter(fitted["model"], X)
        order = fitted["state_order"]
        # reorder columns so column j corresponds to labels[j] (ascending vol)
        ordered_alpha = alpha[:, order]
        max_state_idx = ordered_alpha.argmax(axis=1)
        max_prob = ordered_alpha.max(axis=1)
        df = pd.DataFrame({
            "state_label": [labels[i] for i in max_state_idx],
            "max_prob": max_prob,
        }, index=sess_feat.index)
        cache[sess] = df
    return cache


def state_before(cache, session, entry_ts):
    """Only 5-min bars that COMPLETED strictly before entry_ts are used
    (bar_start + 5min <= entry_ts) -- never the in-progress bar containing
    the entry."""
    df = cache.get(session)
    if df is None or df.empty:
        return None, None
    cutoff = entry_ts - pd.Timedelta(minutes=5)
    prior = df[df.index <= cutoff]
    if prior.empty:
        return None, None
    row = prior.iloc[-1]
    return row["state_label"], float(row["max_prob"])
