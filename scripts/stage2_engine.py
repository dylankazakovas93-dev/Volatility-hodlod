"""Stage 2 shared engine: frozen F2 formula fit on development years only,
time-window block assignment, and the SAL-aware one-position replay.

Development years (per Stage 2 spec): 2018, 2020, 2023, partial 2026.
Reserved (never inspected/reported): 2019, 2021, 2022, 2024, 2025.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.fit_stage1_excursion_formulas import design_matrix, fit_quantile, predict, FEATURE_SETS
from scripts.stage1_engine import round_tp, round_sl, first_passage_exit
from scripts.build_signal_paths import research_session_date
from scripts.build_session_anchored_rvol import session_start_ts

DEV_YEARS = [2018, 2020, 2023, 2026]
RESERVED_YEARS = [2019, 2021, 2022, 2024, 2025]
FEATURE_COLS = FEATURE_SETS["F2"]  # range_30m, prev_session_range, rvol60_primary
ET = "America/New_York"

# Session-relative minute boundaries for blocks A-H (18:00 ET session start = 0)
BLOCKS = {
    "A": (0, 360),      # 18:00-00:00
    "B": (360, 540),    # 00:00-03:00
    "C": (540, 660),    # 03:00-05:00
    "D": (660, 840),    # 05:00-08:00
    "E": (840, 930),    # 08:00-09:30
    "F": (930, 1020),   # 09:30-11:00
    "G": (1020, 1260),  # 11:00-15:00
    "H": (1260, 1319),  # 15:00-15:59 (15:59 bar itself excluded elsewhere)
}
BLOCK_ORDER = ["A", "B", "C", "D", "E", "F", "G", "H"]


def fit_frozen_formula(master, mfe_q=0.50, mae_q=0.50, dev_years=DEV_YEARS):
    """Fits once on the given development years only, returns frozen
    (tp_intercept, tp_coefs, sl_intercept, sl_coefs, mfe_clip, mae_clip, feature_names)."""
    train_df = master[master["year"].isin(dev_years)].dropna(
        subset=FEATURE_COLS + ["conventional_mfe_pts", "conventional_mae_pts"])
    X_train, fnames = design_matrix(train_df, FEATURE_COLS)
    y_mfe = np.log1p(train_df["conventional_mfe_pts"].to_numpy())
    y_mae = np.log1p(train_df["conventional_mae_pts"].to_numpy())
    tp_i, tp_c = fit_quantile(X_train, y_mfe, mfe_q, fnames)
    sl_i, sl_c = fit_quantile(X_train, y_mae, mae_q, fnames)
    mfe_lo, mfe_hi = np.percentile(train_df["conventional_mfe_pts"], [5, 95])
    mae_lo, mae_hi = np.percentile(train_df["conventional_mae_pts"], [5, 95])
    return {
        "tp_intercept": tp_i, "tp_coefs": tp_c, "sl_intercept": sl_i, "sl_coefs": sl_c,
        "mfe_clip": (mfe_lo, mfe_hi), "mae_clip": (mae_lo, mae_hi), "feature_names": fnames,
        "n_train": len(train_df),
    }


def apply_frozen_formula(master, frozen):
    full_df = master.dropna(subset=FEATURE_COLS).copy()
    X_full, _ = design_matrix(full_df, FEATURE_COLS)
    pred_mfe = np.clip(np.expm1(predict(X_full, frozen["feature_names"], frozen["tp_intercept"], frozen["tp_coefs"])),
                        *frozen["mfe_clip"])
    pred_mae = np.clip(np.expm1(predict(X_full, frozen["feature_names"], frozen["sl_intercept"], frozen["sl_coefs"])),
                        *frozen["mae_clip"])
    full_df["tp_dist_stage2"] = round_tp(pd.Series(pred_mfe, index=full_df.index))
    full_df["sl_dist_stage2"] = round_sl(pd.Series(pred_mae, index=full_df.index))
    return full_df


def minutes_since_session_start(ts, session_date):
    start = session_start_ts(session_date)
    return int((ts.tz_convert(ET).tz_localize(None) - start.tz_localize(None)) / pd.Timedelta(minutes=1))


def block_of(minutes_elapsed):
    for name, (lo, hi) in BLOCKS.items():
        if lo <= minutes_elapsed < hi:
            return name
    return None


def window_allows(blocks_allowed, minutes_elapsed):
    b = block_of(minutes_elapsed)
    return b is not None and b in blocks_allowed


def all_contiguous_windows():
    """36 contiguous adjacent-block windows (all subsequences of length 1-8)."""
    windows = []
    n = len(BLOCK_ORDER)
    for length in range(1, n + 1):
        for start in range(0, n - length + 1):
            blocks = tuple(BLOCK_ORDER[start:start + length])
            windows.append(("contig", blocks))
    return windows


def all_minus_one_windows():
    return [("minus1", tuple(b for b in BLOCK_ORDER if b != excl)) for excl in BLOCK_ORDER]


def all_minus_two_adjacent_windows():
    out = []
    for i in range(len(BLOCK_ORDER) - 1):
        excl = {BLOCK_ORDER[i], BLOCK_ORDER[i + 1]}
        out.append(("minus2adj", tuple(b for b in BLOCK_ORDER if b not in excl)))
    return out


def all_test_windows():
    return all_contiguous_windows() + all_minus_one_windows() + all_minus_two_adjacent_windows()


def window_label(kind, blocks):
    return f"{kind}:{'-'.join(blocks)}"


def run_stage2_replay(bars, master_with_dist, allowed_blocks=None, sal_enabled=False):
    """Chronological one-position replay with optional time-window
    restriction and optional SAL. Returns (executed_df, skip_counts, sal_audit)."""
    df = master_with_dist.dropna(subset=["tp_dist_stage2", "sl_dist_stage2"]).sort_values("touched_at")

    executed = []
    sal_audit = []
    skip_counts = {"blocked_reserved_year": 0, "blocked_window": 0, "position_open": 0,
                   "same_bar_reentry": 0, "SAL": 0}

    position_open_until = None
    sal_session = None
    sal_armed = False

    for row in df.itertuples(index=False):
        ts = getattr(row, "touched_at")
        sess = getattr(row, "session_date")

        if sess != sal_session:
            sal_session = sess
            sal_armed = False

        # Reserved years (2019, 2021, 2022, 2024, 2025) are never entered --
        # their strategy results must not be calculated at all, only their
        # bars may feed causal lagged features (already handled upstream).
        if getattr(row, "year") not in DEV_YEARS:
            skip_counts["blocked_reserved_year"] += 1
            continue

        minutes_elapsed = minutes_since_session_start(ts, sess)
        if allowed_blocks is not None and not window_allows(allowed_blocks, minutes_elapsed):
            skip_counts["blocked_window"] += 1
            continue

        if position_open_until is not None and ts < position_open_until:
            skip_counts["position_open"] += 1
            continue
        if position_open_until is not None and ts == position_open_until:
            skip_counts["same_bar_reentry"] += 1
            continue

        if sal_enabled and sal_armed:
            skip_counts["SAL"] += 1
            sal_audit.append({"session_date": sess, "touched_at": ts, "event": "blocked_by_SAL"})
            continue

        side = getattr(row, "side")
        sign = 1.0 if side == "lower" else -1.0
        entry_price = getattr(row, "entry_price")
        cutoff_ts = getattr(row, "forced_liquidation_ts")
        tp_dist = getattr(row, "tp_dist_stage2")
        sl_dist = getattr(row, "sl_dist_stage2")

        pnl, reason, exit_ts = first_passage_exit(bars, ts, cutoff_ts, entry_price, sign, tp_dist, sl_dist)

        executed.append({
            "level_id": getattr(row, "level_id"), "session_date": sess, "year": getattr(row, "year"),
            "side": side, "entry_time": ts, "exit_time": exit_ts,
            "entry_price": entry_price, "tp_dist": tp_dist, "sl_dist": sl_dist,
            "pnl_pts": pnl, "r_multiple": pnl / sl_dist, "exit_reason": reason,
        })
        position_open_until = exit_ts

        if sal_enabled and pnl < 0:
            sal_armed = True
            sal_audit.append({"session_date": sess, "touched_at": ts, "exit_time": exit_ts,
                               "pnl": pnl, "event": "SAL_activated"})

    return pd.DataFrame(executed), skip_counts, pd.DataFrame(sal_audit)
