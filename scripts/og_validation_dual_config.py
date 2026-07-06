"""OG dual-config VALIDATION runner (Step 1 of OG_DUAL_VALIDATION_RUNNER_LOCK).

Reuses the exact frozen mechanics already locked for OG_PRIMARY_150R and
OG_OPERATIONAL_100R (src/strict_engine.py level generation / touch
detection, src/og_management_variants.py::run_variant_managed for the
chronological single-global-position state machine), and reports outcomes
filtered to the validation year set {2019, 2021, 2022, 2024, 2025} instead
of the build years {2018, 2020, 2023, 2026}. It does NOT re-derive levels,
touches, or any mechanic -- see docs/OG_VALIDATION_PROTOCOL_DUAL_CONFIG.md.

FAIL-CLOSED requirements enforced here (raise + nonzero exit, never warn):
  - required config fields must be present
  - config status label must exactly match the expected locked label
  - config's introducing/source commit must be the lock commit or an
    ancestor of it
  - config's recorded data hashes must match the actual committed files
  - --years must be exactly {2019,2021,2022,2024,2025}
  - no build year (2018/2020/2023/2026) may appear in any output
  - the two configs may only differ in target.target_r
  - any invariant test failure aborts before producing final output

Exact reproduction command (Step 4 of the task):
    python3 scripts/og_validation_dual_config.py \\
        --years 2019 2021 2022 2024 2025 \\
        --config configs/OG_PRIMARY_150R.yaml \\
        --config configs/OG_OPERATIONAL_100R.yaml \\
        --out-dir outputs/og_validation/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import subprocess
import sys

import pandas as pd
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.og_build_variant_engine import filter_build_years, in_prop_hard_blackout
from src.og_management_variants import run_variant_managed
from src.metrics import profit_factor, max_drawdown

CACHE = os.path.join(REPO_ROOT, "outputs", "og_build_years", "_cache.pkl")

LOCK_COMMIT = "dad3da69aad401243544f80974f6d7506fefb7e2"
VALIDATION_YEARS = frozenset({2019, 2021, 2022, 2024, 2025})
BUILD_YEARS = frozenset({2018, 2020, 2023, 2026})
BANNED_YEARS = frozenset({2013, 2014, 2015})

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

# Params that must be byte-identical between the two configs (everything
# except target.target_r / target.lane / target.note, which are the
# deliberate single axis of difference, and free-text/comment-only fields).
COMPARE_KEYS = [
    "data", "level_generation", "stop_calc", "one_global_position", "no_overlap",
    "no_stacking", "no_same_minute_reentry", "permanent_touch_consumption",
    "tie_order", "intrabar_ambiguity", "forced_liquidation_time_et",
    "prop_hard_blackout", "entry_blackout", "sal_enabled", "management", "hmm_gate",
]


class ValidationFailClosed(RuntimeError):
    """Raised for any fail-closed condition. Must propagate to a nonzero exit."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_is_ancestor(candidate_sha, descendant_sha, cwd=REPO_ROOT):
    """True if candidate_sha is an ancestor of (or equal to) descendant_sha."""
    if candidate_sha == descendant_sha:
        return True
    r = subprocess.run(
        ["git", "merge-base", "--is-ancestor", candidate_sha, descendant_sha],
        cwd=cwd,
    )
    return r.returncode == 0


def load_config(path):
    with open(path) as f:
        cfg = yaml.safe_load(f)
    missing = [k for k in REQUIRED_FIELDS if k not in cfg]
    if missing:
        raise ValidationFailClosed(f"{path}: missing required config field(s): {missing}")

    config_id = cfg["config_id"]
    if config_id not in EXPECTED_STATUS:
        raise ValidationFailClosed(f"{path}: unknown config_id {config_id!r}")
    if cfg["status"] != EXPECTED_STATUS[config_id]:
        raise ValidationFailClosed(
            f"{path}: status label mismatch. expected "
            f"{EXPECTED_STATUS[config_id]!r}, got {cfg['status']!r}")

    introducing_commit = cfg.get("source", {}).get("introducing_commit")
    if not introducing_commit:
        raise ValidationFailClosed(f"{path}: source.introducing_commit missing")
    if not git_is_ancestor(introducing_commit, LOCK_COMMIT):
        raise ValidationFailClosed(
            f"{path}: source.introducing_commit {introducing_commit} is not "
            f"the lock commit {LOCK_COMMIT} or an ancestor of it")

    # Data hash checks against the actual committed files.
    data = cfg["data"]
    bars_path = os.path.join(REPO_ROOT, data["bars_file"])
    vxn_path = os.path.join(REPO_ROOT, data["vxn_file"])
    bars_hash = sha256_file(bars_path)
    vxn_hash = sha256_file(vxn_path)
    expected_bars_hashes = {
        data.get("bars_sha256_manifest"),
        data.get("bars_sha256_reconstructed_verified_harmless"),
    }
    if bars_hash not in expected_bars_hashes:
        raise ValidationFailClosed(
            f"{path}: bars file sha256 {bars_hash} does not match either "
            f"recorded hash {expected_bars_hashes}")
    if vxn_hash != data.get("vxn_sha256"):
        raise ValidationFailClosed(
            f"{path}: vxn file sha256 {vxn_hash} != recorded {data.get('vxn_sha256')}")

    # Expected build-ledger sanity check (points at real, unchanged artifacts).
    ledger = cfg["expected_build_ledger"]
    ledger_path = os.path.join(REPO_ROOT, ledger["path"])
    if not os.path.exists(ledger_path):
        raise ValidationFailClosed(f"{path}: expected_build_ledger path missing: {ledger_path}")
    ledger_hash = sha256_file(ledger_path)
    if ledger_hash != ledger["sha256"]:
        raise ValidationFailClosed(
            f"{path}: expected_build_ledger sha256 mismatch. expected "
            f"{ledger['sha256']}, got {ledger_hash}")
    ledger_df = pd.read_csv(ledger_path)
    if len(ledger_df) != ledger["n_rows"]:
        raise ValidationFailClosed(
            f"{path}: expected_build_ledger n_rows mismatch. expected "
            f"{ledger['n_rows']}, got {len(ledger_df)}")

    return cfg


def assert_configs_only_differ_in_target_r(cfg_a, cfg_b, path_a, path_b):
    for key in COMPARE_KEYS:
        if cfg_a.get(key) != cfg_b.get(key):
            raise ValidationFailClosed(
                f"{path_a} and {path_b} differ in {key!r} (must be identical "
                f"except target.target_r): {cfg_a.get(key)!r} != {cfg_b.get(key)!r}")
    ta, tb = cfg_a["target"], cfg_b["target"]
    if ta.get("target_r") == tb.get("target_r"):
        raise ValidationFailClosed(
            "configs have identical target_r; expected exactly one axis of "
            "difference (target.target_r)")


def resolve_effective_params(cfg):
    """Resolve every effective engine parameter from the config explicitly.
    No silent defaults for anything the config doesn't specify."""
    mgmt = cfg["management"]
    if mgmt.get("mode") != "barcount":
        raise ValidationFailClosed(f"unsupported management.mode {mgmt.get('mode')!r}")
    if "be_bars" not in mgmt:
        raise ValidationFailClosed("management.be_bars missing")
    if mgmt.get("be_extra_lock", None) != 0.0:
        raise ValidationFailClosed(
            "management.be_extra_lock must be 0.0 (exact breakeven, "
            "canonical BE45) -- runner does not support nonzero lock")
    if cfg["hmm_gate"].get("enabled"):
        raise ValidationFailClosed("hmm_gate.enabled=true is not supported by this runner")
    if cfg["sal_enabled"] is not False:
        raise ValidationFailClosed("sal_enabled must be false")
    if cfg["tie_order"] != "age":
        raise ValidationFailClosed("tie_order must be 'age'")
    win = cfg["entry_blackout"]["blocked_window_minutes"]
    target_r = cfg["target"]["target_r"]
    if target_r is None:
        raise ValidationFailClosed("target.target_r missing")
    return {
        "be_bars": int(mgmt["be_bars"]),
        "blocked_window": (int(win[0]), int(win[1])),
        "target_r": float(target_r),
    }


def compute_year_row(label, sub, yr_label, n_years=1.0):
    n = len(sub)
    pnl = sub["pnl"]
    capr = sub["pnl"] / sub["cap"]
    return {
        "config": label, "year": yr_label, "n_trades": n,
        "net_pts": round(float(pnl.sum()), 2) if n else 0.0,
        "PF_pts": round(profit_factor(pnl), 4) if n else None,
        "PF_R": round(profit_factor(capr), 4) if n else None,
        "cap_norm_R_total": round(float(capr.sum()), 4) if n else 0.0,
        "avg_R_per_trade": round(float(capr.mean()), 4) if n else 0.0,
        "win_rate": round(float((pnl > 0).mean()), 4) if n else 0.0,
        "positive_net_pts": bool(pnl.sum() > 0) if n else False,
    }


def run_one_config(config_id, params, bars, ranges, events, years, out_dir):
    summary, ex_df = run_variant_managed(
        bars, ranges, events,
        mgmt_kwargs=dict(mode="barcount", be_bars=params["be_bars"], target_r=params["target_r"]),
        sal_enabled=False, blocked_window=params["blocked_window"], hmm_gate=None)

    if len(ex_df):
        bad_entry = ex_df["entry_time"].apply(in_prop_hard_blackout).any()
        bad_exit = ex_df["exit_time"].apply(in_prop_hard_blackout).any()
        if bad_entry or bad_exit:
            raise ValidationFailClosed(f"{config_id}: PROP_HARD_BLACKOUT violated")

    # Firewall: filter to exactly the requested validation years.
    by = filter_build_years(ex_df, years=years)
    if by is None or (len(by) == 0 and "year" not in by.columns):
        by = pd.DataFrame(columns=[
            "level_id", "session_date", "year", "side", "entry_time", "exit_time",
            "entry_price", "exit_price", "level", "anchor", "cap",
            "exit_reason", "pnl", "gap_through",
        ])

    if by is not None and len(by):
        leaked_build = set(by["year"].unique()) & BUILD_YEARS
        if leaked_build:
            raise ValidationFailClosed(f"{config_id}: build years leaked into validation output: {leaked_build}")
        leaked_banned = set(by["year"].unique()) & BANNED_YEARS
        if leaked_banned:
            raise ValidationFailClosed(f"{config_id}: banned years leaked into validation output: {leaked_banned}")
        extra = set(by["year"].unique()) - set(years)
        if extra:
            raise ValidationFailClosed(f"{config_id}: unexpected years in validation output: {extra}")

    ledger_path = os.path.join(out_dir, f"{config_id}_validation_trades.csv")
    by.to_csv(ledger_path, index=False)

    rows = []
    for yr in sorted(years):
        sub = by[by["year"] == yr] if len(by) else by
        rows.append(compute_year_row(config_id, sub, yr))
    rows.append(compute_year_row(config_id, by, "pooled_validation_years", n_years=len(years)))
    metrics_df = pd.DataFrame(rows)
    metrics_path = os.path.join(out_dir, f"{config_id}_validation_metrics.csv")
    metrics_df.to_csv(metrics_path, index=False)

    return summary, by, metrics_df


def evaluate_gate(by, years):
    """Apply the locked §4 gate (docs/OG_VALIDATION_PROTOCOL_DUAL_CONFIG.md)
    to a single config's validation-year ledger. Returns dict of criterion
    -> (value, passed)."""
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
    n_years_pf_gt_105 = sum(1 for yr in years if per_year[yr]["PF_pts"] > 1.05)

    # criterion 9: total R excluding best validation year (best by total_R)
    if years:
        best_yr = max(years, key=lambda yr: per_year[yr]["total_R"])
        R_excl_best = pooled_R - per_year[best_yr]["total_R"]
    else:
        best_yr, R_excl_best = None, 0.0

    # criterion 11: no single year > 80% of pooled positive net points
    positive_net_total = sum(max(per_year[yr]["net_pts"], 0.0) for yr in years)
    if positive_net_total > 0:
        max_year_share = max(max(per_year[yr]["net_pts"], 0.0) / positive_net_total for yr in years)
    else:
        max_year_share = None

    gate["2_pooled_net_positive"] = (pooled_net, pooled_net > 0)
    gate["3_pooled_R_positive"] = (pooled_R, pooled_R > 0)
    gate["4_pooled_PF_pts_ge_1.15"] = (pf_pts, pf_pts >= 1.15)
    gate["5_pooled_PF_R_ge_1.05"] = (pf_R, pf_R >= 1.05)
    gate["6_avg_R_per_trade_positive"] = (avg_R, avg_R > 0)
    gate["7_at_least_3_of_5_years_positive_R"] = (n_years_positive_R, n_years_positive_R >= 3)
    gate["8_at_least_3_of_5_years_PF_pts_gt_1.05"] = (n_years_pf_gt_105, n_years_pf_gt_105 >= 3)
    gate["9_total_R_positive_excl_best_year"] = (R_excl_best, R_excl_best > 0)
    gate["10_at_least_250_trades"] = (n, n >= 250)
    gate["11_no_year_gt_80pct_of_positive_net"] = (
        max_year_share, (max_year_share is None) or (max_year_share <= 0.80))

    overall = all(v[1] for v in gate.values())
    return gate, per_year, overall


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", required=True)
    ap.add_argument("--config", action="append", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)

    years = set(args.years)
    if years != VALIDATION_YEARS:
        raise ValidationFailClosed(
            f"--years must be exactly {sorted(VALIDATION_YEARS)}, got {sorted(years)}")
    if years & BANNED_YEARS:
        raise ValidationFailClosed(f"--years must never include {sorted(BANNED_YEARS)}")

    if len(args.config) != 2:
        raise ValidationFailClosed("exactly two --config arguments required")

    configs = {}
    for path in args.config:
        cfg = load_config(path)
        configs[cfg["config_id"]] = (path, cfg)

    if set(configs.keys()) != set(EXPECTED_STATUS.keys()):
        raise ValidationFailClosed(f"expected configs {set(EXPECTED_STATUS)}, got {set(configs.keys())}")

    (path_p, cfg_p) = configs["OG_PRIMARY_150R"]
    (path_s, cfg_s) = configs["OG_OPERATIONAL_100R"]
    assert_configs_only_differ_in_target_r(cfg_p, cfg_s, path_p, path_s)

    params = {
        "OG_PRIMARY_150R": resolve_effective_params(cfg_p),
        "OG_OPERATIONAL_100R": resolve_effective_params(cfg_s),
    }

    os.makedirs(args.out_dir, exist_ok=True)

    if not os.path.exists(CACHE):
        raise ValidationFailClosed(f"required cache not found: {CACHE}")
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]

    results = {}
    for config_id in ("OG_PRIMARY_150R", "OG_OPERATIONAL_100R"):
        summary, by, metrics_df = run_one_config(
            config_id, params[config_id], bars, ranges, events, years, args.out_dir)
        gate, per_year, overall = evaluate_gate(by, years)
        results[config_id] = {
            "summary": summary,
            "n_validation_trades": len(by),
            "gate": {k: {"value": v[0], "pass": bool(v[1])} for k, v in gate.items()},
            "per_year": per_year,
            "overall_pass": overall,
        }

    p_pass = results["OG_PRIMARY_150R"]["overall_pass"]
    s_pass = results["OG_OPERATIONAL_100R"]["overall_pass"]
    if p_pass and s_pass:
        family = "DUAL_CONFIG_FAMILY_PASS"
    elif p_pass:
        family = "PRIMARY_ONLY_PASS"
    elif s_pass:
        family = "SECONDARY_ONLY_PASS"
    else:
        family = "DUAL_CONFIG_FAIL"

    out = {
        "years": sorted(years),
        "family_verdict": family,
        "results": results,
    }
    with open(os.path.join(args.out_dir, "validation_gate_results.json"), "w") as f:
        json.dump(out, f, indent=2, default=str)

    print(json.dumps({"family_verdict": family,
                       "primary_pass": p_pass, "secondary_pass": s_pass}, indent=2))
    return out


if __name__ == "__main__":
    main()
