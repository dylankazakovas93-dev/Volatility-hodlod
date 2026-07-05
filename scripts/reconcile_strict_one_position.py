#!/usr/bin/env python3
"""Strict NQ one-position reconciliation and falsification harness.

This script is deliberately explicit about event ordering:
  - each level side is physically consumed at its first touch;
  - blocked/SAL/position-open touches do not retest later;
  - SAL activates only after the losing trade's actual exit timestamp;
  - one global NQ position is allowed.

It uses the local workspace data by default. If the exact canonical bars are
not present, the output is labelled LOCAL_REPLAY rather than canonical.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch
import scripts.build_be60_enriched as B


CANONICAL_BARS_ROWS = 2_964_655
CANONICAL_RAW_PRE_SAL = 1_841
SL_CAP = 200.0
BE_BARS = 45
EPS = 0.1


@dataclass(frozen=True)
class Variant:
    name: str
    sl_mult: float = 1.5
    tp_mult: float = 1.5
    sl_cap: float | None = SL_CAP
    tp_cap: float | None = SL_CAP
    be_bars: int | None = BE_BARS
    be_mech: str = "open_cross"
    touch_bar: str = "legacy_next_bar"  # legacy_next_bar | adverse_stop_first
    creation_tradeable: str = "at_created"  # at_created | following_bar
    expiry_rule: str = "inclusive"  # inclusive | exclude_expiry_ts
    same_minute_reentry: bool = True
    cost_pts: float = 0.0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def profit_factor(s: pd.Series) -> float:
    gross = float(s[s > 0].sum())
    loss = float(-s[s < 0].sum())
    return gross / loss if loss else (float("inf") if gross > 0 else 0.0)


def maxdd(s: pd.Series) -> float:
    if s.empty:
        return 0.0
    eq = s.cumsum()
    return float((eq - eq.cummax()).min())


def session_allowed(ts: pd.Timestamp) -> bool:
    et = ts.tz_convert("America/New_York")
    minute = et.hour * 60 + et.minute
    return minute >= 19 * 60 or minute < 11 * 60


def dist(anchor: float, mult: float, cap: float | None) -> float:
    value = anchor * mult
    return value if cap is None else min(value, cap)


def make_variants() -> list[Variant]:
    base = Variant("base_legacy_entrybar")
    return [
        base,
        Variant("creation_following_bar", creation_tradeable="following_bar"),
        Variant("touchbar_adverse_stop_first", touch_bar="adverse_stop_first"),
        Variant("no_same_minute_reentry", same_minute_reentry=False),
        Variant("expiry_exclude_creation_ts", expiry_rule="exclude_expiry_ts"),
        Variant("sl_cap_tp_uncapped", sl_cap=SL_CAP, tp_cap=None),
        Variant("tp_cap_sl_uncapped", sl_cap=None, tp_cap=SL_CAP),
        Variant("both_uncapped", sl_cap=None, tp_cap=None),
    ]


def build_physical_touches(bars: pd.DataFrame, vxn: pd.Series, variant: Variant) -> pd.DataFrame:
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = B.bar_ranges(bars)
    lvls = list(levels.itertuples(index=False))
    rows = []
    for i, lv in enumerate(lvls):
        created_at = lv.created_at
        search_start = created_at
        if variant.creation_tradeable == "following_bar":
            pos = bars.index.searchsorted(created_at, side="right")
            if pos >= len(bars.index):
                continue
            search_start = bars.index[pos]
        expiry = lvls[i + B.LINE_DAYS].created_at if i + B.LINE_DAYS < len(lvls) else bars.index[-1]
        if variant.expiry_rule == "exclude_expiry_ts":
            search = bars.loc[search_start: expiry]
            search = search[search.index < expiry]
        else:
            search = bars.loc[search_start: expiry]
        if search.empty:
            continue
        for side, col in (("upper", lv.upper_level), ("lower", lv.lower_level)):
            level = float(col)
            touched_at = _first_touch(search, level)
            if touched_at is None:
                continue
            anchor = B.prev_completed_range(ranges, touched_at)
            cutoff = B.session_cutoff(touched_at)
            sess = B.session_date(touched_at)
            rows.append({
                "level_id": f"{i}:{side}",
                "level_index": i,
                "level_session": str(lv.session_date),
                "created_at": created_at,
                "expiry_at": expiry,
                "sess_date": sess,
                "year": pd.Timestamp(sess).year,
                "side": side,
                "sign": -1.0 if side == "upper" else 1.0,
                "level": level,
                "touched_at": touched_at,
                "anchor": anchor,
                "cutoff": cutoff,
                "entry_allowed": session_allowed(touched_at),
                "has_anchor": anchor is not None,
                "has_cutoff": cutoff is not None,
            })
    return pd.DataFrame(rows).sort_values(["touched_at", "level_index", "side"], kind="stable").reset_index(drop=True)


def simulate_trade(
    bars: pd.DataFrame,
    touch: pd.Series,
    variant: Variant,
) -> tuple[float, str, pd.Timestamp, float, float]:
    entry = float(touch["level"])
    sign = float(touch["sign"])
    anchor = float(touch["anchor"])
    tp = dist(anchor, variant.tp_mult, variant.tp_cap)
    sl = dist(anchor, variant.sl_mult, variant.sl_cap)
    cutoff = touch["cutoff"]

    if variant.touch_bar == "adverse_stop_first":
        path = bars.loc[touch["touched_at"]: cutoff]
    else:
        path = bars.loc[touch["touched_at"]: cutoff].iloc[1:]
    if path.empty:
        return 0.0 - variant.cost_pts, "no_path", touch["touched_at"], tp, sl

    target = entry + sign * tp
    orig_stop = entry - sign * sl
    hi = path["high"].values
    lo = path["low"].values
    op = path["open"].values
    cl = path["close"].values
    idx = path.index
    armed = False
    checked = False
    for i in range(len(path)):
        h = float(hi[i])
        l = float(lo[i])
        if variant.be_bars is None or i < variant.be_bars:
            stop = orig_stop
        else:
            if not checked:
                checked = True
                ref = float(cl[i - 1]) if variant.be_mech == "close_cross" and i > 0 else float(op[i])
                armed = (ref >= entry) if sign > 0 else (ref <= entry)
            stop = entry if armed else orig_stop

        if sign > 0:
            hit_stop = l <= stop
            hit_tp = h >= target
        else:
            hit_stop = h >= stop
            hit_tp = l <= target

        if variant.touch_bar == "adverse_stop_first" and i == 0 and hit_stop:
            return sign * (stop - entry) - variant.cost_pts, ("BE" if (variant.be_bars is not None and i >= variant.be_bars and armed) else "SL"), idx[i], tp, sl
        if hit_stop:
            return sign * (stop - entry) - variant.cost_pts, ("BE" if (variant.be_bars is not None and i >= variant.be_bars and armed) else "SL"), idx[i], tp, sl
        if hit_tp:
            return tp - variant.cost_pts, "TP", idx[i], tp, sl

    return sign * (float(cl[-1]) - entry) - variant.cost_pts, "cutoff", idx[-1], tp, sl


def run_state_machine(touches: pd.DataFrame, bars: pd.DataFrame, variant: Variant) -> tuple[pd.DataFrame, pd.DataFrame]:
    executed = []
    skipped = []
    active_until: pd.Timestamp | None = None
    last_exit_minute: pd.Timestamp | None = None
    sal_by_session: dict[str, pd.Timestamp] = {}

    for _, row in touches.iterrows():
        t = row["touched_at"]
        sess = row["sess_date"]
        reason = None
        sal_at = sal_by_session.get(sess)
        if sal_at is not None and t >= sal_at:
            reason = "sal_active"
        elif active_until is not None and t < active_until:
            reason = "position_open"
        elif not variant.same_minute_reentry and last_exit_minute is not None and t.floor("min") == last_exit_minute.floor("min"):
            reason = "same_minute_reentry"
        elif not bool(row["entry_allowed"]):
            reason = "blocked_time"
        elif not bool(row["has_anchor"]):
            reason = "no_anchor"
        elif not bool(row["has_cutoff"]):
            reason = "no_cutoff"

        if reason is not None:
            d = row.to_dict()
            d["skip_reason"] = reason
            skipped.append(d)
            continue

        pnl, ex, exit_time, tp, sl = simulate_trade(bars, row, variant)
        d = row.to_dict()
        d.update({
            "pnl": pnl,
            "exit": ex,
            "exit_time": exit_time,
            "tp_dist": tp,
            "sl_dist": sl,
            "variant": variant.name,
        })
        executed.append(d)
        active_until = exit_time
        last_exit_minute = exit_time
        if pnl < -EPS and ex != "BE":
            sal_by_session[sess] = exit_time

    return pd.DataFrame(executed), pd.DataFrame(skipped)


def summarize(df: pd.DataFrame, label: str) -> dict:
    if df.empty:
        return {"variant": label, "n": 0, "net": 0.0, "pf": 0.0, "maxdd": 0.0, "avg": 0.0, "wr": 0.0, "twr": 0.0, "tp": 0, "sl": 0, "be": 0, "cut": 0}
    p = df["pnl"].astype(float)
    ex = df["exit"].value_counts()
    tp = int(ex.get("TP", 0))
    sl = int(ex.get("SL", 0))
    return {
        "variant": label,
        "n": len(df),
        "net": float(p.sum()),
        "pf": profit_factor(p),
        "maxdd": maxdd(p),
        "avg": float(p.mean()),
        "wr": float((p > EPS).mean() * 100),
        "twr": tp / (tp + sl) * 100 if tp + sl else 0.0,
        "tp": tp,
        "sl": sl,
        "be": int(ex.get("BE", 0)),
        "cut": int(ex.get("cutoff", 0)),
    }


def yearly(df: pd.DataFrame, variant_name: str) -> pd.DataFrame:
    rows = []
    for year, sub in df.groupby("year"):
        r = summarize(sub, variant_name)
        r["year"] = int(year)
        rows.append(r)
    return pd.DataFrame(rows)


def collision_report(touches: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ts, group in touches.groupby("touched_at"):
        if len(group) <= 1:
            continue
        levels = group["level"].astype(float).sort_values().to_list()
        min_dist = min(abs(a - b) for i, a in enumerate(levels) for b in levels[i + 1:])
        rows.append({
            "touched_at": ts,
            "count": len(group),
            "sides": "|".join(group["side"].astype(str)),
            "min_level_distance": min_dist,
            "level_ids": "|".join(group["level_id"].astype(str)),
        })
    return pd.DataFrame(rows)


def gap_report(touches: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in touches.iterrows():
        try:
            bar = bars.loc[r["touched_at"]]
        except KeyError:
            continue
        level = float(r["level"])
        in_range = float(bar["low"]) <= level <= float(bar["high"])
        if not in_range:
            rows.append({
                "level_id": r["level_id"],
                "touched_at": r["touched_at"],
                "side": r["side"],
                "level": level,
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
            })
    return pd.DataFrame(rows)


def write_manifest(args: argparse.Namespace, bars: pd.DataFrame, touches: pd.DataFrame, status: str) -> None:
    paths = [Path(args.bars), Path(args.vxn), ROOT / "volgen/levels.py", ROOT / "volgen/reactions.py", ROOT / "scripts/nq_cond_be45.py"]
    manifest = {
        "status": status,
        "command": " ".join(sys.argv),
        "bars_path": args.bars,
        "vxn_path": args.vxn,
        "bars_rows": len(bars),
        "bars_start": str(bars.index[0]),
        "bars_end": str(bars.index[-1]),
        "physical_touches_base": len(touches),
        "eligible_candidate_target": CANONICAL_RAW_PRE_SAL,
        "sha256": {str(p): sha256(p) for p in paths if p.exists()},
        "config": {
            "level_params": str(NQ_PARAMS),
            "line_days": B.LINE_DAYS,
            "sl_cap": SL_CAP,
            "be_bars": BE_BARS,
            "entry_window": "19:00-11:00 ET",
            "cutoff": "15:00 ET",
        },
    }
    (ROOT / "DATA_MANIFEST.md").write_text("# Data Manifest\n\n```json\n" + json.dumps(manifest, indent=2) + "\n```\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", default=str(ROOT / "data/nq_1m/nq_continuous_downloads_2018_2026_1m.csv"))
    parser.add_argument("--vxn", default=str(ROOT / "data/vxn_daily_2018_2026.csv"))
    parser.add_argument("--outputs", default=str(ROOT / "outputs"))
    args = parser.parse_args()

    outdir = Path(args.outputs)
    outdir.mkdir(parents=True, exist_ok=True)

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)
    base_variant = Variant("base_legacy_entrybar")
    touches = build_physical_touches(bars, vxn, base_variant)
    eligible = touches[touches["entry_allowed"] & touches["has_anchor"] & touches["has_cutoff"]].copy()
    status = "CANONICAL_MATCH" if len(bars) == CANONICAL_BARS_ROWS and len(eligible) == CANONICAL_RAW_PRE_SAL else "FAILED_REPRODUCTION_LOCAL_REPLAY"

    touches.to_csv(outdir / "local_physical_touches.csv", index=False)
    eligible.to_csv(outdir / "canonical_eligible_1841.csv", index=False)
    eligible.to_csv(outdir / "local_eligible_candidates.csv", index=False)
    write_manifest(args, bars, eligible, status)

    summaries = []
    yearly_rows = []
    base_exec = base_skip = None
    for variant in make_variants():
        vt = touches if variant == base_variant else build_physical_touches(bars, vxn, variant)
        executed, skipped = run_state_machine(vt, bars, variant)
        executed.to_csv(outdir / f"{variant.name}_executed.csv", index=False)
        skipped.to_csv(outdir / f"{variant.name}_skipped.csv", index=False)
        summaries.append(summarize(executed, variant.name) | {
            "raw_physical_touches": len(vt),
            "eligible_candidates": int((vt["entry_allowed"] & vt["has_anchor"] & vt["has_cutoff"]).sum()),
            "skipped": len(skipped),
        })
        yr = yearly(executed, variant.name)
        yearly_rows.append(yr)
        if variant.name == "base_legacy_entrybar":
            base_exec, base_skip = executed, skipped

    assert base_exec is not None and base_skip is not None
    base_exec.to_csv(outdir / "canonical_strict_executed.csv", index=False)
    base_skip.to_csv(outdir / "canonical_strict_skipped.csv", index=False)
    pd.concat(yearly_rows, ignore_index=True).to_csv(outdir / "canonical_strict_yearly.csv", index=False)
    pd.DataFrame(summaries).to_csv(outdir / "canonical_sensitivities.csv", index=False)

    cost_rows = []
    for cost in [0.0, 0.5, 1.0, 2.0]:
        adj = base_exec.copy()
        adj["pnl"] = adj["pnl"] - cost
        cost_rows.append(summarize(adj, f"cost_{cost:g}") | {"cost_pts": cost})
    pd.DataFrame(cost_rows).to_csv(outdir / "canonical_costs.csv", index=False)

    removal_rows = []
    for label, mask in {
        "full": base_exec["year"].notna(),
        "exclude_2026": base_exec["year"] <= 2025,
        "exclude_2025_2026": base_exec["year"] <= 2024,
        "2018_2024_only": base_exec["year"] <= 2024,
    }.items():
        removal_rows.append(summarize(base_exec[mask], label))
    pd.DataFrame(removal_rows).to_csv(outdir / "canonical_recent_year_concentration.csv", index=False)

    collision_report(touches).to_csv(outdir / "canonical_collision_report.csv", index=False)
    gap_report(touches, bars).to_csv(outdir / "canonical_gap_report.csv", index=False)

    print(f"status={status}")
    print(f"bars_rows={len(bars)} physical_touches={len(touches)} eligible={len(eligible)}")
    print(pd.DataFrame(summaries).to_string(index=False))


if __name__ == "__main__":
    main()
