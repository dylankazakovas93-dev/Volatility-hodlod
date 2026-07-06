"""Locked out-of-sample holdout engine (LOCKED_NONCONSECUTIVE_HOLDOUT).

Reuses, unchanged, the frozen mechanics from every prior stage:
  - F2 TP/SL formula, fit ONLY on DEV_YEARS, via scripts.stage2_engine
    (fit_frozen_formula / apply_frozen_formula) -- never refit here.
  - profit_lock_0.75R management via scripts.stage3_engine.simulate_exact_r_be
    (trigger_r=0.75, lock_r=0.10, next-bar activation) -- unchanged.
  - Entry window 05:00-11:00 ET (Stage 5 blocks E+F+G+H+I) and 15:59 ET
    forced-liquidation cutoff, via scripts.stage5_engine (BLOCKS,
    in_allowed_blocks, session_cutoff_ts) -- unchanged.
  - Causal rolling 3-state Gaussian HMM (per-session refit, trailing
    max 120 / min 20 sessions, forward-filtered only) via
    scripts.stage4_hmm (fit_hmm_for_session, causal_forward_filter) --
    unchanged. hmm3_exclude_LOW_VOL gate unchanged.

New in this module (OOS-specific, additive only):
  - a richer per-session HMM cache that also records fit diagnostics
    (training-session span, count, and a parameter hash) needed for the
    OOS ledger's audit-trail requirement;
  - a standalone diagonal-Gaussian causal forward-filter that applies the
    FROZEN Pine-compatible HMM parameters (already fit and saved in
    outputs/stage5_pine_hmm_frozen_params.json) to session feature data,
    without any refitting -- this mirrors, line for line, the forward-
    filter algorithm in scripts.stage4_hmm.causal_forward_filter, and is
    verified (tests/test_oos_holdout.py) to reproduce
    outputs/stage5_pine_hmm_2026_features.csv exactly before being
    trusted on 2024/2025.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from scripts.stage2_engine import DEV_YEARS, RESERVED_YEARS, minutes_since_session_start
from scripts.stage4_hmm import fit_hmm_for_session, causal_forward_filter
from scripts.stage4_regime_data import trailing_sessions
from scripts.stage5_engine import BLOCKS, in_allowed_blocks, session_cutoff_ts
import scripts.stage3_engine as s3

SELECTED_BLOCKS = {"E", "F", "G", "H", "I"}  # 05:00-11:00 ET, frozen Stage 5 selection
SELECTED_CUTOFF_MINUTES = 1319  # 15:59 ET
TRIGGER_R = 0.75
LOCK_R = 0.10
MAX_TRAIN_SESSIONS = 120
MIN_TRAIN_SESSIONS = 20
LABELS_3 = ["LOW_VOL", "MID_VOL", "HIGH_VOL"]


def _hmm_param_hash(model):
    payload = json.dumps({
        "means": np.round(model.means_, 10).tolist(),
        "covars": np.round(model.covars_, 10).tolist(),
        "transmat": np.round(model.transmat_, 10).tolist(),
        "startprob": np.round(model.startprob_, 10).tolist(),
    }, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def build_rich_hmm3_cache(features, all_sessions, sessions_needed, n_states=3):
    """Returns (cache_probs, cache_meta).

    cache_probs[session] = DataFrame(index=bar_ts, columns=
        state_label, max_prob, prob_LOW_VOL, prob_MID_VOL, prob_HIGH_VOL)
    cache_meta[session] = {n_train_sessions, earliest_train_session,
        latest_train_session, param_hash} or None if no fit was possible
        (insufficient trailing history -- < MIN_TRAIN_SESSIONS).
    """
    cache_probs, cache_meta = {}, {}
    fit_cache = {}
    for sess in sessions_needed:
        if sess not in fit_cache:
            trailing = trailing_sessions(all_sessions, sess, MAX_TRAIN_SESSIONS, MIN_TRAIN_SESSIONS)
            fitted = fit_hmm_for_session(features, all_sessions, sess, n_states)
            fit_cache[sess] = (fitted, trailing)
        fitted, trailing = fit_cache[sess]
        if fitted is None or trailing is None:
            cache_meta[sess] = None
            continue

        sess_feat = features[features["session_date"] == sess].dropna(subset=["ret", "vol30", "trend30"])
        if sess_feat.empty:
            cache_meta[sess] = None
            continue

        X = ((sess_feat[["ret", "vol30", "trend30"]] - fitted["mu"]) / fitted["sd"]).to_numpy()
        alpha = causal_forward_filter(fitted["model"], X)
        order = fitted["state_order"]
        ordered_alpha = alpha[:, order]
        max_state_idx = ordered_alpha.argmax(axis=1)
        max_prob = ordered_alpha.max(axis=1)

        df = pd.DataFrame({
            "state_label": [LABELS_3[i] for i in max_state_idx],
            "max_prob": max_prob,
            "prob_LOW_VOL": ordered_alpha[:, 0],
            "prob_MID_VOL": ordered_alpha[:, 1],
            "prob_HIGH_VOL": ordered_alpha[:, 2],
        }, index=sess_feat.index)
        cache_probs[sess] = df
        cache_meta[sess] = {
            "n_train_sessions": len(trailing),
            "earliest_train_session": str(trailing[0]),
            "latest_train_session": str(trailing[-1]),
            "param_hash": _hmm_param_hash(fitted["model"]),
        }
    return cache_probs, cache_meta


def state_before_rich(cache_probs, cache_meta, session, entry_ts):
    """Causal lookup: only 5-min bars that COMPLETED strictly before
    entry_ts (bar_start + 5min <= entry_ts). Returns a dict of ledger
    fields, all None if no state is available (treated as HMM-blocked)."""
    empty = {
        "hmm_state": None, "hmm_prob": None,
        "hmm_prob_low": None, "hmm_prob_mid": None, "hmm_prob_high": None,
        "hmm_last_bar_ts": None, "hmm_n_train_sessions": None,
        "hmm_earliest_train_session": None, "hmm_latest_train_session": None,
        "hmm_param_hash": None,
    }
    df = cache_probs.get(session)
    if df is None or df.empty:
        return empty
    cutoff = entry_ts - pd.Timedelta(minutes=5)
    prior = df[df.index <= cutoff]
    if prior.empty:
        return empty
    row = prior.iloc[-1]
    meta = cache_meta.get(session) or {}
    return {
        "hmm_state": row["state_label"], "hmm_prob": float(row["max_prob"]),
        "hmm_prob_low": float(row["prob_LOW_VOL"]), "hmm_prob_mid": float(row["prob_MID_VOL"]),
        "hmm_prob_high": float(row["prob_HIGH_VOL"]), "hmm_last_bar_ts": prior.index[-1],
        "hmm_n_train_sessions": meta.get("n_train_sessions"),
        "hmm_earliest_train_session": meta.get("earliest_train_session"),
        "hmm_latest_train_session": meta.get("latest_train_session"),
        "hmm_param_hash": meta.get("param_hash"),
    }


# ---------------------------------------------------------------------------
# Frozen Pine-compatible HMM: standalone application (no refitting), applied
# ONLY to sessions in years {2024, 2025} per the task's causality constraint
# (params were fit on 2018+2020+2023; applying to 2019/2021/2022 would use
# parameters trained on data from years chronologically after those touches).
# ---------------------------------------------------------------------------

def load_pine_frozen_params(path):
    with open(path) as f:
        return json.load(f)


def _diag_gaussian_loglik(X, means, variances):
    return -0.5 * (np.sum(np.log(2 * np.pi * variances)) + np.sum((X - means) ** 2 / variances, axis=1))


def _forward_filter_from_loglik(log_probs, startprob, transmat):
    """Identical algorithm to scripts.stage4_hmm.causal_forward_filter,
    decoupled from an hmmlearn model object so it can run directly off
    JSON-serialized frozen parameters."""
    n_obs, n_states = log_probs.shape
    probs = np.exp(log_probs - log_probs.max(axis=1, keepdims=True))
    alpha = np.zeros((n_obs, n_states))
    a = startprob * probs[0]
    s = a.sum()
    a = a / s if s > 0 else np.full(n_states, 1.0 / n_states)
    alpha[0] = a
    for t in range(1, n_obs):
        a = (alpha[t - 1] @ transmat) * probs[t]
        s = a.sum()
        a = a / s if s > 0 else np.full(n_states, 1.0 / n_states)
        alpha[t] = a
    return alpha


def apply_pine_frozen_to_session(params, sess_feat):
    """sess_feat: DataFrame with columns ret, vol30, trend30, indexed by bar
    ts, for ONE session. Alpha restarts fresh at the session's first bar
    (matching scripts/build_stage5_pine_hmm.py's existing, already-committed
    per-session-restart methodology -- not redesigned here)."""
    mu = np.array([params["mu"]["ret"], params["mu"]["vol30"], params["mu"]["trend30"]])
    sd = np.array([params["sd"]["ret"], params["sd"]["vol30"], params["sd"]["trend30"]])
    means = np.array(params["means"])       # (3, 3), raw state order == state_order (ascending vol)
    covars = np.array(params["covars"])     # (3, 3, 3) diagonal matrices
    variances = np.diagonal(covars, axis1=1, axis2=2)  # (3, 3)
    startprob = np.array(params["startprob"])
    transmat = np.array(params["transmat"])
    order = params["state_order"]
    labels = params["labels"]

    X = ((sess_feat[["ret", "vol30", "trend30"]].to_numpy() - mu) / sd)
    log_probs = np.column_stack([_diag_gaussian_loglik(X, means[s], variances[s]) for s in range(3)])
    alpha = _forward_filter_from_loglik(log_probs, startprob, transmat)
    ordered_alpha = alpha[:, order]
    max_state_idx = ordered_alpha.argmax(axis=1)
    max_prob = ordered_alpha.max(axis=1)
    return pd.DataFrame({
        "state_label": [labels[i] for i in max_state_idx],
        "max_prob": max_prob,
    }, index=sess_feat.index)


def build_pine_cache(features, sessions_needed, params):
    cache = {}
    for sess in sessions_needed:
        sess_feat = features[features["session_date"] == sess].dropna(subset=["ret", "vol30", "trend30"])
        if sess_feat.empty:
            continue
        cache[sess] = apply_pine_frozen_to_session(params, sess_feat)
    return cache


def state_before_pine(cache, session, entry_ts):
    df = cache.get(session)
    if df is None or df.empty:
        return None, None
    cutoff = entry_ts - pd.Timedelta(minutes=5)
    prior = df[df.index <= cutoff]
    if prior.empty:
        return None, None
    row = prior.iloc[-1]
    return row["state_label"], float(row["max_prob"])


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def run_oos_replay(bars, full_df, hmm_lookup_fn, tradeable_years):
    """Single continuous chronological replay over the ENTIRE master table
    (all years present in full_df), in touched_at order. Only touches whose
    year is in `tradeable_years` are ever entered; all other years' touches
    are skipped immediately (blocked_non_tradeable_year) without affecting
    position state (since they were never eligible to open a position in
    the first place). position_open_until is a single running variable with
    no per-year reset.

    hmm_lookup_fn(session, entry_ts) -> dict of ledger fields (see
    state_before_rich / must include at least 'hmm_state').

    Returns (ledger_df, skip_counts).
    """
    df = full_df.dropna(subset=["tp_dist_stage2", "sl_dist_stage2"]).sort_values("touched_at")
    ledger = []
    skip_counts = {
        "blocked_non_tradeable_year": 0, "blocked_window": 0, "blocked_low_vol": 0,
        "blocked_at_or_after_cutoff": 0, "position_open": 0, "same_bar_reentry": 0,
    }
    position_open_until = None

    for row in df.itertuples(index=False):
        year = getattr(row, "year")
        ts = getattr(row, "touched_at")
        sess = getattr(row, "session_date")
        level_id = getattr(row, "level_id")
        side = getattr(row, "side")

        if year not in tradeable_years:
            skip_counts["blocked_non_tradeable_year"] += 1
            continue

        minutes_elapsed = minutes_since_session_start(ts, sess)
        window_allowed = in_allowed_blocks(minutes_elapsed, SELECTED_BLOCKS)

        hmm_info = hmm_lookup_fn(sess, ts)
        hmm_state = hmm_info.get("hmm_state")
        hmm_allowed = hmm_state is not None and hmm_state != "LOW_VOL"

        position_available = not (position_open_until is not None and ts <= position_open_until)
        cutoff_ok = minutes_elapsed < SELECTED_CUTOFF_MINUTES

        # Determine the single, mutually-exclusive final skip reason, in a
        # fixed precedence identical to prior stages: cutoff, then window,
        # then regime, then position.
        skip_reason = None
        if not cutoff_ok:
            skip_reason = "blocked_at_or_after_cutoff"
        elif not window_allowed:
            skip_reason = "blocked_window"
        elif not hmm_allowed:
            skip_reason = "blocked_low_vol"
        elif position_open_until is not None and ts < position_open_until:
            skip_reason = "position_open"
        elif position_open_until is not None and ts == position_open_until:
            skip_reason = "same_bar_reentry"

        record = {
            "level_id": level_id, "side": side, "session_date": sess, "year": year,
            "created_at": getattr(row, "created_at"), "expiry_at": getattr(row, "expiry_at"),
            "touched_at": ts, "entry_price": getattr(row, "entry_price"),
            "minutes_elapsed": minutes_elapsed, "window_allowed": window_allowed,
            "hmm_state": hmm_state, "hmm_prob": hmm_info.get("hmm_prob"),
            "hmm_prob_low": hmm_info.get("hmm_prob_low"), "hmm_prob_mid": hmm_info.get("hmm_prob_mid"),
            "hmm_prob_high": hmm_info.get("hmm_prob_high"),
            "hmm_last_bar_ts": hmm_info.get("hmm_last_bar_ts"),
            "hmm_n_train_sessions": hmm_info.get("hmm_n_train_sessions"),
            "hmm_earliest_train_session": hmm_info.get("hmm_earliest_train_session"),
            "hmm_latest_train_session": hmm_info.get("hmm_latest_train_session"),
            "hmm_param_hash": hmm_info.get("hmm_param_hash"),
            "hmm_allowed": hmm_allowed, "position_available": position_available,
            "tp_dist": getattr(row, "tp_dist_stage2"), "sl_dist": getattr(row, "sl_dist_stage2"),
            "skip_reason": skip_reason,
            "entry_time": None, "profit_lock_trigger_ts": None, "profit_lock_activation_ts": None,
            "exit_time": None, "exit_reason": None, "pnl_pts": None, "r_multiple": None,
        }

        if skip_reason is not None:
            skip_counts[skip_reason] += 1
            ledger.append(record)
            continue

        sign = 1.0 if side == "lower" else -1.0
        entry_price = getattr(row, "entry_price")
        cutoff_ts = session_cutoff_ts(sess, SELECTED_CUTOFF_MINUTES)
        tp_dist, sl_dist = getattr(row, "tp_dist_stage2"), getattr(row, "sl_dist_stage2")

        pnl, reason, exit_ts, audit = s3.simulate_exact_r_be(
            bars, ts, cutoff_ts, entry_price, sign, tp_dist, sl_dist,
            trigger_r=TRIGGER_R, lock_r=LOCK_R)

        record.update({
            "entry_time": ts, "exit_time": exit_ts, "exit_reason": reason,
            "pnl_pts": pnl, "r_multiple": pnl / sl_dist,
            "profit_lock_trigger_ts": audit.get("trigger_bar_ts"),
            "profit_lock_activation_ts": audit.get("trigger_activated_ts"),
        })
        ledger.append(record)
        position_open_until = exit_ts

    return pd.DataFrame(ledger), skip_counts
