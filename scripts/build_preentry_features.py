#!/usr/bin/env python3
"""Stage 0: causal pre-entry feature table for every qualifying signal in
outputs/stage0_signal_paths.csv.

Every feature is computed using only 1-minute bars that CLOSED strictly
before the signal's touch timestamp (a "completed" N-minute bucket ending
at or before touch_ts, using the same floor-to-bucket convention as the
verified engine's anchor calculation: `ts.floor(N) - N`). No feature ever
reads the touch bar itself or anything after it.

Usage:
    python3 scripts/build_preentry_features.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv \
        --signals outputs/stage0_signal_paths.csv \
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

from src.data_loader import load_1m_ohlcv, load_gvz_daily, prior_session_close  # noqa: E402

ET = "America/New_York"
RVOL_WINDOWS = (30, 60, 120)
RVOL_HISTORY_SESSIONS = (15, 20, 30)
RVOL_CLIP = (0.10, 10.0)  # fixed, documented a priori -- not tuned on profitability
ATR_BAR_MINUTES = (5, 15, 30, 60)
ATR_PERIOD = 14
EWMA_HALFLIVES = (30, 60, 120)
RANGE_WINDOWS = (15, 30, 60, 120)


def completed_bucket_range(bars, ts, minutes):
    """The [high-low] range of the most recent COMPLETED `minutes`-long
    bucket ending at/before `ts`, using floor-to-bucket - minutes."""
    bucket_start = ts.floor(f"{minutes}min") - pd.Timedelta(minutes=minutes)
    bucket_end = bucket_start + pd.Timedelta(minutes=minutes)
    window = bars.loc[bucket_start:bucket_end]
    window = window[window.index < bucket_end]
    if window.empty:
        return None
    return float(window["high"].max() - window["low"].min())


def session_date_of(ts):
    et = ts.tz_convert(ET)
    d = (et + pd.Timedelta(days=1)) if et.hour >= 18 else et
    return d.strftime("%Y-%m-%d")


def previous_session_range(session_ranges, ts):
    """Full prior *research* session's high-low range (18:00 ET->15:59 ET),
    looked up by the touch's own session date, using only sessions strictly
    before it."""
    sess = session_date_of(ts)
    prior = session_ranges[session_ranges.index < sess]
    if prior.empty:
        return None
    return float(prior.iloc[-1])


def build_atr_lookup(bars, bar_minutes, period=ATR_PERIOD):
    """Resample to `bar_minutes` OHLC bars, compute a `period`-length
    rolling ATR (true range mean) over COMPLETED bars only, indexed by the
    bar's own start timestamp (so `.asof` on a *completed* bucket start is
    always causal)."""
    o = bars["open"].resample(f"{bar_minutes}min", label="left", closed="left").first()
    h = bars["high"].resample(f"{bar_minutes}min", label="left", closed="left").max()
    l = bars["low"].resample(f"{bar_minutes}min", label="left", closed="left").min()
    c = bars["close"].resample(f"{bar_minutes}min", label="left", closed="left").last()
    ohlc = pd.DataFrame({"open": o, "high": h, "low": l, "close": c}).dropna()
    prev_close = ohlc["close"].shift(1)
    tr = pd.concat([
        ohlc["high"] - ohlc["low"],
        (ohlc["high"] - prev_close).abs(),
        (ohlc["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    # atr.loc[bucket_start] is the ATR *as of the close of that bucket* --
    # to use it causally for a touch, we must look up the bucket strictly
    # before the touch's own completed bucket, so shift index forward by
    # one bucket width conceptually: callers look up `bucket_start - bar_minutes`.
    return atr


def build_ewma_vol_lookup(bars, halflife_minutes):
    """EWMA stdev of 1-minute point returns (already in NQ point units),
    indexed by minute timestamp. Value at time t uses only returns up to
    and including bar t (so callers must look up the bar strictly before
    the touch bar)."""
    ret = bars["close"].diff()
    var = (ret ** 2).ewm(halflife=halflife_minutes, min_periods=halflife_minutes).mean()
    return np.sqrt(var)


def build_volume_bucket_table(bars, bucket_minutes):
    """Sum of volume per `bucket_minutes` bucket, plus the bucket's session
    date and its local time-of-day key (for the same-time-of-day RVOL
    lookup)."""
    vol = bars["volume"].resample(f"{bucket_minutes}min", label="left", closed="left").sum()
    df = vol.to_frame("volume")
    df["session_date"] = [session_date_of(ts) for ts in df.index]
    df["tod_key"] = [ts.tz_convert(ET).strftime("%H:%M") for ts in df.index]
    return df


def rvol_lookup(bucket_table, ts, bucket_minutes, n_sessions):
    bucket_start = ts.floor(f"{bucket_minutes}min") - pd.Timedelta(minutes=bucket_minutes)
    if bucket_start not in bucket_table.index:
        return None
    row = bucket_table.loc[bucket_start]
    current_vol = float(row["volume"])
    tod_key = row["tod_key"]
    this_session = row["session_date"]

    same_tod = bucket_table[bucket_table["tod_key"] == tod_key]
    prior_sessions = sorted(same_tod[same_tod["session_date"] < this_session]["session_date"].unique())
    if len(prior_sessions) < 1:
        return None
    use_sessions = set(prior_sessions[-n_sessions:])
    hist = same_tod[same_tod["session_date"].isin(use_sessions)]["volume"]
    if hist.empty or hist.median() == 0:
        return None
    raw = current_vol / float(hist.median())
    return float(np.clip(raw, *RVOL_CLIP))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    ap.add_argument("--signals", required=True)
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()

    out_dir = os.path.join(REPO_ROOT, args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)
    signals = pd.read_csv(args.signals)
    signals["touched_at"] = pd.to_datetime(signals["touched_at"], utc=True).dt.tz_convert(ET)

    # session-level research range (18:00 ET -> 15:59 ET), for prev-session-range feature
    sess_labels = pd.Series([session_date_of(ts) for ts in bars.index], index=bars.index)
    sess_hi = bars.groupby(sess_labels)["high"].max()
    sess_lo = bars.groupby(sess_labels)["low"].min()
    session_ranges = (sess_hi - sess_lo).sort_index()

    atr_lookups = {m: build_atr_lookup(bars, m) for m in ATR_BAR_MINUTES}
    ewma_lookups = {h: build_ewma_vol_lookup(bars, h) for h in EWMA_HALFLIVES}
    vol_buckets = {m: build_volume_bucket_table(bars, m) for m in RVOL_WINDOWS}

    records = []
    for _, row in signals.iterrows():
        ts = row["touched_at"]
        rec = {"level_id": row["level_id"], "touched_at": ts}

        for w in RANGE_WINDOWS:
            rec[f"range_{w}m"] = completed_bucket_range(bars, ts, w)
        rec["prev_session_range"] = previous_session_range(session_ranges, ts)

        for m in ATR_BAR_MINUTES:
            bucket_start = ts.floor(f"{m}min") - pd.Timedelta(minutes=m)
            lookup_bucket = bucket_start - pd.Timedelta(minutes=m)  # strictly-completed-before rule
            atr_series = atr_lookups[m]
            val = atr_series.asof(lookup_bucket) if lookup_bucket >= atr_series.index[0] else None
            rec[f"atr{ATR_PERIOD}_{m}m"] = float(val) if val is not None and not pd.isna(val) else None

        for h in EWMA_HALFLIVES:
            lookup_bar = ts.floor("min") - pd.Timedelta(minutes=1)
            series = ewma_lookups[h]
            val = series.asof(lookup_bar) if lookup_bar >= series.index[0] else None
            rec[f"ewma_vol_hl{h}m"] = float(val) if val is not None and not pd.isna(val) else None

        prior_vxn = prior_session_close(vxn, pd.Timestamp(row["session_date"] if "session_date" in row else ts).tz_localize(None))
        rec["vxn_prior_close"] = prior_vxn
        prior2 = vxn[vxn.index < pd.Timestamp(ts).tz_localize(None).normalize()]
        if len(prior2) >= 2:
            rec["vxn_prior_pct_change"] = float(prior2.iloc[-1] / prior2.iloc[-2] - 1.0)
        else:
            rec["vxn_prior_pct_change"] = None

        for w in RVOL_WINDOWS:
            for n in RVOL_HISTORY_SESSIONS:
                rec[f"rvol_{w}m_hist{n}"] = rvol_lookup(vol_buckets[w], ts, w, n)

        records.append(rec)

    feat_df = pd.DataFrame(records)
    feat_path = os.path.join(out_dir, "stage0_features.csv")
    feat_df.to_csv(feat_path, index=False)

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
        "n_signals": len(feat_df),
        "n_features": len(feat_df.columns) - 2,
        "feature_table_sha256": sha256_file(feat_path),
        "rvol_clip_bounds_a_priori": list(RVOL_CLIP),
        "reproduction_command": (
            f"python3 scripts/build_preentry_features.py --bars {args.bars} --vxn {args.vxn} "
            f"--signals {args.signals} --out-dir {args.out_dir}"
        ),
    }
    with open(os.path.join(out_dir, "stage0_feature_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
