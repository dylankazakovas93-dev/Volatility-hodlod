"""
Stage-A invariant checks for the OG_CONFIG_CLEAN_BASELINE (canonical commit
a375818056ca435df021d60b111f5f58b1f3551f).

IMPORTANT SCOPE NOTE: the canonical NQ 1-minute bars file
(data/nq_1m/nq_continuous_2018_2026_1m.csv, ~211MB) is not present in this
repository or execution environment (see docs/OG_STAGE_A_VERIFICATION_REPORT.md,
section "Data verification"). Because the engines cannot be executed without
this file, the dynamic/adversarial tests that require re-running the engine
(causality/truncation test, retry-after-consumed-touch test, forced-liquidation
test, SAL transition test under mutated inputs) CANNOT be performed and are
NOT included here -- doing so would require fabricating or substituting data,
which is explicitly disallowed by the Stage-A instructions.

What IS tested here, using only the pre-existing, already-committed ledger
files at the canonical commit (outputs/baseline_executed.csv,
outputs/baseline_skipped.csv, outputs/engine_comparison.json):

  1. No-overlap invariant: no executed trade's entry_time occurs before the
     exit_time of the immediately preceding trade (when sorted by entry_time).
  2. No same-minute re-entry: no executed trade enters in the exact same
     minute as the prior trade's exit.
  3. Exit-reason / skip-reason totals reconcile with baseline_summary.json.
  4. Two independently-coded engines (strict_engine.py vs
     independent_strict_engine.py) produced byte-for-byte identical trade
     ledgers, per the pre-existing outputs/engine_comparison.json artifact.
  5. Headline metrics recomputed directly from the trade ledger CSV match
     the pre-existing outputs/baseline_summary.json headline numbers.

These are verification tests of the artifacts already checked into the
canonical commit -- they are NOT independent re-execution of the engine
(that is blocked; see report).
"""
import csv
import json
import os
from collections import Counter
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXECUTED_CSV = os.path.join(REPO_ROOT, "outputs", "baseline_executed.csv")
SKIPPED_CSV = os.path.join(REPO_ROOT, "outputs", "baseline_skipped.csv")
SUMMARY_JSON = os.path.join(REPO_ROOT, "outputs", "baseline_summary.json")
COMPARISON_JSON = os.path.join(REPO_ROOT, "outputs", "engine_comparison.json")


def _load_executed():
    with open(EXECUTED_CSV) as f:
        return list(csv.DictReader(f))


def test_data_file_absent_documented():
    """Confirms (does not silently paper over) that the canonical bars file
    is absent, which is why only ledger-level checks run here."""
    bars_path = os.path.join(REPO_ROOT, "data", "nq_1m", "nq_continuous_2018_2026_1m.csv")
    assert not os.path.exists(bars_path), (
        "Canonical bars file now present -- Stage A should be re-run with full "
        "dynamic/adversarial engine tests, this static-only test suite is stale."
    )


def test_no_overlap_invariant():
    rows = _load_executed()
    parsed = [
        (datetime.fromisoformat(r["entry_time"]), datetime.fromisoformat(r["exit_time"]), r)
        for r in rows
    ]
    parsed.sort(key=lambda x: x[0])
    prev_exit = None
    violations = []
    for et, xt, r in parsed:
        if prev_exit is not None and et < prev_exit:
            violations.append((r["level_id"], str(et), str(prev_exit)))
        prev_exit = xt if prev_exit is None else max(prev_exit, xt)
    assert violations == [], f"Overlap violations found: {violations[:5]}"


def test_no_same_minute_reentry():
    rows = _load_executed()
    parsed = [
        (datetime.fromisoformat(r["entry_time"]), datetime.fromisoformat(r["exit_time"]), r)
        for r in rows
    ]
    parsed.sort(key=lambda x: x[0])
    prev_exit = None
    violations = []
    for et, xt, r in parsed:
        if prev_exit is not None and et == prev_exit:
            violations.append((r["level_id"], str(et)))
        prev_exit = xt if prev_exit is None else max(prev_exit, xt)
    assert violations == [], f"Same-minute re-entry violations found: {violations[:5]}"


def test_exit_reason_counts_match_summary():
    rows = _load_executed()
    counts = Counter(r["exit_reason"] for r in rows)
    with open(SUMMARY_JSON) as f:
        summary = json.load(f)["result"]
    assert counts["TP"] == summary["TP"]
    assert counts["SL"] == summary["SL"]
    assert counts["BE"] == summary["BE"]
    assert counts["cutoff"] == summary["cutoff"]


def test_skip_reason_counts_match_summary():
    with open(SKIPPED_CSV) as f:
        rows = list(csv.DictReader(f))
    skip_counts = Counter(r["skip_reason"] for r in rows if r["skip_reason"])
    with open(SUMMARY_JSON) as f:
        summary = json.load(f)["result"]
    assert skip_counts["blocked_time"] == summary["skipped_blocked_time"]
    assert skip_counts["no_cutoff"] == summary["skipped_no_cutoff"]
    assert skip_counts["SAL"] == summary["skipped_SAL"]
    assert skip_counts["position_open"] == summary["skipped_position_open"]
    assert skip_counts["no_anchor"] == summary["skipped_no_anchor"]
    assert skip_counts["simultaneous_collision"] == summary["skipped_simultaneous_collision"]
    assert skip_counts["same_bar_reentry"] == summary["skipped_same_bar_reentry"]
    executed_count = sum(1 for r in rows if r["eligibility"] == "executed")
    assert executed_count == summary["executed"]
    total_touches = len(rows)
    assert total_touches == summary["total_physical_touches"]


def test_headline_metrics_recomputed_from_ledger():
    rows = _load_executed()
    n = len(rows)
    net = sum(float(r["pnl"]) for r in rows)
    wins = [float(r["pnl"]) for r in rows if float(r["pnl"]) > 0]
    losses = [float(r["pnl"]) for r in rows if float(r["pnl"]) < 0]
    pf = sum(wins) / (-sum(losses))
    win_rate = len(wins) / n
    avg_trade = net / n

    eq = 0.0
    peak = 0.0
    maxdd = 0.0
    for r in rows:
        eq += float(r["pnl"])
        peak = max(peak, eq)
        maxdd = min(maxdd, eq - peak)

    with open(SUMMARY_JSON) as f:
        summary = json.load(f)["result"]

    assert n == summary["executed"] == 1107
    assert abs(net - summary["net_pts"]) < 0.05
    assert abs(pf - summary["PF"]) < 0.0005
    assert abs(win_rate - summary["win_rate"]) < 0.0005
    assert abs(avg_trade - summary["avg_trade"]) < 0.001
    assert abs(maxdd - summary["max_drawdown"]) < 0.05


def test_two_engines_agree_exactly():
    with open(COMPARISON_JSON) as f:
        comp = json.load(f)
    assert comp["fully_reproduced"] is True
    assert comp["reference_rows"] == comp["comparison_rows"] == 1107
    assert comp["only_in_reference"] == 0
    assert comp["only_in_comparison"] == 0
    assert comp["same_entry_diff_exit"] == 0
    assert comp["same_entry_exit_diff_pnl"] == 0


def test_negative_years_match_documented():
    rows = _load_executed()
    by_year = {}
    for r in rows:
        y = r["year"]
        by_year.setdefault(y, 0.0)
        by_year[y] += float(r["pnl"])
    negative_years = sorted(int(y) for y, v in by_year.items() if v < 0)
    assert negative_years == [2019, 2023, 2024]
