#!/usr/bin/env python3
"""Stage 1 correction: session-anchored RVOL (section 6C).

The Stage 0 `rvol_120m` had a ~65% missing rate because its buckets were
anchored to fixed wall-clock times (00:00, 02:00, ...) instead of the
research session's own 18:00 ET start -- a bucket-alignment defect, not
genuine data unavailability.

This script rebuilds RVOL_30 / RVOL_60 / RVOL_120 using buckets that are
non-overlapping and anchored at each research session's own 18:00 ET start
(bucket 0 = [18:00, 18:00+W), bucket 1 = [18:00+W, 18:00+2W), ...). For a
signal at time t, only the most recently COMPLETED bucket strictly before
t is used, and the historical comparison set is the same bucket *index*
from the N most recent, strictly-prior, completed research sessions.

Usage:
    python3 scripts/build_session_anchored_rvol.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --signals outputs/stage1_corrected_excursions.parquet \
        --out-dir outputs
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv  # noqa: E402
from scripts.build_signal_paths import research_session_date  # noqa: E402

ET = "America/New_York"
RVOL_WINDOWS = (30, 60, 120)
RVOL_HISTORY_SESSIONS = (15, 20, 30)
RVOL_CLIP = (0.10, 10.0)


def session_start_ts(session_date_str):
    return pd.Timestamp(f"{session_date_str} 18:00", tz=ET) - pd.Timedelta(days=1)


def vectorized_session_dates_and_starts(index_et):
    """Fully vectorized equivalent of research_session_date(): a bar at ET
    local hour >= 18 belongs to the *following* calendar day's session."""
    hours = index_et.hour
    normalized = index_et.normalize()
    session_day = pd.DatetimeIndex(np.where(hours >= 18, normalized + pd.Timedelta(days=1), normalized))
    session_dates = np.array(session_day.strftime("%Y-%m-%d"))
    session_start = session_day - pd.Timedelta(hours=6)  # 18:00 the day before 00:00 of session_day
    return session_dates, session_start


def build_bucket_table(bars, minutes, index_et, session_dates, session_start):
    """Per-bar bucket assignment: (session_date, bucket_index), then summed
    volume per (session_date, bucket_index)."""
    minutes_since_start = ((index_et.tz_localize(None) - session_start.tz_localize(None))
                            / pd.Timedelta(minutes=1)).astype(int)
    bucket_idx = minutes_since_start // minutes

    df = pd.DataFrame({
        "session_date": session_dates,
        "bucket_index": bucket_idx,
        "volume": bars["volume"].to_numpy(),
    })
    table = df.groupby(["session_date", "bucket_index"])["volume"].sum().reset_index()
    return table


def rvol_lookup(table_indexed, session_dates_sorted, session_date, bucket_index, n_sessions):
    pos = np.searchsorted(session_dates_sorted, session_date)
    if pos == 0:
        return None, 0
    prior_dates = session_dates_sorted[max(0, pos - n_sessions):pos]
    key_current = (session_date, bucket_index)
    if key_current not in table_indexed.index:
        return None, 0
    current_vol = float(table_indexed.loc[key_current, "volume"])

    hist_vals = []
    for d in prior_dates:
        k = (d, bucket_index)
        if k in table_indexed.index:
            hist_vals.append(float(table_indexed.loc[k, "volume"]))
    if not hist_vals:
        return None, 0
    med = float(np.median(hist_vals))
    if med <= 0:
        return None, len(hist_vals)
    return float(np.clip(current_vol / med, *RVOL_CLIP)), len(hist_vals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--signals", required=True)
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    bars = load_1m_ohlcv(args.bars)
    signals = pd.read_parquet(args.signals)
    signals["touched_at"] = pd.to_datetime(signals["touched_at"], utc=True).dt.tz_convert(ET)

    index_et = bars.index.tz_convert(ET)
    session_dates_arr, session_start_arr = vectorized_session_dates_and_starts(index_et)

    bucket_tables = {}
    for w in RVOL_WINDOWS:
        t = build_bucket_table(bars, w, index_et, session_dates_arr, session_start_arr)
        t = t.set_index(["session_date", "bucket_index"])
        bucket_tables[w] = t

    all_session_dates = np.array(sorted(pd.unique(session_dates_arr)))

    records = []
    for _, row in signals.iterrows():
        ts = row["touched_at"]
        sess = row["session_date"]
        start = session_start_ts(sess)
        minutes_elapsed = int((ts.tz_localize(None) - start.tz_localize(None)) / pd.Timedelta(minutes=1))

        rec = {"level_id": row["level_id"], "touched_at": ts}
        for w in RVOL_WINDOWS:
            cur_idx = minutes_elapsed // w
            completed_idx = cur_idx - 1
            if completed_idx < 0:
                for n in RVOL_HISTORY_SESSIONS:
                    rec[f"rvol_{w}m_hist{n}_session_anchored"] = None
                continue
            for n in RVOL_HISTORY_SESSIONS:
                val, n_hist = rvol_lookup(bucket_tables[w], all_session_dates, sess, completed_idx, n)
                rec[f"rvol_{w}m_hist{n}_session_anchored"] = val
        records.append(rec)

    rvol_df = pd.DataFrame(records)
    out_path = os.path.join(out_dir, "stage1_session_anchored_rvol.parquet")
    rvol_df.to_parquet(out_path, index=False)

    missing_rates = {
        c: float(rvol_df[c].isna().mean())
        for c in rvol_df.columns if c.startswith("rvol_")
    }

    def sha256_file(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def git_sha():
        try:
            return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
        except Exception:
            return None

    summary = {
        "research_commit": git_sha(),
        "n_signals": len(rvol_df),
        "missing_rates": missing_rates,
        "output_parquet_sha256": sha256_file(out_path),
        "reproduction_command": (
            f"python3 scripts/build_session_anchored_rvol.py --bars {args.bars} "
            f"--signals {args.signals} --out-dir {args.out_dir}"
        ),
    }
    with open(os.path.join(out_dir, "stage1_session_anchored_rvol_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
