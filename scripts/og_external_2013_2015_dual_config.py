"""OG dual-config EXTERNAL 2013-2015 DIAGNOSTIC runner (Step 4 of the
OG_EXTERNAL_2013_2015 task).

Reuses the exact frozen mechanics already locked for OG_PRIMARY_150R /
OG_OPERATIONAL_100R and already reused (unmodified) by
scripts/og_validation_dual_config.py -- src/level_generation.py
(generate_levels, sigma-band math), src/strict_engine.py (bar_ranges,
physical_touches, eligibility gate), src/og_management_variants.py
(run_variant_managed, the chronological single-global-position state
machine) -- and reports outcomes for the externally-sourced 2013-2015
window instead of the locked validation years or build years.

It does NOT re-derive levels, touches, or any mechanic, and does NOT
permanently repoint the committed configs at the 2013-2015 data: the bars
and VXN file paths are supplied as explicit CLI overrides
(--bars/--vxn) and used only in-memory for this run.

FAIL-CLOSED requirements enforced here (raise + nonzero exit, never warn):
  - required config fields must be present
  - config status label must exactly match the expected (not-yet-validated)
    locked label
  - the two configs may only differ in target.target_r
  - --years must be exactly {2013, 2014, 2015}
  - no other year (including the 2012 warmup-only months present in the
    VXN file) may appear in any traded/reported output
  - --bars/--vxn must exist and hash-match the values recorded in
    docs/OG_EXTERNAL_2013_2015_DATA_REPORT.md
  - any invariant failure aborts before producing final output

Exact reproduction command:
    python3 scripts/og_external_2013_2015_dual_config.py \\
        --years 2013 2014 2015 \\
        --config configs/OG_PRIMARY_150R.yaml \\
        --config configs/OG_OPERATIONAL_100R.yaml \\
        --bars data/external_2013_2015/normalized/nq_continuous_2013_2015_1m.csv \\
        --vxn data/external_2013_2015/normalized/vxn_daily_2012warmup_2015.csv \\
        --out-dir outputs/og_external_2013_2015/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv, load_gvz_daily
from src.level_generation import NQ_PARAMS, generate_levels
from src.strict_engine import bar_ranges, physical_touches
from src.og_build_variant_engine import in_prop_hard_blackout
from src.og_management_variants import run_variant_managed
from src.metrics import profit_factor, max_drawdown

EXTERNAL_YEARS = frozenset({2013, 2014, 2015})
WARMUP_ONLY_YEARS = frozenset({2012})  # present in the VXN file, must never be traded/reported

EXPECTED_BARS_SHA256 = "026aab199422298cfac7d03b1c58e883b74598d3bd0c66cb52cf6b3d2f5ce4da"
EXPECTED_VXN_SHA256 = "9355c3d720ef33707810638e158e513dc1fb037ad77a74bc3a6bfd27664a37c7"

EXPECTED_STATUS = {
    "OG_PRIMARY_150R": "PRIMARY_RESEARCH_CONFIG__RETROSPECTIVE_BUILD_PASS__NOT_VALIDATED",
    "OG_OPERATIONAL_100R": "SECONDARY_OPERATIONAL_CONFIG__RETROSPECTIVE_BUILD_PASS__NOT_VALIDATED",
}

REQUIRED_FIELDS = [
    "status", "config_id", "source", "data", "level_generation", "stop_calc",
    "one_global_position", "no_overlap", "no_stacking", "no_same_minute_reentry",
    "permanent_touch_consumption", "tie_order", "intrabar_ambiguity",
    "forced_liquidation_time_et", "prop_hard_blackout", "entry_blackout",
    "sal_enabled", "management", "hmm_gate", "target", "expected_build_ledger",
]

COMPARE_KEYS = [
    "level_generation", "stop_calc", "one_global_position", "no_overlap",
    "no_stacking", "no_same_minute_reentry", "permanent_touch_consumption",
    "tie_order", "intrabar_ambiguity", "forced_liquidation_time_et",
    "prop_hard_blackout", "entry_blackout", "sal_enabled", "management", "hmm_gate",
]
# NOTE: "data" is deliberately excluded from COMPARE_KEYS here (unlike the
# locked-validation runner) only because both configs' *own* data.vxn_file/
# bars_file point at the 2018-2026 build data and are overridden identically
# by --bars/--vxn for both configs in this diagnostic; the override is
# applied uniformly so it cannot introduce an asymmetry between the two.


class ExternalDiagFailClosed(RuntimeError):
    """Raised for any fail-closed condition. Must propagate to a nonzero exit."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_config(path):
    with open(path) as f:
        cfg = yaml.safe_load(f)
    missing = [k for k in REQUIRED_FIELDS if k not in cfg]
    if missing:
        raise ExternalDiagFailClosed(f"{path}: missing required config field(s): {missing}")
    config_id = cfg["config_id"]
    if config_id not in EXPECTED_STATUS:
        raise ExternalDiagFailClosed(f"{path}: unknown config_id {config_id!r}")
    if cfg["status"] != EXPECTED_STATUS[config_id]:
        raise ExternalDiagFailClosed(
            f"{path}: status label mismatch. expected "
            f"{EXPECTED_STATUS[config_id]!r}, got {cfg['status']!r}")
    return cfg


def assert_configs_only_differ_in_target_r(cfg_a, cfg_b, path_a, path_b):
    for key in COMPARE_KEYS:
        if cfg_a.get(key) != cfg_b.get(key):
            raise ExternalDiagFailClosed(
                f"{path_a} and {path_b} differ in {key!r} (must be identical "
                f"except target.target_r): {cfg_a.get(key)!r} != {cfg_b.get(key)!r}")
    ta, tb = cfg_a["target"], cfg_b["target"]
    if ta.get("target_r") == tb.get("target_r"):
        raise ExternalDiagFailClosed(
            "configs have identical target_r; expected exactly one axis of "
            "difference (target.target_r)")


def resolve_effective_params(cfg):
    mgmt = cfg["management"]
    if mgmt.get("mode") != "barcount":
        raise ExternalDiagFailClosed(f"unsupported management.mode {mgmt.get('mode')!r}")
    if "be_bars" not in mgmt:
        raise ExternalDiagFailClosed("management.be_bars missing")
    if mgmt.get("be_extra_lock", None) != 0.0:
        raise ExternalDiagFailClosed("management.be_extra_lock must be 0.0")
    if cfg["hmm_gate"].get("enabled"):
        raise ExternalDiagFailClosed("hmm_gate.enabled=true is not supported by this runner")
    if cfg["sal_enabled"] is not False:
        raise ExternalDiagFailClosed("sal_enabled must be false")
    if cfg["tie_order"] != "age":
        raise ExternalDiagFailClosed("tie_order must be 'age'")
    win = cfg["entry_blackout"]["blocked_window_minutes"]
    target_r = cfg["target"]["target_r"]
    if target_r is None:
        raise ExternalDiagFailClosed("target.target_r missing")
    fl = cfg["forced_liquidation_time_et"]
    if fl != "15:00":
        raise ExternalDiagFailClosed(f"forced_liquidation_time_et must be '15:00', got {fl!r}")
    return {
        "be_bars": int(mgmt["be_bars"]),
        "blocked_window": (int(win[0]), int(win[1])),
        "target_r": float(target_r),
    }


def holding_minutes(row):
    return (row["exit_time"] - row["entry_time"]).total_seconds() / 60.0


def compute_block_metrics(label, sub):
    n = len(sub)
    out = {"config": label, "n_trades": n}
    if n == 0:
        return out
    pnl = sub["pnl"]
    capr = sub["pnl"] / sub["cap"]
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    exs = sub["exit_reason"].value_counts()
    holds = sub.apply(holding_minutes, axis=1)
    by_day = sub.groupby("session_date")["pnl"].sum()
    out.update({
        "net_pts": round(float(pnl.sum()), 2),
        "PF_pts": round(profit_factor(pnl), 4),
        "PF_R": round(profit_factor(capr), 4),
        "total_R": round(float(capr.sum()), 4),
        "avg_R_per_trade": round(float(capr.mean()), 4),
        "win_rate": round(float((pnl > 0).mean()), 4),
        "avg_winner": round(float(wins.mean()), 3) if len(wins) else 0.0,
        "avg_loser": round(float(losses.mean()), 3) if len(losses) else 0.0,
        "payoff_ratio": round(float(wins.mean() / abs(losses.mean())), 4) if len(wins) and len(losses) else None,
        "max_drawdown_pts": round(max_drawdown(pnl), 2),
        "max_drawdown_R": round(max_drawdown(capr), 4),
        "TP": int(exs.get("TP", 0)), "SL": int(exs.get("SL", 0)),
        "BE": int(exs.get("BE", 0)), "cutoff": int(exs.get("cutoff", 0)),
        "mean_holding_min": round(float(holds.mean()), 2),
        "median_holding_min": round(float(holds.median()), 2),
        "profitable_days": int((by_day > 0).sum()),
        "losing_days": int((by_day < 0).sum()),
        "breakeven_days": int((by_day == 0).sum()),
        "longest_non_winning_day_run": longest_non_winning_run(by_day),
    })
    return out


def longest_non_winning_run(by_day_pnl):
    best = cur = 0
    for v in by_day_pnl.sort_index().values:
        if v <= 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return int(best)


def run_one_config(config_id, params, bars, ranges, events, years, out_dir):
    summary, ex_df = run_variant_managed(
        bars, ranges, events,
        mgmt_kwargs=dict(mode="barcount", be_bars=params["be_bars"], target_r=params["target_r"]),
        sal_enabled=False, blocked_window=params["blocked_window"], hmm_gate=None)

    if len(ex_df):
        bad_entry = ex_df["entry_time"].apply(in_prop_hard_blackout).any()
        bad_exit = ex_df["exit_time"].apply(in_prop_hard_blackout).any()
        if bad_entry or bad_exit:
            raise ExternalDiagFailClosed(f"{config_id}: PROP_HARD_BLACKOUT violated")

    if ex_df is None or len(ex_df) == 0:
        by = pd.DataFrame(columns=[
            "level_id", "session_date", "year", "side", "entry_time", "exit_time",
            "entry_price", "exit_price", "level", "anchor", "cap",
            "exit_reason", "pnl", "gap_through",
        ])
    else:
        all_years = set(ex_df["year"].unique())
        leaked_warmup = all_years & WARMUP_ONLY_YEARS
        if leaked_warmup:
            raise ExternalDiagFailClosed(
                f"{config_id}: warmup-only year(s) {leaked_warmup} produced traded "
                f"output -- 2012 must be causal-lookup only")
        by = ex_df[ex_df["year"].isin(years)].copy()
        extra = all_years - set(years) - WARMUP_ONLY_YEARS
        if extra:
            raise ExternalDiagFailClosed(f"{config_id}: unexpected years in output: {extra}")

    ledger_path = os.path.join(out_dir, f"{config_id.lower().replace('og_', '')}_trades.csv")
    by.to_csv(ledger_path, index=False)

    return summary, by, ledger_path


def evaluate_gate(by, years):
    """Fixed external-support gate (13 criteria, see
    docs/OG_EXTERNAL_2013_2015_PROTOCOL.md). Applied independently per config."""
    years = sorted(years)
    gate = {}
    n = len(by)
    pnl = by["pnl"] if n else pd.Series([], dtype=float)
    capr = (by["pnl"] / by["cap"]) if n else pd.Series([], dtype=float)

    pooled_net = float(pnl.sum()) if n else 0.0
    pooled_R = float(capr.sum()) if n else 0.0
    pf_pts = profit_factor(pnl) if n else 0.0
    pf_R = profit_factor(capr) if n else 0.0
    avg_R = float(capr.mean()) if n else 0.0

    per_year = {}
    for yr in years:
        sub = by[by["year"] == yr] if n else by
        yn = len(sub)
        ypnl = sub["pnl"] if yn else pd.Series([], dtype=float)
        ycapr = (sub["pnl"] / sub["cap"]) if yn else pd.Series([], dtype=float)
        per_year[yr] = {
            "n_trades": yn,
            "net_pts": float(ypnl.sum()) if yn else 0.0,
            "total_R": float(ycapr.sum()) if yn else 0.0,
            "PF_pts": profit_factor(ypnl) if yn else 0.0,
        }

    n_years_positive_R = sum(1 for yr in years if per_year[yr]["total_R"] > 0)
    n_years_pf_gt_1 = sum(1 for yr in years if per_year[yr]["PF_pts"] > 1.00)

    if years:
        best_yr = max(years, key=lambda yr: per_year[yr]["total_R"])
        R_excl_best = pooled_R - per_year[best_yr]["total_R"]
    else:
        best_yr, R_excl_best = None, 0.0

    positive_net_total = sum(max(per_year[yr]["net_pts"], 0.0) for yr in years)
    if positive_net_total > 0:
        max_year_share = max(max(per_year[yr]["net_pts"], 0.0) / positive_net_total for yr in years)
    else:
        max_year_share = None

    # criterion 13: pooled result not entirely supplied by one isolated month
    if n:
        by = by.copy()
        by["ym"] = by["session_date"].apply(lambda d: (pd.Timestamp(d).year, pd.Timestamp(d).month))
        month_net = by.groupby("ym")["pnl"].sum()
        pos_month_total = month_net[month_net > 0].sum()
        max_month_share = (month_net[month_net > 0].max() / pos_month_total) if pos_month_total > 0 else None
    else:
        max_month_share = None

    gate["3_pooled_net_positive"] = (pooled_net, pooled_net > 0)
    gate["4_pooled_R_positive"] = (pooled_R, pooled_R > 0)
    gate["5_pooled_PF_pts_ge_1.10"] = (pf_pts, pf_pts >= 1.10)
    gate["6_pooled_PF_R_gt_1.00"] = (pf_R, pf_R > 1.00)
    gate["7_avg_R_per_trade_positive"] = (avg_R, avg_R > 0)
    gate["8_at_least_2_of_3_years_positive_R"] = (n_years_positive_R, n_years_positive_R >= 2)
    gate["9_at_least_2_of_3_years_PF_pts_gt_1.00"] = (n_years_pf_gt_1, n_years_pf_gt_1 >= 2)
    gate["10_total_R_positive_excl_best_year"] = (R_excl_best, R_excl_best > 0)
    gate["11_at_least_150_eligible_trades"] = (n, n >= 150)
    gate["12_no_year_gt_80pct_of_positive_net"] = (
        max_year_share, (max_year_share is None) or (max_year_share <= 0.80))
    gate["13_no_single_month_entirely_supplies_result"] = (
        max_month_share, (max_month_share is None) or (max_month_share < 1.0))

    overall = all(v[1] for v in gate.values())
    return gate, per_year, overall


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", required=True)
    ap.add_argument("--config", action="append", required=True)
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)

    years = set(args.years)
    if years != EXTERNAL_YEARS:
        raise ExternalDiagFailClosed(
            f"--years must be exactly {sorted(EXTERNAL_YEARS)}, got {sorted(years)}")

    if len(args.config) != 2:
        raise ExternalDiagFailClosed("exactly two --config arguments required")

    bars_path = os.path.join(REPO_ROOT, args.bars) if not os.path.isabs(args.bars) else args.bars
    vxn_path = os.path.join(REPO_ROOT, args.vxn) if not os.path.isabs(args.vxn) else args.vxn
    if not os.path.exists(bars_path):
        raise ExternalDiagFailClosed(f"--bars file not found: {bars_path}")
    if not os.path.exists(vxn_path):
        raise ExternalDiagFailClosed(f"--vxn file not found: {vxn_path}")
    bars_hash = sha256_file(bars_path)
    vxn_hash = sha256_file(vxn_path)
    if bars_hash != EXPECTED_BARS_SHA256:
        raise ExternalDiagFailClosed(
            f"--bars sha256 {bars_hash} != expected {EXPECTED_BARS_SHA256}")
    if vxn_hash != EXPECTED_VXN_SHA256:
        raise ExternalDiagFailClosed(
            f"--vxn sha256 {vxn_hash} != expected {EXPECTED_VXN_SHA256}")

    configs = {}
    for path in args.config:
        cfg = load_config(path)
        configs[cfg["config_id"]] = (path, cfg)
    if set(configs.keys()) != set(EXPECTED_STATUS.keys()):
        raise ExternalDiagFailClosed(f"expected configs {set(EXPECTED_STATUS)}, got {set(configs.keys())}")

    (path_p, cfg_p) = configs["OG_PRIMARY_150R"]
    (path_s, cfg_s) = configs["OG_OPERATIONAL_100R"]
    assert_configs_only_differ_in_target_r(cfg_p, cfg_s, path_p, path_s)

    params = {
        "OG_PRIMARY_150R": resolve_effective_params(cfg_p),
        "OG_OPERATIONAL_100R": resolve_effective_params(cfg_s),
    }

    os.makedirs(args.out_dir, exist_ok=True)

    # Fail-closed: never mutate the committed config files. Bars/VXN paths
    # come only from --bars/--vxn; the config's own data.* fields are not
    # read for path resolution in this runner.
    bars = load_1m_ohlcv(bars_path)
    vxn = load_gvz_daily(vxn_path)

    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = bar_ranges(bars)
    lvls = list(levels.itertuples(index=False))
    events = physical_touches(bars, lvls)

    # First eligible traded date: first session date with an executed trade
    # (i.e. survived the anchor/level/VXN-warmup eligibility gate already
    # enforced inside generate_levels/physical_touches/run_variant_managed)
    # using the PRIMARY config's parameters (both configs share identical
    # eligibility mechanics; target_r only affects TP distance, not
    # eligibility).
    probe_summary, probe_ex_df, _ = run_one_config(
        "OG_PRIMARY_150R", params["OG_PRIMARY_150R"], bars, ranges, events,
        years, args.out_dir)
    if len(probe_ex_df):
        first_eligible_date = str(sorted(probe_ex_df["session_date"].unique())[0])
    else:
        first_eligible_date = None

    results = {}
    ledgers = {}
    for config_id in ("OG_PRIMARY_150R", "OG_OPERATIONAL_100R"):
        summary, by, ledger_path = run_one_config(
            config_id, params[config_id], bars, ranges, events, years, args.out_dir)
        ledgers[config_id] = by
        gate, per_year, overall = evaluate_gate(by, years)
        pooled = compute_block_metrics(config_id, by)
        yearly = {yr: compute_block_metrics(config_id, by[by["year"] == yr] if len(by) else by)
                  for yr in sorted(years)}
        results[config_id] = {
            "summary": summary,
            "n_trades": len(by),
            "pooled_metrics": pooled,
            "yearly_metrics": yearly,
            "gate": {k: {"value": v[0], "pass": bool(v[1])} for k, v in gate.items()},
            "per_year_gate_inputs": per_year,
            "overall_pass": overall,
            "ledger_path": os.path.relpath(ledger_path, REPO_ROOT),
        }

    p_pass = results["OG_PRIMARY_150R"]["overall_pass"]
    s_pass = results["OG_OPERATIONAL_100R"]["overall_pass"]
    if p_pass and s_pass:
        family = "EXTERNAL_DUAL_SUPPORT"
    elif p_pass:
        family = "EXTERNAL_PRIMARY_ONLY_SUPPORT"
    elif s_pass:
        family = "EXTERNAL_OPERATIONAL_ONLY_SUPPORT"
    else:
        family = "EXTERNAL_DUAL_NO_SUPPORT"

    out = {
        "years": sorted(years),
        "bars_file": args.bars, "bars_sha256": bars_hash,
        "vxn_file": args.vxn, "vxn_sha256": vxn_hash,
        "first_eligible_traded_date": first_eligible_date,
        "family_verdict": family,
        "diagnostic_only": True,
        "does_not_reverse_locked_validation": "DUAL_CONFIG_FAIL (commit add8f30)",
        "results": results,
    }
    with open(os.path.join(args.out_dir, "gate_results.json"), "w") as f:
        json.dump(out, f, indent=2, default=str)

    print(json.dumps({"family_verdict": family, "primary_pass": p_pass,
                       "secondary_pass": s_pass,
                       "first_eligible_traded_date": first_eligible_date}, indent=2))
    return out


if __name__ == "__main__":
    main()
