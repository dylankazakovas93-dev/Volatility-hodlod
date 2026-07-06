"""Stage D: causal 2-state Gaussian HMM regime gate for the OG build-years
pipeline.

Design (kept deliberately simple/causal, per the Stage D spec):

  1. Feature: 60-minute-bar log returns computed from the full chronological
     bar stream (this is an *input feature*, not an outcome metric -- using
     the full stream for feature construction is explicitly allowed by the
     task's data firewall, since it is rolling/causal and lagged).
  2. Walk-forward annual refit: at the start of each calendar year Y, a
     2-state Gaussian HMM is fit ONLY on 60-min returns from all years
     strictly before Y (hmmlearn's EM fit, which is fine to run on a static
     historical window because by construction that window is entirely in
     the past relative to every bar it will be used to classify). The first
     two years (2018 has no prior data) fall back to "no gate" (regime
     gate not active) since there is no prior-year data to fit from -- this
     itself is a causal, not-cheating choice, not a leak.
  3. Causal per-bar state filtering: for bars inside year Y, the regime state
     is estimated with a manual forward-algorithm filter (alpha recursion)
     using the year-Y model's fixed transition/emission parameters and only
     observations up to and including the current bar -- NOT hmmlearn's
     default Viterbi/posterior decode, which would smooth using future
     observations within the sequence. This guarantees no lookahead within a
     trading day or across days.
  4. Gate: a touch at timestamp ts is allowed only if the causally filtered
     regime state of the most recently completed 60-minute bar strictly
     before ts equals the candidate's target state (0 or 1).

This module only builds the gate function; it computes no strategy outcome
metrics itself.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    from hmmlearn.hmm import GaussianHMM
except Exception:  # pragma: no cover
    GaussianHMM = None


def _resample_60m_logret(bars: pd.DataFrame) -> pd.Series:
    close_60m = bars["close"].resample("60min", label="right", closed="left").last().dropna()
    logret = np.log(close_60m).diff().dropna()
    return logret


def _forward_filter(obs, startprob, transmat, means, covars):
    """Manual causal forward-algorithm filter for a 2-state Gaussian HMM.
    Returns an array of filtered state probabilities, shape (n, 2), where
    row i uses only obs[0..i] (no future data)."""
    n = len(obs)
    n_states = len(startprob)
    stds = np.sqrt(np.array(covars).reshape(n_states))
    means = np.array(means).reshape(n_states)

    def emis(x):
        return (1.0 / (stds * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x - means) / stds) ** 2)

    alpha = np.zeros((n, n_states))
    e0 = emis(obs[0])
    a0 = startprob * e0
    a0 = a0 / a0.sum() if a0.sum() > 0 else startprob
    alpha[0] = a0
    for t in range(1, n):
        pred = alpha[t - 1] @ transmat
        e = emis(obs[t])
        a = pred * e
        s = a.sum()
        alpha[t] = a / s if s > 0 else pred
    return alpha


def build_causal_regime_series(bars: pd.DataFrame, min_fit_year: int = 2019) -> pd.Series:
    """Returns a pandas Series indexed by 60-min-bar right-edge timestamp ->
    causally filtered most-likely regime state (0 or 1), walk-forward refit
    annually. Years before `min_fit_year` (no prior-year data) get state -1
    (no gate / unknown -- callers should treat -1 as "gate does not apply,
    do not block")."""
    if GaussianHMM is None:
        raise RuntimeError("hmmlearn not available")

    logret = _resample_60m_logret(bars)
    years = sorted(set(logret.index.year))
    out = pd.Series(-1, index=logret.index, dtype=int)

    for y in years:
        if y < min_fit_year:
            continue
        train = logret[logret.index.year < y]
        test = logret[logret.index.year == y]
        if len(train) < 200 or len(test) == 0:
            continue
        model = GaussianHMM(n_components=2, covariance_type="diag", n_iter=100, random_state=0)
        model.fit(train.values.reshape(-1, 1))
        alpha = _forward_filter(
            test.values, model.startprob_, model.transmat_,
            model.means_, model.covars_,
        )
        states = alpha.argmax(axis=1)
        out.loc[test.index] = states

    return out


def make_hmm_gate(regime_series: pd.Series, target_state: int, bars_tz: str = "America/New_York"):
    """Returns a callable gate(ts) -> bool. ts is looked up against the most
    recently completed 60-min bar strictly before ts (causal: the regime of a
    bar isn't known until that bar closes)."""
    idx = regime_series.index

    def gate(ts) -> bool:
        # 60-min bars are right-labeled (label of the bar's close time); the
        # most recently completed bar strictly before ts:
        pos = idx.searchsorted(ts, side="left") - 1
        if pos < 0:
            return True  # no history yet -> do not block (fail-open, matches min_fit_year design)
        state = regime_series.iloc[pos]
        if state == -1:
            return True  # gate not active for this period (pre-fit years)
        return bool(state == target_state)

    return gate
