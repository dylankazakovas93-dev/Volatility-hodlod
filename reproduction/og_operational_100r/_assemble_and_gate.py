"""Independent OG_OPERATIONAL_100R shadow assembly and rolling-PF gate.

Assembles three frozen component ledgers into chronological shadow sequence,
then applies the 100-trade 1.10 symmetric rolling-PF gate independently.
No calls to existing src/ assembly or gate functions.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from itertools import groupby

import numpy as np
import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

COMPONENT_LEDGERS = {
    "external_2013_2015": os.path.join(
        REPO_ROOT, "outputs/og_external_2013_2015", "operational_100r_trades.csv"
    ),
    "build_years": os.path.join(
        REPO_ROOT, "outputs/og_build_years", "final_buildoff_A_build_years_trades.csv"
    ),
    "validation": os.path.join(
        REPO_ROOT, "outputs/og_validation", "OG_OPERATIONAL_100R_validation_trades.csv"
    ),
}

# Frozen trigger log (for comparison)
FROZEN_TRIGGER_LOG = os.path.join(
    REPO_ROOT, "outputs/og_regime_killswitch",
    "operational_100r_trigger_log_rolling_pf_w100_t1.1_symmetric.csv",
)

# Outputs
OUT_DIR = os.path.join(REPO_ROOT, "artifacts", "og_operational_100r_fidelity")
os.makedirs(OUT_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Stage 5: Assemble shadow sequence
# ---------------------------------------------------------------------------

def load_component(path: str, source_label: str) -> pd.DataFrame:
    """Load a component ledger and add source + chronological index."""
    df = pd.read_csv(path)
    required = {"entry_time", "pnl", "cap", "exit_reason", "side", "entry_price",
                "exit_price", "exit_time", "anchor", "level", "level_id", "gap_through", "year"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{source_label}: missing columns {missing}")
    df["source"] = source_label
    df["entry_ts"] = pd.to_datetime(df["entry_time"], utc=True)
    return df


def assemble_shadow_sequence(ledger_paths: dict[str, str]) -> pd.DataFrame:
    """Load, validate, and concatenate component ledgers chronologically."""
    chunks = []
    for label, path in ledger_paths.items():
        df = load_component(path, label)
        n_before = len(df)
        # Drop any totally duplicate rows by entry_ts (seam protection)
        df = df.drop_duplicates(subset=["entry_ts"])
        n_after = len(df)
        if n_after < n_before:
            print(f"  {label}: dropped {n_before - n_after} duplicate seam rows")
        print(f"  {label}: {len(df)} rows ({df['entry_ts'].min()} to {df['entry_ts'].max()})")
        chunks.append(df)

    shadow = pd.concat(chunks, ignore_index=True)
    shadow = shadow.sort_values("entry_ts").reset_index(drop=True)
    shadow.index.name = "shadow_idx"
    return shadow


# ---------------------------------------------------------------------------
# Stage 6: Rolling PF gate
# ---------------------------------------------------------------------------

def rolling_pf_gate(
    pnl: np.ndarray,
    window: int = 100,
    threshold: float = 1.10,
) -> np.ndarray:
    """Symmetric rolling PF gate.

    Returns is_flat: True where the gate is OFF (trade skipped).

    Line-by-line logic:
    - First `window` rows: state = ON (not flat)
    - For row i (i >= window): compute PF on rows [i-window, i)
    - If currently ON and PF < threshold: switch OFF
    - If currently OFF and PF >= threshold: switch ON
    - Current row excluded from its own PF calculation
    """
    n = len(pnl)
    is_flat = np.zeros(n, dtype=bool)
    state_off = False

    for i in range(n):
        if i >= window:
            trailing = pnl[i - window:i]
            gains = trailing[trailing > 0].sum()
            losses = -trailing[trailing < 0].sum()
            pf = gains / losses if losses > 0 else float("inf")

            if state_off:
                if pf >= threshold:
                    state_off = False
            else:
                if pf < threshold:
                    state_off = True

        is_flat[i] = state_off

    return is_flat


def apply_gate(shadow: pd.DataFrame) -> pd.DataFrame:
    """Apply rolling PF gate to shadow sequence.

    Returns augmented DataFrame with all gate fields.
    """
    pnl = shadow["pnl"].values.astype(float)
    cap = shadow["cap"].values.astype(float)

    is_flat = rolling_pf_gate(pnl, window=100, threshold=1.10)

    result = shadow.copy()
    result["is_flat"] = is_flat
    result["effective_pnl"] = np.where(~is_flat, pnl, 0.0)
    result["effective_r"] = np.where(~is_flat, pnl / np.where(cap > 0, cap, 1.0), 0.0)

    # Compute rolling window edges
    window = 100
    result["window_start"] = np.nan
    result["window_end"] = np.nan
    result["window_gains"] = np.nan
    result["window_losses"] = np.nan
    result["window_pf"] = np.nan

    for i in range(len(result)):
        if i >= window:
            start = i - window
            end = i - 1
            trailing = pnl[start:i]
            gains = trailing[trailing > 0].sum()
            losses = -trailing[trailing < 0].sum()
            pf = gains / losses if losses > 0 else float("inf")
            result.loc[result.index[i], "window_start"] = start
            result.loc[result.index[i], "window_end"] = end
            result.loc[result.index[i], "window_gains"] = gains
            result.loc[result.index[i], "window_losses"] = losses
            result.loc[result.index[i], "window_pf"] = pf

    return result


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------

def compute_metrics(df: pd.DataFrame) -> dict:
    """Compute benchmark metrics from gated shadow."""
    active = df[df["is_flat"] == False]
    pnl = active["pnl"].values.astype(float)
    cap = active["cap"].values.astype(float)

    gains = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    pf = gains / losses if losses > 0 else float("inf")

    r_vals = pnl / np.where(cap > 0, cap, 1.0)
    r_total = r_vals.sum()
    r_gains = r_vals[r_vals > 0].sum()
    r_losses = -r_vals[r_vals < 0].sum()
    r_pf = r_gains / r_losses if r_losses > 0 else float("inf")

    cum_pnl = np.cumsum(pnl)
    peak_pnl = np.maximum.accumulate(cum_pnl)
    dd_pnl = cum_pnl - peak_pnl
    mdd_pts = dd_pnl.min()

    cum_r = np.cumsum(r_vals)
    peak_r = np.maximum.accumulate(cum_r)
    dd_r = cum_r - peak_r
    mdd_r = dd_r.min()

    flat_mask = df["is_flat"].values
    flat_count = int(flat_mask.sum())
    flat_run_seq = [list(g) for k, g in groupby(flat_mask) if k]
    flat_runs = len(flat_run_seq)

    return {
        "n_shadow": len(df),
        "n_active": int((~flat_mask).sum()),
        "n_flat": flat_count,
        "n_flat_runs": flat_runs,
        "net_pts": round(float(pnl.sum()), 3),
        "points_pf": round(pf, 6),
        "total_r": round(r_total, 4),
        "r_pf": round(r_pf, 6),
        "mdd_pts": round(mdd_pts, 4),
        "mdd_r": round(mdd_r, 4),
    }


# ---------------------------------------------------------------------------
# Reconciliation helpers
# ---------------------------------------------------------------------------

def reconcile_with_frozen(df_actual: pd.DataFrame, df_frozen: pd.DataFrame) -> dict:
    """Row-by-row comparison of is_flat decisions."""
    # Normalize timestamps
    actual_ts = pd.to_datetime(df_actual["entry_ts"] if "entry_ts" in df_actual.columns else df_actual["entry_time"], utc=True)
    frozen_ts = pd.to_datetime(df_frozen["entry_time"], utc=True)

    # Build lookup
    frozen_flat = dict(zip(frozen_ts.astype(str), df_frozen["is_flat"]))

    mismatches = 0
    match_details = {"is_flat_match": True, "total": 0, "mismatches": 0}

    for i, (ts, actual_flat) in enumerate(zip(actual_ts, df_actual["is_flat"])):
        ts_str = str(ts)
        expected = frozen_flat.get(ts_str)
        if expected is None:
            continue  # timestamp not in frozen (shouldn't happen)
        if bool(actual_flat) != bool(expected):
            mismatches += 1
            if mismatches <= 5:
                match_details.setdefault("first_mismatches", []).append({
                    "row": i, "ts": ts_str,
                    "actual_flat": bool(actual_flat),
                    "expected_flat": bool(expected),
                })

    match_details["total"] = len(df_actual)
    match_details["mismatches"] = mismatches
    match_details["is_flat_match"] = mismatches == 0
    return match_details


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("OG_OPERATIONAL_100R: Independent shadow assembly + rolling PF gate")
    print("=" * 60)

    # Stage 5: Assemble
    print("\n--- Stage 5: Assemble shadow sequence ---")
    shadow = assemble_shadow_sequence(COMPONENT_LEDGERS)
    print(f"Total shadow rows: {len(shadow)}")

    years = sorted(shadow["entry_ts"].dt.year.unique())
    print(f"Years: {years}")
    absent = [y for y in ["2016", "2017"] if int(y) not in years]
    print(f"Absent years (expected): {absent}")

    # Save raw shadow
    shadow.to_csv(os.path.join(OUT_DIR, "assembled_shadow.csv"), index=True)
    print(f"Saved: {OUT_DIR}/assembled_shadow.csv")

    # Stage 6: Apply rolling PF gate
    print("\n--- Stage 6: Apply rolling PF gate (w=100, t=1.10, symmetric) ---")
    gated = apply_gate(shadow)

    # Save gated output
    gated_out = gated.drop(columns=["entry_ts"])
    gated_out.to_csv(os.path.join(OUT_DIR, "gated_benchmark.csv"), index=True)
    print(f"Saved: {OUT_DIR}/gated_benchmark.csv")

    # Compute metrics
    metrics = compute_metrics(gated)
    print(f"\nIndependent benchmark metrics:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    # Load frozen trigger log for comparison
    if os.path.exists(FROZEN_TRIGGER_LOG):
        frozen_trig = pd.read_csv(FROZEN_TRIGGER_LOG)
        frozen_flat_dict = dict(zip(
            pd.to_datetime(frozen_trig["entry_time"], utc=True).astype(str),
            frozen_trig["is_flat"],
        ))

        # Reconcile
        rec = reconcile_with_frozen(gated, frozen_trig)
        print(f"\nRow-by-row reconciliation vs frozen:")
        print(f"  Total rows: {rec['total']}")
        print(f"  is_flat mismatches: {rec['mismatches']}")
        print(f"  All match: {rec['is_flat_match']}")
        if not rec["is_flat_match"] and "first_mismatches" in rec:
            print(f"  First mismatches:")
            for m in rec["first_mismatches"]:
                print(f"    Row {m['row']}: {m['ts']} actual={m['actual_flat']} expected={m['expected_flat']}")

        # Compare metrics
        frozen_active = frozen_trig[frozen_trig["is_flat"] == False]
        ts_list = pd.to_datetime(frozen_trig["entry_time"], utc=True).astype(str)
        shadow_dict = dict(zip(
            pd.to_datetime(gated["entry_ts"] if "entry_ts" in gated.columns else gated["entry_time"], utc=True).astype(str),
            gated.index,
        ))
        active_idx = [shadow_dict[ts] for ts in ts_list if not frozen_flat_dict[ts]]
        if active_idx:
            active_pnl = shadow.loc[active_idx, "pnl"].values.astype(float)
            gains = active_pnl[active_pnl > 0].sum()
            losses = -active_pnl[active_pnl < 0].sum()
            frozen_pf = gains / losses if losses > 0 else float("inf")
            print(f"\n  Frozen active PF: {frozen_pf:.6f}")
            print(f"  Independent active PF: {metrics['points_pf']}")

    # Hashes
    print(f"\n--- Artifact hashes ---")
    for fname in ["assembled_shadow.csv", "gated_benchmark.csv"]:
        fpath = os.path.join(OUT_DIR, fname)
        with open(fpath, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest()
            print(f"  {fname}: {h}")

    print(f"\nDone. Outputs in {OUT_DIR}/")
    return gated, metrics


if __name__ == "__main__":
    main()
