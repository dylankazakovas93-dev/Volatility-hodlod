"""Primary strict one-position, time-aware-SAL NQ engine.

Consolidated, with zero logic changes, from the verified
scripts/reconcile_strict_one_position.py plus the session/window/anchor
helpers it depended on from scripts/build_be60_enriched.py and the
1,841-candidate gate from scripts/nq_cond_be45.py. This is the single
canonical file for "how the primary engine works" in this handoff.

Usage:
    python3 -m src.strict_engine \
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
from collections import defaultdict

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv, load_gvz_daily, prior_session_close  # noqa: E402
from src.level_generation import NQ_PARAMS, generate_levels  # noqa: E402
from src.metrics import profit_factor, max_drawdown, max_loss_streak  # noqa: E402

LINE_DAYS = 20
SL_CAP = 200.0
BE_BARS = 45
ET = "America/New_York"


# ------------------------------------------------------- session / window helpers

def entry_allowed(ts):
    et = ts.tz_convert(ET)
    m = et.hour * 60 + et.minute
    return not (11 * 60 <= m < 15 * 60)


def session_date(ts):
    et = ts.tz_convert(ET)
    return ((et + pd.Timedelta(days=1)) if et.hour >= 19 else et).strftime("%Y-%m-%d")


def session_cutoff(touched_at):
    et = touched_at.tz_convert(ET)
    d = et.strftime("%Y-%m-%d")
    co = pd.Timestamp(f"{d} 15:00", tz=ET)
    re = pd.Timestamp(f"{d} 19:00", tz=ET)
    if et < co:
        return co.tz_convert(touched_at.tz)
    if et >= re:
        nxt = et.normalize() + pd.Timedelta(days=1)
        return pd.Timestamp(f"{nxt.date()} 15:00", tz=ET).tz_convert(touched_at.tz)
    return None


def bar_ranges(bars):
    r = bars.resample("60min", label="left", closed="left").agg({"high": "max", "low": "min"}).dropna()
    return r["high"] - r["low"]


def prev_completed_range(ranges, ts):
    prev = ts.floor("60min") - pd.Timedelta(minutes=60)
    v = ranges.get(prev)
    return float(v) if v is not None and not pd.isna(v) and v > 0 else None


# ------------------------------------------------------------- touch detection

def first_touch(bars: pd.DataFrame, level: float):
    """Level falls inside the bar's range, or close crosses it intrabar-to-intrabar."""
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev_close = close.shift(1)
    touched = (
        ((high >= level) & (low <= level))
        | ((close >= level) & (prev_close < level))
        | ((close <= level) & (prev_close > level))
    )
    hits = bars.index[touched]
    return hits[0] if len(hits) else None


# --------------------------------------------------- eligible-candidate gate (1,841)

def simulate_cond_be(path, entry, sign, cap, be_bars=BE_BARS):
    """1:1 TP/SL with conditional BE arming at `be_bars`. Returns (pnl, exit_type)."""
    target = entry + sign * cap
    orig_stop = entry - sign * cap
    hi, lo, op, cl = (path["high"].values, path["low"].values,
                      path["open"].values, path["close"].values)
    armed = checked = False
    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        if i < be_bars:
            stop = orig_stop
        else:
            if not checked:
                checked = True
                o = float(op[i])
                armed = (o >= entry) if sign > 0 else (o <= entry)
            stop = entry if armed else orig_stop
        if sign > 0:
            if l <= stop:
                return sign * (stop - entry), ("BE" if (i >= be_bars and armed) else "SL")
            if h >= target:
                return cap, "TP"
        else:
            if h >= stop:
                return sign * (stop - entry), ("BE" if (i >= be_bars and armed) else "SL")
            if l <= target:
                return cap, "TP"
    return sign * (float(cl[-1]) - entry), "cutoff"


def build_eligible_candidates(bars, vxn):
    """Reproduces the 1,841-row eligible-candidate gate: first touch exists,
    valid entry time, prior completed 1h range exists, valid session cutoff,
    nonempty post-entry path. This population is the static gate all
    downstream engines (SAL-only and strict single-position alike) share."""
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = bar_ranges(bars)
    lvls = list(levels.itertuples(index=False))
    records = []
    for i, lv in enumerate(lvls):
        expiry = lvls[i + LINE_DAYS].created_at if i + LINE_DAYS < len(lvls) else bars.index[-1]
        search = bars.loc[lv.created_at: expiry]
        for side, col in (("upper", lv.upper_level), ("lower", lv.lower_level)):
            lvl = float(col)
            ft = first_touch(search, lvl)
            if ft is None or not entry_allowed(ft):
                continue
            anchor = prev_completed_range(ranges, ft)
            if anchor is None:
                continue
            co = session_cutoff(ft)
            if co is None:
                continue
            path = bars.loc[ft: co].iloc[1:]
            if path.empty:
                continue
            cap = min(1.5 * anchor, SL_CAP)
            sign = -1.0 if side == "upper" else 1.0
            pnl, ex = simulate_cond_be(path, lvl, sign, cap)
            records.append({
                "sess_date": session_date(ft), "year": pd.Timestamp(session_date(ft)).year,
                "side": side, "touched_at": ft, "level": lvl,
                "anchor": anchor, "cap": cap, "pnl": pnl, "exit": ex,
            })
    return pd.DataFrame(records)


# ------------------------------------------------------------ physical touch

def physical_touches(bars, lvls, creation_bar_exclude=True, expiry_exclude=True):
    """One row per level-side. touched_at is None if never physically touched
    inside its live window under the frozen edge-case rules."""
    n = len(lvls)
    events = []
    for i, lv in enumerate(lvls):
        expiry = lvls[i + LINE_DAYS].created_at if i + LINE_DAYS < n else bars.index[-1]
        window = bars.loc[lv.created_at: expiry]
        if creation_bar_exclude:
            window = window[window.index > lv.created_at]
        if expiry_exclude:
            window = window[window.index < expiry]
        for side, col in (("upper", lv.upper_level), ("lower", lv.lower_level)):
            lvl_val = float(col)
            ft = first_touch(window, lvl_val) if not window.empty else None
            events.append({
                "level_id": f"{i}_{side}",
                "level_idx": i,
                "session_date": lv.session_date,
                "created_at": lv.created_at,
                "expiry_at": expiry,
                "side": side,
                "level": lvl_val,
                "touched_at": ft,
            })
    return events


def touch_is_clean(bars, ts, level):
    row = bars.loc[ts]
    return bool(row["low"] <= level <= row["high"])


def simulate_from_touch(bars, touched_at, cutoff, entry_fill, sign, cap, be_bars=BE_BARS):
    """Returns (pnl, exit_type, exit_ts). Touch bar: stop-only check (a touch-bar
    target hit is never assumed a win). Rest of path: full TP/SL/BE state machine."""
    touch_row = bars.loc[touched_at]
    orig_stop = entry_fill - sign * cap
    h0, l0 = float(touch_row["high"]), float(touch_row["low"])
    hit_stop = (l0 <= orig_stop) if sign > 0 else (h0 >= orig_stop)
    if hit_stop:
        return sign * (orig_stop - entry_fill), "SL", touched_at

    rest = bars.loc[touched_at: cutoff].iloc[1:]
    if rest.empty:
        return sign * (float(touch_row["close"]) - entry_fill), "cutoff", touched_at

    target = entry_fill + sign * cap
    hi, lo, op, cl = (rest["high"].values, rest["low"].values, rest["open"].values, rest["close"].values)
    idx = rest.index
    armed = checked = False
    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        if i < be_bars:
            stop = orig_stop
        else:
            if not checked:
                checked = True
                o = float(op[i])
                armed = (o >= entry_fill) if sign > 0 else (o <= entry_fill)
            stop = entry_fill if armed else orig_stop
        if sign > 0:
            if l <= stop:
                return sign * (stop - entry_fill), ("BE" if (i >= be_bars and armed) else "SL"), idx[i]
            if h >= target:
                return cap, "TP", idx[i]
        else:
            if h >= stop:
                return sign * (stop - entry_fill), ("BE" if (i >= be_bars and armed) else "SL"), idx[i]
            if l <= target:
                return cap, "TP", idx[i]
    return sign * (float(cl[-1]) - entry_fill), "cutoff", (idx[-1] if len(idx) else touched_at)


# --------------------------------------------------------------- main engine

def run_strict(bars, ranges, events, tie_order="age"):
    """Chronological, single-global-position, time-aware-SAL state machine
    over physical first-touch events. `tie_order` breaks simultaneous-touch
    ties; the frozen primary config uses "age" (oldest level first)."""
    touched = [e for e in events if e["touched_at"] is not None]
    total_physical_touches = len(touched)

    for e in touched:
        pos = bars.index.get_indexer([e["touched_at"]])[0]
        e["prior_close"] = float(bars["close"].iloc[pos - 1]) if pos > 0 else float(bars["close"].iloc[pos])
        e["dist_prior_close"] = abs(e["level"] - e["prior_close"])

    groups = defaultdict(list)
    for e in touched:
        groups[e["touched_at"]].append(e)

    rows, executed = [], []
    skip_counts = defaultdict(int)
    simultaneous_groups = 0
    gap_count = 0
    gap_pnl_delta = 0.0

    pos_exit_time = None
    sal_session = None
    sal_armed_at = None

    def record_skip(ev, reason, pos_state, sal_state):
        skip_counts[reason] += 1
        rows.append({
            "level_id": ev["level_id"], "session_date": ev["session_date"],
            "created_at": ev["created_at"], "expiry_at": ev["expiry_at"],
            "physical_touch": ev["touched_at"], "side": ev["side"],
            "eligibility": "skipped", "skip_reason": reason,
            "position_state": pos_state, "sal_state": sal_state,
            "entry_time": None, "exit_time": None, "entry_price": None,
            "exit_price": None, "anchor": None, "cap": None,
            "exit_reason": None, "pnl": None,
        })

    for ts in sorted(groups.keys()):
        group = groups[ts]

        anchor = prev_completed_range(ranges, ts)
        if anchor is None:
            for e in group:
                record_skip(e, "no_anchor", "n/a", "n/a")
            continue

        if not entry_allowed(ts):
            for e in group:
                record_skip(e, "blocked_time", "n/a", "n/a")
            continue

        cutoff = session_cutoff(ts)
        if cutoff is None:
            for e in group:
                record_skip(e, "no_cutoff", "n/a", "n/a")
            continue

        sess = session_date(ts)
        if sess != sal_session:
            sal_session = sess
            sal_armed_at = None

        sal_state_before = "active" if sal_armed_at is not None else "inactive"

        if sal_armed_at is not None and ts >= sal_armed_at:
            for e in group:
                record_skip(e, "SAL", "n/a", sal_state_before)
            continue

        pos_state = "open" if (pos_exit_time is not None and ts <= pos_exit_time) else "flat"
        if pos_exit_time is not None and ts < pos_exit_time:
            for e in group:
                record_skip(e, "position_open", pos_state, sal_state_before)
            continue
        if pos_exit_time is not None and ts == pos_exit_time:
            for e in group:
                record_skip(e, "same_bar_reentry", "reopen_blocked", sal_state_before)
            continue

        if len(group) > 1:
            simultaneous_groups += 1
            if tie_order == "age":
                ordered = sorted(group, key=lambda e: (e["created_at"], e["side"]))
            elif tie_order == "nearest":
                ordered = sorted(group, key=lambda e: e["dist_prior_close"])
            elif tie_order == "farthest":
                ordered = sorted(group, key=lambda e: -e["dist_prior_close"])
            else:
                raise ValueError(f"unknown tie_order {tie_order}")
            chosen, losers = ordered[0], ordered[1:]
            for e in losers:
                record_skip(e, "simultaneous_collision", pos_state, sal_state_before)
        else:
            chosen = group[0]

        sign = -1.0 if chosen["side"] == "upper" else 1.0
        cap = min(1.5 * anchor, SL_CAP)
        clean = touch_is_clean(bars, ts, chosen["level"])
        fill = chosen["level"] if clean else float(bars.loc[ts, "close"])

        if not clean:
            gap_count += 1
            p_level, _, _ = simulate_from_touch(bars, ts, cutoff, chosen["level"], sign, cap)
            p_adj, ex_adj, exit_ts_adj = simulate_from_touch(bars, ts, cutoff, fill, sign, cap)
            gap_pnl_delta += (p_adj - p_level)
            pnl, ex, exit_ts = p_adj, ex_adj, exit_ts_adj
        else:
            pnl, ex, exit_ts = simulate_from_touch(bars, ts, cutoff, fill, sign, cap)

        year = pd.Timestamp(sess).year
        exit_price = fill + sign * pnl
        executed.append({
            "level_id": chosen["level_id"], "session_date": sess, "year": year,
            "side": chosen["side"], "entry_time": ts, "exit_time": exit_ts,
            "entry_price": fill, "exit_price": exit_price, "level": chosen["level"],
            "anchor": anchor, "cap": cap,
            "exit_reason": ex, "pnl": pnl, "gap_through": not clean,
        })
        rows.append({
            "level_id": chosen["level_id"], "session_date": sess,
            "created_at": chosen["created_at"], "expiry_at": chosen["expiry_at"],
            "physical_touch": ts, "side": chosen["side"],
            "eligibility": "executed", "skip_reason": None,
            "position_state": pos_state, "sal_state": sal_state_before,
            "entry_time": ts, "exit_time": exit_ts, "entry_price": fill,
            "exit_price": exit_price,
            "anchor": anchor, "cap": cap, "exit_reason": ex, "pnl": pnl,
        })

        pos_exit_time = exit_ts
        if pnl < -0.1 and ex != "BE":
            sal_armed_at = exit_ts

    ex_df = pd.DataFrame(executed)
    summary = {
        "total_physical_touches": total_physical_touches,
        "executed": len(ex_df),
        "skipped_no_anchor": skip_counts.get("no_anchor", 0),
        "skipped_blocked_time": skip_counts.get("blocked_time", 0),
        "skipped_no_cutoff": skip_counts.get("no_cutoff", 0),
        "skipped_SAL": skip_counts.get("SAL", 0),
        "skipped_position_open": skip_counts.get("position_open", 0),
        "skipped_same_bar_reentry": skip_counts.get("same_bar_reentry", 0),
        "skipped_simultaneous_collision": skip_counts.get("simultaneous_collision", 0),
        "simultaneous_groups": simultaneous_groups,
        "gap_through_count": gap_count,
        "gap_through_pnl_delta": round(gap_pnl_delta, 3),
    }
    if len(ex_df):
        exs = ex_df["exit_reason"].value_counts()
        pnl = ex_df["pnl"]
        summary.update({
            "TP": int(exs.get("TP", 0)), "SL": int(exs.get("SL", 0)),
            "BE": int(exs.get("BE", 0)), "cutoff": int(exs.get("cutoff", 0)),
            "net_pts": round(float(pnl.sum()), 2),
            "PF": round(profit_factor(pnl), 4),
            "win_rate": round(float((pnl > 0).mean()), 4),
            "twr": round(int(exs.get("TP", 0)) / max(1, int(exs.get("TP", 0)) + int(exs.get("SL", 0))), 4),
            "avg_trade": round(float(pnl.mean()), 3),
            "max_drawdown": round(max_drawdown(pnl), 2),
            "max_loss_streak": max_loss_streak(ex_df["exit_reason"].tolist(), pnl.tolist()),
        })
        cost_adjusted = {}
        for cost in (0.0, 0.5, 1.0, 2.0):
            pnl_c = pnl - cost
            cost_adjusted[f"cost_{cost}"] = {
                "net_pts": round(float(pnl_c.sum()), 2),
                "PF": round(profit_factor(pnl_c), 4),
                "max_drawdown": round(max_drawdown(pnl_c), 2),
                "avg_trade": round(float(pnl_c.mean()), 3),
            }
        summary["cost_adjusted"] = cost_adjusted
        yearly = []
        for yr, s in ex_df.groupby("year"):
            yearly.append({
                "year": int(yr), "n": len(s), "net_pts": round(float(s["pnl"].sum()), 2),
                "PF": round(profit_factor(s["pnl"]), 4),
                "max_drawdown": round(max_drawdown(s["pnl"]), 2),
                "avg_trade": round(float(s["pnl"].mean()), 3),
            })
        summary["yearly"] = yearly
        summary["negative_years"] = [y["year"] for y in yearly if y["net_pts"] < 0]
    else:
        summary["yearly"] = []
        summary["negative_years"] = []

    return summary, ex_df, pd.DataFrame(rows)


# --------------------------------------------------------------------- utils

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


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()

    out_dir = os.path.join(REPO_ROOT, args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)

    print("=== GATE: canonical eligible-candidate reconciliation ===")
    eligible = build_eligible_candidates(bars, vxn)
    print(f"  raw eligible candidates: {len(eligible)}  (expected 1841)")
    if len(eligible) != 1841:
        print("BASELINE MISMATCH. Stopping before profitability interpretation.")
        sys.exit(1)
    eligible.to_csv(os.path.join(out_dir, "baseline_eligible_1841.csv"), index=False)

    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = bar_ranges(bars)
    lvls = list(levels.itertuples(index=False))

    events = physical_touches(bars, lvls)
    pd.DataFrame(events).to_csv(os.path.join(out_dir, "baseline_physical_touches.csv"), index=False)

    print("\n=== PRIMARY: strict one-position / time-aware-SAL engine ===")
    summary, executed, skipped = run_strict(bars, ranges, events)
    print(json.dumps({k: v for k, v in summary.items() if k != "yearly"}, indent=2))

    executed.to_csv(os.path.join(out_dir, "baseline_executed.csv"), index=False)
    skipped.to_csv(os.path.join(out_dir, "baseline_skipped.csv"), index=False)
    pd.DataFrame(summary["yearly"]).to_csv(os.path.join(out_dir, "baseline_yearly.csv"), index=False)

    manifest = {
        "code_commit": git_sha(),
        "data_hashes": {"bars": sha256_file(args.bars), "vxn": sha256_file(args.vxn)},
        "result": summary,
        "reproduction_command": (
            f"python3 -m src.strict_engine --bars {args.bars} --vxn {args.vxn} --out-dir {args.out_dir}"
        ),
    }
    with open(os.path.join(out_dir, "baseline_summary.json"), "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    print(f"\noutputs written to {out_dir}/")


if __name__ == "__main__":
    main()
