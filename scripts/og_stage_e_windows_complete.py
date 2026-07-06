"""Stage E completion: blocked-entry-interval / session-entry study.

Supersedes the earlier, insufficient docs/OG_STAGE_E_WINDOWS.md pass. Holds
constant: SAL off (Stage B freeze), BE60 management (Stage C final --
mode="barcount", be_bars=60, via src.og_management_variants.run_variant_managed,
NOT reimplemented here), no HMM gate (Stage D freeze), target fixed at 1.0R
(cap = min(1.5*anchor, SL_CAP), unchanged), forced liquidation 15:00 ET
(session_cutoff(), unchanged), PROP_HARD_BLACKOUT (16:00-19:00 ET) always on
and unconditional (src/og_build_variant_engine.py::in_prop_hard_blackout,
checked inside run_variant_managed itself).

The variable under test is a BLOCKED ENTRY INTERVAL: entries are blocked from
a start time until a cutoff (start-until-15:00 for the primary candidates;
the redundant until-16:00 labels are included only to demonstrate they are
numerically identical, since forced liquidation at 15:00 already prevents any
entry after that time regardless of the stated blackout end). This is never
described as an "allowed trading window."

Session-entry variants use the hmm_gate hook (a plain callable(ts) -> bool,
independent of blocked_window) purely as a session-membership gate -- no HMM
model is involved. blocked_window is set to (0, 0) for these, which is a
structural no-op given entry_allowed_window's semantics (0 <= m < 0 is never
true, so nothing is blocked by that path); PROP_HARD_BLACKOUT and the 15:00
cutoff still apply unconditionally underneath.

Outputs:
  outputs/og_build_years/stage_e_window_complete.csv
  outputs/og_build_years/stage_e_window_complete_raw.json
  docs/OG_STAGE_E_WINDOWS_COMPLETE.md (written separately)
"""
import json
import os
import pickle
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.og_build_variant_engine import filter_build_years, in_prop_hard_blackout, ET
from src.og_management_variants import run_variant_managed
from src.metrics import profit_factor, max_drawdown

CACHE = os.path.join(REPO_ROOT, "outputs", "og_build_years", "_cache.pkl")
OUT = os.path.join(REPO_ROOT, "outputs", "og_build_years")

MGMT_KWARGS = dict(mode="barcount", be_bars=60)  # Stage C final (BE60_CONFIRMED)
NOOP_WINDOW = (0, 0)  # structurally never blocks via entry_allowed_window


# ---------------------------------------------------------------------------
# Session-membership gates (ET minutes-since-midnight; wraps midnight where
# start > end). Session definitions (not found predefined elsewhere in
# docs/ -- checked docs/OG_STAGE_E_WINDOWS.md, docs/OG_PROP_HARD_BLACKOUT.md,
# docs/OG_CONFIG_LIVE_RULES.md; none define Asia/London/NY session boundaries,
# so we define them here per the task spec and state that explicitly):
#   Asia:     19:00-03:00 ET
#   London:   03:00-08:00 ET
#   New York: 08:00-16:00 ET
ASIA = (19 * 60, 3 * 60)
LONDON = (3 * 60, 8 * 60)
NY = (8 * 60, 16 * 60)
NY_PRE10 = (8 * 60, 10 * 60)


def _in_range(m, start, end):
    if start <= end:
        return start <= m < end
    return m >= start or m < end


def _m(ts):
    et = ts.tz_convert(ET)
    return et.hour * 60 + et.minute


def gate_union(*ranges):
    def f(ts):
        m = _m(ts)
        return any(_in_range(m, s, e) for s, e in ranges)
    return f


def gate_blocked_interval(blocked_start_min, blocked_end_min):
    """Control-style gate: allow everything EXCEPT [blocked_start_min,
    blocked_end_min) -- used for the 'all-canonical-permitted-hours' control
    candidate, expressed as a session-style gate for uniform handling."""
    def f(ts):
        m = _m(ts)
        return not _in_range(m, blocked_start_min, blocked_end_min)
    return f


# ---------------------------------------------------------------------------
# Candidate definitions.

def mins(h, mm=0):
    return h * 60 + mm


INTERVAL_STARTS = [
    ("0900", mins(9, 0)),
    ("0930", mins(9, 30)),
    ("1000", mins(10, 0)),
    ("1030", mins(10, 30)),
    ("1100", mins(11, 0)),   # canonical
    ("1130", mins(11, 30)),
    ("1200", mins(12, 0)),
]

CUTOFF_15 = mins(15, 0)
CUTOFF_16 = mins(16, 0)

SESSION_CANDIDATES = {
    "asia_only": gate_union(ASIA),
    "london_only": gate_union(LONDON),
    "ny_pre10_only": gate_union(NY_PRE10),
    "asia_or_london": gate_union(ASIA, LONDON),
    "asia_or_ny_pre10": gate_union(ASIA, NY_PRE10),
    "london_or_ny_pre10": gate_union(LONDON, NY_PRE10),
    "all_canonical_permitted_hours": gate_blocked_interval(mins(11, 0), mins(15, 0)),  # control
}


def hold_time_minutes(sub):
    dt = (pd.to_datetime(sub["exit_time"]) - pd.to_datetime(sub["entry_time"])).dt.total_seconds() / 60.0
    return dt


def compute_full_metrics(label, by):
    if by is None or len(by) == 0:
        return []
    by = by.copy()
    by["cap_norm_pnl"] = by["pnl"] / by["cap"]
    by["hold_min"] = hold_time_minutes(by)

    def yr_row(sub, yr_label, n_years=1):
        n = len(sub)
        pnl = sub["pnl"]
        capr = sub["cap_norm_pnl"]
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        avg_w = float(wins.mean()) if len(wins) else 0.0
        avg_l = float(losses.mean()) if len(losses) else 0.0
        payoff = (avg_w / abs(avg_l)) if avg_l not in (0, None) and avg_l != 0 else None
        exit_counts = sub["exit_reason"].value_counts().to_dict()
        hm = sub["hold_min"]
        return {
            "candidate": label, "year": yr_label, "n_trades": n,
            "net_pts": round(float(pnl.sum()), 2),
            "PF_pts": round(profit_factor(pnl), 4),
            "avg_pts_per_trade": round(float(pnl.mean()), 3) if n else 0.0,
            "cap_norm_R_total": round(float(capr.sum()), 4),
            "cap_norm_R_avg": round(float(capr.mean()), 4) if n else 0.0,
            "max_dd_pts": round(max_drawdown(pnl), 2) if n else 0.0,
            "max_dd_R": round(max_drawdown(capr), 4) if n else 0.0,
            "win_rate": round(float((pnl > 0).mean()), 4) if n else 0.0,
            "avg_winner_pts": round(avg_w, 3),
            "avg_loser_pts": round(avg_l, 3),
            "payoff_ratio": round(payoff, 3) if payoff is not None else None,
            "n_TP": int(exit_counts.get("TP", 0)),
            "n_SL": int(exit_counts.get("SL", 0)),
            "n_BE": int(exit_counts.get("BE", 0) + exit_counts.get("LOCK", 0) + exit_counts.get("SCRATCH", 0)),
            "n_cutoff": int(exit_counts.get("cutoff", 0)),
            "trades_per_year": round(n / n_years, 2),
            "hold_median_min": round(float(hm.median()), 1) if n else None,
            "hold_mean_min": round(float(hm.mean()), 1) if n else None,
            "hold_p25_min": round(float(hm.quantile(.25)), 1) if n else None,
            "hold_p75_min": round(float(hm.quantile(.75)), 1) if n else None,
        }

    rows = []
    for yr in sorted(by["year"].unique()):
        sub = by[by["year"] == yr]
        rows.append(yr_row(sub, int(yr)))
    rows.append(yr_row(by, "ALL", n_years=4))
    ex2026 = by[by["year"] != 2026]
    if len(ex2026):
        rows.append(yr_row(ex2026, "ALL_ex2026", n_years=3))
    yearly_net = by.groupby("year")["pnl"].sum()
    if len(yearly_net) > 1:
        best_year = yearly_net.idxmax()
        ex_best = by[by["year"] != best_year]
        rows.append(yr_row(ex_best, f"ALL_ex_best_year({int(best_year)})", n_years=len(yearly_net) - 1))
    return rows


def run_candidate(bars, ranges, events, *, blocked_window=NOOP_WINDOW, hmm_gate=None):
    summary, ex_df = run_variant_managed(
        bars, ranges, events, mgmt_kwargs=MGMT_KWARGS, sal_enabled=False,
        blocked_window=blocked_window, hmm_gate=hmm_gate)
    by = filter_build_years(ex_df)
    return summary, by


def verify_hard_blackout(label, by):
    if by is None or len(by) == 0:
        return True
    bad_entry = by["entry_time"].apply(in_prop_hard_blackout).any()
    bad_exit = by["exit_time"].apply(in_prop_hard_blackout).any()
    if bad_entry or bad_exit:
        raise AssertionError(f"PROP_HARD_BLACKOUT violated for candidate {label}")
    return True


def main():
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]

    all_rows = []
    raw = {}
    trades_by_label = {}

    # --- Primary candidates: blocked-until-15:00, 7 starts -------------------
    for name, start in INTERVAL_STARTS:
        label = f"blocked_{name}_until1500"
        summary, by = run_candidate(bars, ranges, events, blocked_window=(start, CUTOFF_15))
        verify_hard_blackout(label, by)
        trades_by_label[label] = by
        by.to_csv(os.path.join(OUT, f"stage_e_complete_{label}_build_years_trades.csv"), index=False)
        rows = compute_full_metrics(label, by)
        all_rows.extend(rows)
        raw[label] = {"blocked_window": (start, CUTOFF_15), "summary": summary, "n": int(len(by))}
        print(label, "n=", len(by), "net=", round(float(by["pnl"].sum()), 2) if len(by) else 0)

    # --- Redundant until-16:00 labels, 7 starts (verify identical to above) -
    dedup_report = []
    for name, start in INTERVAL_STARTS:
        label15 = f"blocked_{name}_until1500"
        label16 = f"blocked_{name}_until1600"
        summary, by = run_candidate(bars, ranges, events, blocked_window=(start, CUTOFF_16))
        verify_hard_blackout(label16, by)
        trades_by_label[label16] = by
        by.to_csv(os.path.join(OUT, f"stage_e_complete_{label16}_build_years_trades.csv"), index=False)

        by15 = trades_by_label[label15]
        cols = ["level_id", "session_date", "side", "entry_time", "exit_time",
                "entry_price", "exit_price", "exit_reason", "pnl"]
        identical = (len(by) == len(by15)) and by.reset_index(drop=True)[cols].equals(
            by15.reset_index(drop=True)[cols])
        dedup_report.append({"start": name, "identical_to_1500": bool(identical),
                              "n_1500": int(len(by15)), "n_1600": int(len(by))})
        print(f"dedup check {name}: identical={identical} (n15={len(by15)}, n16={len(by)})")

        raw[label16] = {"blocked_window": (start, CUTOFF_16), "summary": summary,
                         "n": int(len(by)), "identical_to_until1500": bool(identical)}
        # Always include the until1600 row in the full candidate table (even
        # though it is numerically identical to its until1500 counterpart,
        # per the task spec's requirement for all 21 candidate rows); this
        # is the ONE place a redundant/duplicate row is intentionally kept.
        rows = compute_full_metrics(label16, by)
        all_rows.extend(rows)

    # --- Session-entry variants, 7 candidates --------------------------------
    for label, gate in SESSION_CANDIDATES.items():
        summary, by = run_candidate(bars, ranges, events, blocked_window=NOOP_WINDOW, hmm_gate=gate)
        verify_hard_blackout(label, by)
        trades_by_label[label] = by
        by.to_csv(os.path.join(OUT, f"stage_e_complete_{label}_build_years_trades.csv"), index=False)
        rows = compute_full_metrics(label, by)
        all_rows.extend(rows)
        raw[label] = {"session_gate": label, "summary": summary, "n": int(len(by))}
        print(label, "n=", len(by), "net=", round(float(by["pnl"].sum()), 2) if len(by) else 0)

    # Cross-check the control session candidate against the canonical 1100 row
    ctrl = trades_by_label["all_canonical_permitted_hours"]
    canon = trades_by_label["blocked_1100_until1500"]
    cols = ["level_id", "session_date", "side", "entry_time", "exit_time",
            "entry_price", "exit_price", "exit_reason", "pnl"]
    ctrl_identical = (len(ctrl) == len(canon)) and ctrl.reset_index(drop=True)[cols].equals(
        canon.reset_index(drop=True)[cols])
    print("control-vs-canonical identical:", ctrl_identical)
    raw["_control_vs_canonical_identical"] = bool(ctrl_identical)
    raw["_dedup_report"] = dedup_report

    df = pd.DataFrame(all_rows)
    df.to_csv(os.path.join(OUT, "stage_e_window_complete.csv"), index=False)
    with open(os.path.join(OUT, "stage_e_window_complete_raw.json"), "w") as f:
        json.dump(raw, f, indent=2, default=str)
    print("\nWrote outputs/og_build_years/stage_e_window_complete.csv")

    # --- Selection: pick the best provisional blocked-interval start by    --
    # --- full-year-ex-2026 PF among the 7 "until1500" candidates, subject  --
    # --- to all/most build years positive and no isolated cliff-edge.      --
    interval_labels = [f"blocked_{name}_until1500" for name, _ in INTERVAL_STARTS]
    ex2026_pf = {}
    year_pos_count = {}
    for lbl in interval_labels:
        by = trades_by_label[lbl]
        ex2026 = by[by["year"] != 2026]
        ex2026_pf[lbl] = profit_factor(ex2026["pnl"]) if len(ex2026) else 0.0
        yearly_net = by.groupby("year")["pnl"].sum()
        year_pos_count[lbl] = int((yearly_net > 0).sum())
    # Rank by ex2026 PF, restricted to candidates with >=3/4 years positive
    # if any qualify; else fall back to the full ranked list.
    qualifying = [l for l in interval_labels if year_pos_count[l] >= 3]
    pool = qualifying if qualifying else interval_labels
    # Diagnostic-only: flag candidates whose immediate left/right neighbor
    # (30-min step) differs by more than 20% relative ex2026 PF. This does
    # NOT override selection (see docs/OG_STAGE_E_WINDOWS_COMPLETE.md's
    # "Selection" section for the full stated standard, which treats
    # "not an isolated cliff-edge" as "flanked by still-profitable,
    # gradually-declining neighbors" rather than a hard relative-PF cutoff),
    # but is reported for transparency.
    ordered_names = [n for n, _ in INTERVAL_STARTS]

    def cliff_adjacent(lbl, rel_thresh=0.20):
        name = lbl.replace("blocked_", "").replace("_until1500", "")
        i = ordered_names.index(name)
        pf = ex2026_pf[lbl]
        for j in (i - 1, i + 1):
            if 0 <= j < len(ordered_names):
                nbr_lbl = f"blocked_{ordered_names[j]}_until1500"
                nbr_pf = ex2026_pf[nbr_lbl]
                if nbr_pf == 0:
                    continue
                if abs(pf - nbr_pf) / nbr_pf > rel_thresh:
                    return True
        return False

    cliff_flags = {l: cliff_adjacent(l) for l in interval_labels}
    best_label = max(pool, key=lambda l: ex2026_pf[l])
    best_start_name = best_label.replace("blocked_", "").replace("_until1500", "")
    best_start_min = dict(INTERVAL_STARTS)[best_start_name]
    print(f"Cliff flags by candidate (diagnostic only, >20% rel PF vs immediate neighbor): {cliff_flags}")
    print(f"\nSelected provisional best blocked-interval start: {best_start_name} "
          f"({best_start_min} min) -- ex2026 PF={ex2026_pf[best_label]:.4f}, "
          f"years_positive={year_pos_count[best_label]}/4, "
          f"cliff_adjacent={cliff_flags[best_label]} (see doc for full rationale)")
    raw["_selection"] = {
        "cliff_flags_by_candidate": cliff_flags,
        "best_label": best_label, "best_start_min": best_start_min,
        "ex2026_pf_by_candidate": ex2026_pf, "years_positive_by_candidate": year_pos_count,
    }
    with open(os.path.join(OUT, "stage_e_window_complete_raw.json"), "w") as f:
        json.dump(raw, f, indent=2, default=str)

    # --- Window perturbation around the selected provisional best ----------
    perturb_rows = []
    perturb_raw = {}
    base_start = best_start_min
    for delta_name, delta in [("start-60", -60), ("start-30", -30), ("start", 0),
                               ("start+30", 30), ("start+60", 60)]:
        start = base_start + delta
        label = f"perturb_{delta_name}"
        summary, by = run_candidate(bars, ranges, events, blocked_window=(start, CUTOFF_15))
        verify_hard_blackout(label, by)
        by.to_csv(os.path.join(OUT, f"stage_e_complete_{label}_build_years_trades.csv"), index=False)
        rows = compute_full_metrics(label, by)
        perturb_rows.extend(rows)
        perturb_raw[label] = {"blocked_start_min": start, "summary": summary, "n": int(len(by))}
        print(label, "start_min=", start, "n=", len(by),
              "net=", round(float(by["pnl"].sum()), 2) if len(by) else 0)

    pdf = pd.DataFrame(perturb_rows)
    pdf.to_csv(os.path.join(OUT, "stage_e_window_perturbation.csv"), index=False)
    with open(os.path.join(OUT, "stage_e_window_perturbation_raw.json"), "w") as f:
        json.dump(perturb_raw, f, indent=2, default=str)
    print("Wrote outputs/og_build_years/stage_e_window_perturbation.csv")


if __name__ == "__main__":
    main()
