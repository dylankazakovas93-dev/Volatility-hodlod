#!/usr/bin/env python3
"""Strict one-position, time-aware-SAL reconciliation of the NQ level-fade engine.

Rebuilds the canonical eligible-candidate gate (1,841) from
scripts/nq_cond_be45.py's own mechanics, then runs a chronological,
single-global-position, time-aware-SAL state machine over the physical
first-touch events, with six edge cases handled via an explicit primary
(conservative) rule plus an individually-reported sensitivity for each.

Usage:
    python3 scripts/reconcile_strict_one_position.py \
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

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch
import scripts.build_be60_enriched as B
import scripts.nq_cond_be45 as C

LINE_DAYS = B.LINE_DAYS
SL_CAP = B.SL_CAP
BE_BARS = 45


# ---------------------------------------------------------------- utilities

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ).decode().strip()
    except Exception:
        return None


def profit_factor(s):
    g = float(s[s > 0].sum())
    l = float(-s[s < 0].sum())
    return g / l if l > 0 else float("inf")


def max_drawdown(s):
    eq = s.cumsum()
    return float((eq - eq.cummax()).min())


def max_loss_streak(exs, pnls):
    best = cur = 0
    for ex, p in zip(exs, pnls):
        if p < -0.1 and ex != "BE":
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


# ------------------------------------------------------------ physical touch

def physical_touches(bars, lvls, creation_bar_exclude, expiry_exclude):
    """One row per level-side. touched_at is None if never physically touched
    inside its live window under the given edge-case rules."""
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
            ft = _first_touch(window, lvl_val) if not window.empty else None
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


def simulate_from_touch(bars, touched_at, cutoff, entry_fill, sign, cap, touchbar_stop_only, be_bars=BE_BARS):
    """Returns (pnl, exit_type, exit_ts). exit_type in {SL,BE,TP,cutoff}."""
    touch_row = bars.loc[touched_at]
    orig_stop = entry_fill - sign * cap
    if touchbar_stop_only:
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

def run_strict(bars, ranges, events, opts):
    """opts: touchbar_stop_only, gap_fill_adjust, samebar_reentry_block, tie_order."""
    touchbar_stop_only = opts.get("touchbar_stop_only", True)
    gap_fill_adjust = opts.get("gap_fill_adjust", True)
    samebar_reentry_block = opts.get("samebar_reentry_block", True)
    tie_order = opts.get("tie_order", "age")

    touched = [e for e in events if e["touched_at"] is not None]
    total_physical_touches = len(touched)

    for e in touched:
        pos = bars.index.get_indexer([e["touched_at"]])[0]
        e["prior_close"] = float(bars["close"].iloc[pos - 1]) if pos > 0 else float(bars["close"].iloc[pos])
        e["dist_prior_close"] = abs(e["level"] - e["prior_close"])

    groups = defaultdict(list)
    for e in touched:
        groups[e["touched_at"]].append(e)

    rows = []
    executed = []
    skip_counts = defaultdict(int)
    simultaneous_groups = 0
    gap_count = 0
    gap_pnl_delta = 0.0
    samebar_reentry_blocked = 0

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

        anchor = B.prev_completed_range(ranges, ts)
        if anchor is None:
            for e in group:
                record_skip(e, "no_anchor", "n/a", "n/a")
            continue

        if not B.entry_allowed(ts):
            for e in group:
                record_skip(e, "blocked_time", "n/a", "n/a")
            continue

        cutoff = B.session_cutoff(ts)
        if cutoff is None:
            for e in group:
                record_skip(e, "no_cutoff", "n/a", "n/a")
            continue

        sess = B.session_date(ts)
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
            if samebar_reentry_block:
                samebar_reentry_blocked += len(group)
                for e in group:
                    record_skip(e, "same_bar_reentry", "reopen_blocked", sal_state_before)
                continue

        # ---- choose one candidate from the (possibly simultaneous) group ----
        if len(group) > 1:
            simultaneous_groups += 1
            if tie_order == "age":
                ordered = sorted(group, key=lambda e: (e["created_at"], e["side"]))
            elif tie_order == "nearest":
                ordered = sorted(group, key=lambda e: e["dist_prior_close"])
            elif tie_order == "farthest":
                ordered = sorted(group, key=lambda e: -e["dist_prior_close"])
            elif tie_order == "worst":
                previews = []
                for e in group:
                    sign = -1.0 if e["side"] == "upper" else 1.0
                    cap = min(1.5 * anchor, SL_CAP)
                    clean = touch_is_clean(bars, ts, e["level"])
                    fill = e["level"] if (not gap_fill_adjust or clean) else float(bars.loc[ts, "close"])
                    p, _, _ = simulate_from_touch(bars, ts, cutoff, fill, sign, cap, touchbar_stop_only)
                    previews.append((e, p))
                previews.sort(key=lambda t: t[1])
                ordered = [e for e, _ in previews]
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
        fill = chosen["level"] if (not gap_fill_adjust or clean) else float(bars.loc[ts, "close"])

        if not clean:
            gap_count += 1
            p_level, _, _ = simulate_from_touch(bars, ts, cutoff, chosen["level"], sign, cap, touchbar_stop_only)
            p_adj, ex_adj, exit_ts_adj = simulate_from_touch(bars, ts, cutoff, fill, sign, cap, touchbar_stop_only)
            gap_pnl_delta += (p_adj - p_level)
            pnl, ex, exit_ts = p_adj, ex_adj, exit_ts_adj
        else:
            pnl, ex, exit_ts = simulate_from_touch(bars, ts, cutoff, fill, sign, cap, touchbar_stop_only)

        year = pd.Timestamp(sess).year
        executed.append({
            "level_id": chosen["level_id"], "session_date": sess, "year": year,
            "side": chosen["side"], "entry_time": ts, "exit_time": exit_ts,
            "entry_price": fill, "level": chosen["level"], "anchor": anchor, "cap": cap,
            "exit_reason": ex, "pnl": pnl, "gap_through": not clean,
        })
        rows.append({
            "level_id": chosen["level_id"], "session_date": sess,
            "created_at": chosen["created_at"], "expiry_at": chosen["expiry_at"],
            "physical_touch": ts, "side": chosen["side"],
            "eligibility": "executed", "skip_reason": None,
            "position_state": pos_state, "sal_state": sal_state_before,
            "entry_time": ts, "exit_time": exit_ts, "entry_price": fill,
            "exit_price": fill + sign * pnl if False else None,
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


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(os.path.join(repo_root, args.out_dir), exist_ok=True)

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)

    # ---- GATE 1: reconstruct the canonical 1,841 eligible-candidate count ----
    raw = C.build_ledger(bars, vxn)
    gate_1841 = len(raw)
    print(f"=== GATE 1: canonical eligible-candidate reconciliation ===")
    print(f"  raw eligible candidates (nq_cond_be45.build_ledger): {gate_1841}")
    print(f"  expected: 1841   {'PASS' if gate_1841 == 1841 else 'FAIL'}")
    if gate_1841 != 1841:
        print("BASELINE MISMATCH. Stopping before profitability interpretation.")
        sys.exit(1)
    raw.to_csv(os.path.join(repo_root, args.out_dir, "nq_eligible_1841.csv"), index=False)

    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = B.bar_ranges(bars)
    lvls = list(levels.itertuples(index=False))

    print("\n=== Building physical first-touch tables ===")
    events_primary = physical_touches(bars, lvls, creation_bar_exclude=True, expiry_exclude=True)
    events_incl_creation = physical_touches(bars, lvls, creation_bar_exclude=False, expiry_exclude=True)
    events_incl_expiry = physical_touches(bars, lvls, creation_bar_exclude=True, expiry_exclude=False)

    phys_df = pd.DataFrame(events_primary)
    phys_df.to_csv(os.path.join(repo_root, args.out_dir, "nq_physical_first_touches.csv"), index=False)
    n_creation_bar_touches = sum(
        1 for a, b in zip(events_incl_creation, events_primary)
        if a["touched_at"] is not None and a["touched_at"] == a["created_at"] and b["touched_at"] != a["touched_at"]
    )

    print("\n=== PRIMARY: fully conservative strict engine ===")
    primary_opts = dict(touchbar_stop_only=True, gap_fill_adjust=True,
                        samebar_reentry_block=True, tie_order="age")
    primary_summary, primary_ex, primary_rows = run_strict(bars, ranges, events_primary, primary_opts)
    primary_summary["skipped_creation_bar"] = n_creation_bar_touches
    print(json.dumps({k: v for k, v in primary_summary.items() if k != "yearly"}, indent=2))

    primary_ex.to_csv(os.path.join(repo_root, args.out_dir, "nq_strict_executed.csv"), index=False)
    primary_rows.to_csv(os.path.join(repo_root, args.out_dir, "nq_strict_skipped.csv"), index=False)
    pd.DataFrame(primary_summary["yearly"]).to_csv(
        os.path.join(repo_root, args.out_dir, "nq_strict_yearly.csv"), index=False)

    print("\n=== ORIGINAL OPTIMISTIC MECHANICS (nq_cond_be45 + SAL, overlap-permitting) ===")
    kept_orig = C.apply_sal(raw)
    ex_orig = kept_orig["exit"].value_counts()
    original_summary = {
        "trades": len(kept_orig), "net_pts": round(float(kept_orig["pnl"].sum()), 2),
        "PF": round(profit_factor(kept_orig["pnl"]), 4),
        "TP": int(ex_orig.get("TP", 0)), "SL": int(ex_orig.get("SL", 0)),
        "BE": int(ex_orig.get("BE", 0)), "cutoff": int(ex_orig.get("cutoff", 0)),
    }
    print(json.dumps(original_summary, indent=2))

    print("\n=== SENSITIVITIES (one edge case flipped at a time from PRIMARY) ===")
    sensitivities = {}

    s_opts = dict(primary_opts); s_opts["touchbar_stop_only"] = False
    s, _, _ = run_strict(bars, ranges, events_primary, s_opts)
    sensitivities["B_skip_touch_bar_original"] = s

    s_opts = dict(primary_opts); s_opts["gap_fill_adjust"] = False
    s, _, _ = run_strict(bars, ranges, events_primary, s_opts)
    sensitivities["C_no_gap_adjustment"] = s

    s_opts = dict(primary_opts); s_opts["samebar_reentry_block"] = False
    s, _, _ = run_strict(bars, ranges, events_primary, s_opts)
    sensitivities["D_allow_samebar_reentry"] = s

    for order in ("nearest", "farthest", "worst"):
        s_opts = dict(primary_opts); s_opts["tie_order"] = order
        s, _, _ = run_strict(bars, ranges, events_primary, s_opts)
        sensitivities[f"E_order_{order}"] = s

    s, _, _ = run_strict(bars, ranges, events_incl_creation, primary_opts)
    sensitivities["A_include_creation_bar"] = s

    s, _, _ = run_strict(bars, ranges, events_incl_expiry, primary_opts)
    sensitivities["F_include_expiry_timestamp"] = s

    for name, s in sensitivities.items():
        print(f"  {name:32s}  n={s['executed']:5d}  net={s['net_pts']:>9.1f}  "
              f"PF={s['PF']:.4f}  negYears={s['negative_years']}")

    edge_rows = []
    for name, s in {"PRIMARY": primary_summary, **sensitivities}.items():
        edge_rows.append({
            "config": name, "executed": s["executed"], "net_pts": s["net_pts"],
            "PF": s["PF"], "win_rate": s.get("win_rate"), "twr": s.get("twr"),
            "max_drawdown": s.get("max_drawdown"), "negative_years": s["negative_years"],
        })
    pd.DataFrame(edge_rows).to_csv(
        os.path.join(repo_root, args.out_dir, "nq_edge_case_sensitivities.csv"), index=False)

    # ------------------------------------------------------------ manifest
    sha = git_sha()
    bars_hash = sha256_file(args.bars)
    vxn_hash = sha256_file(args.vxn)
    config = {
        "LINE_DAYS": LINE_DAYS, "SL_CAP": SL_CAP, "BE_BARS": BE_BARS,
        "NQ_PARAMS": NQ_PARAMS.__dict__, "primary_opts": primary_opts,
    }
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()

    out_dir_abs = os.path.join(repo_root, args.out_dir)
    output_hashes = {}
    for fn in ["nq_physical_first_touches.csv", "nq_eligible_1841.csv", "nq_strict_executed.csv",
               "nq_strict_skipped.csv", "nq_strict_yearly.csv", "nq_edge_case_sensitivities.csv"]:
        p = os.path.join(out_dir_abs, fn)
        if os.path.exists(p):
            output_hashes[fn] = sha256_file(p)

    full_summary = {
        "git_sha": sha,
        "data_file_hashes": {"bars": bars_hash, "vxn": vxn_hash},
        "config_hash": config_hash,
        "output_hashes": output_hashes,
        "gate_1841": {"status": "PASS" if gate_1841 == 1841 else "FAIL", "count": gate_1841},
        "original_optimistic": original_summary,
        "primary_conservative": {k: v for k, v in primary_summary.items()},
        "sensitivities": sensitivities,
        "reproduction_command": (
            f"python3 scripts/reconcile_strict_one_position.py "
            f"--bars {args.bars} --vxn {args.vxn} --out-dir {args.out_dir}"
        ),
    }
    with open(os.path.join(out_dir_abs, "nq_strict_summary.json"), "w") as f:
        json.dump(full_summary, f, indent=2, default=str)

    print("\n=== MANIFEST ===")
    print(f"  git SHA        : {sha}")
    print(f"  bars sha256    : {bars_hash}")
    print(f"  vxn  sha256    : {vxn_hash}")
    print(f"  config sha256  : {config_hash}")
    print(f"  outputs written to {out_dir_abs}/")


if __name__ == "__main__":
    main()
