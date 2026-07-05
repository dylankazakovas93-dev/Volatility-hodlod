#!/usr/bin/env python3
"""Stage 0: builds the independent all-hours signal-path dataset.

Reuses the verified, unchanged level-generation and physical-first-touch
code (src.level_generation.generate_levels, src.strict_engine.physical_touches)
-- Stage 0 does not re-derive or alter signal semantics, only what happens
to a touch once it exists.

Research session: 18:00 ET through 15:59 ET the following day. A physical
first touch becomes a Stage 0 "qualifying signal" iff:
  - it is the side's physical first touch (already guaranteed upstream);
  - it is not the level's creation timestamp (already excluded upstream);
  - it is before the level's excluded expiry timestamp (already excluded upstream);
  - its local ET time is NOT in the undefined 16:00:00-17:59:59 gap between
    the previous session's 15:59 forced-liquidation bar and the next
    session's 18:00 open -- there is no session active in that window, so a
    touch inside it has no defined forced-liquidation timestamp and is
    excluded, not silently assigned to either neighboring session;
  - it is not on the 15:59 ET bar itself (no new position may enter on the
    forced-liquidation bar);
  - at least one later 1-minute bar exists before forced liquidation (a
    non-empty post-touch path).

Forced liquidation timestamp for a qualifying touch at local time t:
  - if t < 15:59 ET: same calendar day's 15:59 ET bar;
  - if t >= 18:00 ET: the *next* calendar day's 15:59 ET bar.
(The 16:00-18:00 gap is excluded above, so these two cases are exhaustive
and unambiguous for every touch that reaches this stage.)

Usage:
    python3 scripts/build_signal_paths.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv \
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

from src.data_loader import load_1m_ohlcv, load_gvz_daily  # noqa: E402
from src.level_generation import NQ_PARAMS, generate_levels  # noqa: E402
from src.strict_engine import physical_touches, LINE_DAYS  # noqa: E402

ET = "America/New_York"
SNAPSHOT_MINUTES = [5, 15, 30, 45, 60, 90, 120, 180]


def gap_or_liquidation_bar(ts):
    """Classify a touch timestamp's ET local time.

    Returns one of: 'active' (valid session), 'gap' (16:00-17:59:59, no
    session defined), 'liquidation_bar' (exactly the 15:59 bar).
    """
    et = ts.tz_convert(ET)
    m = et.hour * 60 + et.minute
    if m == 15 * 60 + 59:
        return "liquidation_bar"
    if 16 * 60 <= m < 18 * 60:
        return "gap"
    return "active"


def forced_liquidation_ts(ts):
    et = ts.tz_convert(ET)
    m = et.hour * 60 + et.minute
    day = et.strftime("%Y-%m-%d")
    same_day_cutoff = pd.Timestamp(f"{day} 15:59", tz=ET)
    if m < 15 * 60 + 59:
        return same_day_cutoff.tz_convert(ts.tz)
    nxt = (et.normalize() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return pd.Timestamp(f"{nxt} 15:59", tz=ET).tz_convert(ts.tz)


def research_session_date(ts):
    """Session label: 18:00 ET rolls into the following calendar day,
    mirroring the verified engine's 19:00 convention but at the new
    18:00 boundary."""
    et = ts.tz_convert(ET)
    d = (et + pd.Timedelta(days=1)) if et.hour >= 18 else et
    return d.strftime("%Y-%m-%d")


def build_path_record(bars, event, cutoff_ts):
    touch_ts = event["touched_at"]
    side = event["side"]
    level = event["level"]
    sign = -1.0 if side == "upper" else 1.0  # short=upper(-1 favors down move), long=lower(+1 favors up move)

    touch_row = bars.loc[touch_ts]
    clean = bool(touch_row["low"] <= level <= touch_row["high"])
    entry_price = level if clean else float(touch_row["close"])

    path = bars.loc[touch_ts:cutoff_ts].iloc[1:]
    if path.empty:
        return None

    ts_idx = path.index
    highs = path["high"].to_numpy()
    lows = path["low"].to_numpy()
    closes = path["close"].to_numpy()

    # favourable/adverse excursion in points, signed by trade direction
    if sign > 0:  # long
        fav = highs - entry_price
        adv = lows - entry_price  # negative when adverse
    else:  # short
        fav = entry_price - lows
        adv = entry_price - highs  # negative when adverse

    mfe_idx = int(np.argmax(fav))
    mfe = float(fav[mfe_idx])
    mfe_ts = ts_idx[mfe_idx]

    mae_idx = int(np.argmin(adv))
    mae = float(adv[mae_idx])
    mae_ts = ts_idx[mae_idx]

    mae_before_mfe = mae_ts <= mfe_ts
    mfe_before_mae = mfe_ts <= mae_ts

    cutoff_pnl = float(closes[-1] - entry_price) if sign > 0 else float(entry_price - closes[-1])

    minutes_elapsed = np.arange(1, len(path) + 1)

    def snapshot_at(minutes):
        pos = minutes - 1
        if pos >= len(path):
            pos = len(path) - 1
        fav_snap = float(np.max(fav[: pos + 1]))
        adv_snap = float(np.min(adv[: pos + 1]))
        mtm = float((closes[pos] - entry_price) if sign > 0 else (entry_price - closes[pos]))
        return fav_snap, adv_snap, mtm

    snapshots = {}
    for m in SNAPSHOT_MINUTES:
        f, a, mtm = snapshot_at(m)
        snapshots[f"mfe_{m}m"] = f
        snapshots[f"mae_{m}m"] = a
        snapshots[f"mtm_{m}m"] = mtm

    record = {
        "level_id": event["level_id"],
        "level_idx": event["level_idx"],
        "created_at": event["created_at"],
        "expiry_at": event["expiry_at"],
        "touched_at": touch_ts,
        "session_date": research_session_date(touch_ts),
        "year": pd.Timestamp(research_session_date(touch_ts)).year,
        "side": side,
        "contract": bars.loc[touch_ts, "contract"] if "contract" in bars.columns else None,
        "level": level,
        "entry_price": entry_price,
        "entry_fill_type": "clean" if clean else "gap_through_close",
        "forced_liquidation_ts": cutoff_ts,
        "mfe": mfe, "mfe_ts": mfe_ts, "minutes_to_mfe": mfe_idx + 1,
        "mae": mae, "mae_ts": mae_ts, "minutes_to_mae": mae_idx + 1,
        "mae_before_mfe": bool(mae_before_mfe), "mfe_before_mae": bool(mfe_before_mae),
        "cutoff_pnl": cutoff_pnl,
        "path_len_minutes": int(len(path)),
    }
    record.update(snapshots)
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()

    out_dir = os.path.join(REPO_ROOT, args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    bars = load_1m_ohlcv(args.bars)
    contract_col = None
    raw_bars_full = pd.read_csv(args.bars)
    if "contract" in raw_bars_full.columns:
        bars = bars.copy()
        idx = pd.to_datetime(raw_bars_full["timestamp"], utc=True).dt.tz_convert("America/New_York")
        contract_series = pd.Series(raw_bars_full["contract"].to_numpy(), index=idx).sort_index()
        bars["contract"] = contract_series.reindex(bars.index)

    vxn = load_gvz_daily(args.vxn)
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    lvls = list(levels.itertuples(index=False))
    events = physical_touches(bars, lvls)

    events_df = pd.DataFrame(events)
    events_df.to_csv(os.path.join(out_dir, "stage0_physical_touches.csv"), index=False)

    touched = [e for e in events if e["touched_at"] is not None]
    n_total_sides = len(events)
    n_touched = len(touched)

    classification = []
    qualifying = []
    for e in touched:
        cls = gap_or_liquidation_bar(e["touched_at"])
        if cls != "active":
            classification.append({"level_id": e["level_id"], "touched_at": e["touched_at"], "reason": cls})
            continue
        cutoff_ts = forced_liquidation_ts(e["touched_at"])
        rec = build_path_record(bars, e, cutoff_ts)
        if rec is None:
            classification.append({"level_id": e["level_id"], "touched_at": e["touched_at"], "reason": "no_valid_path"})
            continue
        qualifying.append(rec)

    signal_paths = pd.DataFrame(qualifying)
    signal_paths.to_csv(os.path.join(out_dir, "stage0_signal_paths.csv"), index=False)

    excluded = pd.DataFrame(classification)
    excluded.to_csv(os.path.join(out_dir, "stage0_excluded_touches.csv"), index=False)

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
        "data_hashes": {"bars": sha256_file(args.bars), "vxn": sha256_file(args.vxn)},
        "total_level_sides": n_total_sides,
        "physical_touches": n_touched,
        "verified_baseline_physical_touches": 3486,
        "reconciled": n_touched == 3486,
        "qualifying_signal_paths": len(signal_paths),
        "excluded_gap": int((excluded["reason"] == "gap").sum()) if len(excluded) else 0,
        "excluded_liquidation_bar": int((excluded["reason"] == "liquidation_bar").sum()) if len(excluded) else 0,
        "excluded_no_valid_path": int((excluded["reason"] == "no_valid_path").sum()) if len(excluded) else 0,
        "reproduction_command": (
            f"python3 scripts/build_signal_paths.py --bars {args.bars} --vxn {args.vxn} --out-dir {args.out_dir}"
        ),
    }
    with open(os.path.join(out_dir, "stage0_signal_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
