"""Stage D (full rebuild): causal, session-refit Gaussian HMM regime-gate
infrastructure for the OG build-four-years research pipeline.

This SUPERSEDES the prior session's diagnostic-only 2-state/60-min-return
walk-forward-ANNUAL version (see docs/OG_STAGE_D_HMM.md, SUPERSEDED section).
That version refit once per calendar year on 60-min returns. This version:

  - Uses three features per 5-minute bar, all causal/rolling, no lookahead:
      1. 5-minute log return
      2. trailing 30-minute realized volatility (rolling std of the 5-min
         log return over the trailing 6 bars = 30 minutes)
      3. trailing 30-minute cumulative return/trend (rolling sum of the
         5-min log return over the same trailing 6-bar window)
  - Refits ONCE PER SESSION (not once per year, not continuously intra-day):
    at the start of each session, on the trailing window of the previous
    20-120 *completed* sessions (max 120, min 20 -- sessions with fewer than
    20 prior completed sessions get no gate at all, fail-open).
  - The session being classified is NEVER in its own training window.
  - Standardizes features using ONLY the training window's mean/std.
  - Forward-filters (alpha-recursion) causally, bar by bar, WITHIN the
    session, using the fixed model fit at session start. No smoothing
    (forward-backward) and no Viterbi full-path decoding are used anywhere,
    since both would leak future-within-session information.
  - Orders states by fitted volatility (ascending) at every single refit, so
    "state 0" always means the lowest fitted-vol regime, regardless of
    hmmlearn's arbitrary internal component ordering -- this makes labels
    ("LOW"/"MID"/"HIGH") comparable across sessions/refits.

Per the data firewall: fitting/feature construction may use the full
historical bar stream (rolling, causal, lagged) -- this module only computes
regime PROBABILITIES (an input feature), never a strategy outcome. To keep
compute tractable, callers pass `target_sessions` (the only sessions whose
regime classification is actually needed) -- for this pipeline that is
exactly the sessions containing a build-year touch. Fitting on the causal
trailing window naturally pulls in some non-build-year bars as training
DATA for the price-return HMM, which is explicitly permitted (feature
construction only, never an outcome).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.strict_engine import session_date

try:
    from hmmlearn.hmm import GaussianHMM
except Exception:  # pragma: no cover
    GaussianHMM = None

FEATURE_COLS = ["logret5m", "vol30m", "trend30m"]
VOL_COL_IDX = FEATURE_COLS.index("vol30m")


def build_5m_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Causal 5-minute feature frame. Row at time t uses only bars <= t."""
    c5 = bars["close"].resample("5min", label="right", closed="left").last().dropna()
    logret = np.log(c5).diff()
    vol30 = logret.rolling(6).std()
    trend30 = logret.rolling(6).sum()
    df = pd.DataFrame({"logret5m": logret, "vol30m": vol30, "trend30m": trend30}).dropna()
    df["session"] = [session_date(ts) for ts in df.index]
    return df


def _diag_gaussian_emis(x, means, stds):
    """x: (d,), means/stds: (k,d) -> emission likelihood per state, (k,)."""
    z = (x[None, :] - means) / stds
    exponent = -0.5 * np.sum(z * z, axis=1)
    norm = np.prod(1.0 / (stds * np.sqrt(2 * np.pi)), axis=1)
    return norm * np.exp(exponent)


def forward_filter(X, startprob, transmat, means, covars):
    """Causal forward-algorithm (alpha-recursion) filter for a diagonal-
    covariance Gaussian HMM. Row t of the returned (n,k) array depends only
    on X[0..t] -- this is the causality property under test in
    tests/test_og_hmm_causality.py / the runner's self-check."""
    n = X.shape[0]
    k = len(startprob)
    stds = np.sqrt(np.maximum(covars, 1e-12))
    alpha = np.zeros((n, k))
    e0 = _diag_gaussian_emis(X[0], means, stds)
    a0 = startprob * e0
    s0 = a0.sum()
    alpha[0] = a0 / s0 if s0 > 0 else startprob
    for t in range(1, n):
        pred = alpha[t - 1] @ transmat
        e = _diag_gaussian_emis(X[t], means, stds)
        a = pred * e
        s = a.sum()
        alpha[t] = a / s if s > 0 else pred
    return alpha


def fit_session_hmm(X_train, n_states, random_state):
    """Fit a diagonal-covariance GaussianHMM on standardized training data
    and return (startprob, transmat, means, covars) reordered so state 0 is
    lowest fitted volatility, state (n_states-1) is highest."""
    if GaussianHMM is None:
        raise RuntimeError("hmmlearn not available")
    model = GaussianHMM(
        n_components=n_states, covariance_type="diag", n_iter=20,
        tol=1e-2, random_state=random_state,
    )
    model.fit(X_train)
    order = np.argsort(model.means_[:, VOL_COL_IDX])
    startprob = model.startprob_[order]
    transmat = model.transmat_[np.ix_(order, order)]
    means = model.means_[order]
    covars = np.asarray(model.covars_)[order]
    if covars.ndim == 3:  # (k,d,d) -> diag
        covars = np.array([np.diag(c) for c in covars])
    return startprob, transmat, means, covars


def causal_session_regime_probs(features_df, target_sessions, *, n_states=2,
                                 min_sessions=20, max_sessions=120,
                                 random_state=42):
    """Walk-forward, session-refit causal HMM regime probabilities.

    Only computes probabilities for sessions in `target_sessions` (an
    iterable of session dates) -- this is the data-firewall enforcement
    point for Stage D: no other session's classification is ever computed.

    Returns (regime_df, meta):
      regime_df: DataFrame indexed by 5-min bar timestamp (only rows for
        classified sessions), columns state_prob_0..state_prob_{n_states-1}
        (ascending fitted volatility order), plus 'session' and
        'n_train_sessions'.
      meta: dict with 'n_sessions_requested', 'n_sessions_skipped_insufficient_history',
        'n_sessions_classified', 'skipped_sessions' (list).
    """
    target_sessions = set(target_sessions)
    sessions_sorted = sorted(features_df["session"].unique())
    sess_rows = {s: g for s, g in features_df.groupby("session")}

    frames = []
    skipped = []
    n_classified = 0
    for i, sess in enumerate(sessions_sorted):
        if sess not in target_sessions:
            continue
        prior = sessions_sorted[:i]
        if len(prior) < min_sessions:
            skipped.append(sess)
            continue
        train_sessions = prior[-max_sessions:]
        train_df = pd.concat([sess_rows[s] for s in train_sessions])
        X_train_raw = train_df[FEATURE_COLS].values
        mu, sd = X_train_raw.mean(axis=0), X_train_raw.std(axis=0)
        sd = np.where(sd == 0, 1.0, sd)
        Xs_train = (X_train_raw - mu) / sd

        startprob, transmat, means, covars = fit_session_hmm(Xs_train, n_states, random_state)

        test_df = sess_rows[sess]
        Xs_test = (test_df[FEATURE_COLS].values - mu) / sd  # train-only standardization
        alpha = forward_filter(Xs_test, startprob, transmat, means, covars)

        cols = {f"state_prob_{j}": alpha[:, j] for j in range(n_states)}
        cols["session"] = sess
        cols["n_train_sessions"] = len(train_sessions)
        frames.append(pd.DataFrame(cols, index=test_df.index))
        n_classified += 1

    regime_df = pd.concat(frames).sort_index() if frames else pd.DataFrame()
    meta = {
        "n_sessions_requested": len(target_sessions),
        "n_sessions_skipped_insufficient_history": len(skipped),
        "n_sessions_classified": n_classified,
        "skipped_sessions": [str(s) for s in skipped],
        "n_states": n_states,
        "min_sessions": min_sessions,
        "max_sessions": max_sessions,
        "random_state": random_state,
    }
    return regime_df, meta


def make_gate(regime_df, *, state_idx=None, exclude_idx=None, threshold=0.55):
    """Returns callable gate(ts) -> bool. Exactly one of state_idx/exclude_idx
    should be set:
      - state_idx: allow only if causally filtered P(state==state_idx) > threshold
      - exclude_idx: allow only if causally filtered P(state!=exclude_idx) > threshold
    A touch at ts is checked against the most recently COMPLETED 5-min bar
    strictly before ts (the bar containing ts itself is not yet closed).
    Sessions with no classification (insufficient history, or not in
    regime_df at all) fail OPEN (gate does not block), per the task's
    explicit skip/no-gate rule."""
    if regime_df is None or len(regime_df) == 0:
        return lambda ts: True
    idx = regime_df.index

    def gate(ts) -> bool:
        pos = idx.searchsorted(ts, side="left") - 1
        if pos < 0:
            return True
        row = regime_df.iloc[pos]
        if state_idx is not None:
            return bool(row[f"state_prob_{state_idx}"] > threshold)
        if exclude_idx is not None:
            return bool((1.0 - row[f"state_prob_{exclude_idx}"]) > threshold)
        return True

    return gate
