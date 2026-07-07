"""Runner: backtest the 4 kill-switch mechanism families (with preregistered
parameter grids) against the always-on baseline, on the full chronological
trade sequence, for both OG_PRIMARY_150R and OG_OPERATIONAL_100R.

This is diagnostic monitoring research on an already-simulated trade stream
-- it does not touch level generation, management, RR, or window logic.
Every threshold explored here is a RETROSPECTIVE FIT on data already viewed
in this research line (validation + external years were already diagnosed).
See docs/OG_REGIME_KILLSWITCH_RESULTS.md for the explicit caveat.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.og_regime_killswitch import (
    rolling_pf_killswitch,
    rolling_diagnostics,
    cusum_killswitch,
    streak_killswitch,
    compute_nonwin_streaks,
    apply_flat_mask,
    summarize,
)
from src.metrics import profit_factor, max_drawdown

OUT_DIR = Path("outputs/og_regime_killswitch")
OUT_DIR.mkdir(parents=True, exist_ok=True)

CONFIGS = {
    "primary_150r": {"target_r": 1.50, "build_years": {2018, 2020, 2023, 2026}},
    "operational_100r": {"target_r": 1.00, "build_years": {2018, 2020, 2023, 2026}},
}

BAD_PERIODS = {
    "2014_2015": {2014, 2015},
    "2019": {2019},
    "2024": {2024},
}
GOOD_PERIODS = {
    "2013": {2013},
    "2018_2020_2023_2026_build": {2018, 2020, 2023, 2026},
    "2021_2022_2025_validation": {2021, 2022, 2025},
}

# Preregistered parameter grids -- small, explicitly justified sets, not a
# search over an unbounded space.
PF_WINDOWS = [50, 100, 150, 200]
PF_THRESHOLDS = [0.90, 1.00, 1.10]
PF_REENTRY_MODES = {
    "symmetric": None,        # resume at same threshold
    "hysteretic": 0.15,       # resume at threshold + 0.15 (avoid whipsaw)
}

CUSUM_COOLDOWNS = [20, 30, 50]

STREAK_PERCENTILES = [90, 95, 99]
STREAK_RESUME_WINS = 3  # fixed, preregistered: resume after 3 consecutive winners


def period_breakdown(df_eff: pd.DataFrame, periods: dict) -> dict:
    out = {}
    for label, years in periods.items():
        sub = df_eff[df_eff["year"].isin(years)]
        if len(sub) == 0:
            out[label] = None
            continue
        out[label] = summarize(sub)
    return out


def flat_run_stats(flat: pd.Series, entry_time: pd.Series) -> dict:
    """Number of distinct flat runs and total trades/duration skipped."""
    f = flat.to_numpy()
    n_runs = 0
    total_trades_flat = int(f.sum())
    prev = False
    for v in f:
        if v and not prev:
            n_runs += 1
        prev = v
    if total_trades_flat == 0:
        total_days = 0.0
    else:
        et = pd.to_datetime(entry_time, utc=True)
        flat_times = et[flat.to_numpy()]
        total_days = float((flat_times.max() - flat_times.min()).total_seconds() / 86400.0) if len(flat_times) > 1 else 0.0
    return {"n_flat_runs": n_runs, "n_trades_flat": total_trades_flat, "flat_span_days": round(total_days, 1)}


def run_for_config(config_key: str):
    cfg = CONFIGS[config_key]
    df = pd.read_csv(OUT_DIR / f"{config_key}_full_chronological_trades.csv")
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df = df.sort_values("entry_time", kind="mergesort").reset_index(drop=True)

    results = []
    trigger_logs = {}

    # ---------------- baseline (always on) ----------------
    baseline_eff = apply_flat_mask(df, pd.Series(False, index=df.index))
    baseline_summary = summarize(baseline_eff)
    baseline_summary.update({"mechanism": "baseline_always_on", "params": "none", "config": config_key})
    baseline_summary["bad_period_breakdown"] = period_breakdown(baseline_eff, BAD_PERIODS)
    baseline_summary["good_period_breakdown"] = period_breakdown(baseline_eff, GOOD_PERIODS)
    baseline_summary["flat_stats"] = {"n_flat_runs": 0, "n_trades_flat": 0, "flat_span_days": 0.0}
    results.append(baseline_summary)

    # ---------------- Mechanism 1: rolling PF ----------------
    for window in PF_WINDOWS:
        for threshold in PF_THRESHOLDS:
            for mode, delta in PF_REENTRY_MODES.items():
                reentry_thr = None if delta is None else threshold + delta
                flat = rolling_pf_killswitch(df, window=window, threshold=threshold, reentry_threshold=reentry_thr)
                eff = apply_flat_mask(df, flat)
                summ = summarize(eff)
                summ.update({
                    "mechanism": "rolling_pf",
                    "params": f"window={window},threshold={threshold},reentry={mode}",
                    "config": config_key,
                })
                summ["bad_period_breakdown"] = period_breakdown(eff, BAD_PERIODS)
                summ["good_period_breakdown"] = period_breakdown(eff, GOOD_PERIODS)
                summ["flat_stats"] = flat_run_stats(flat, df["entry_time"])
                results.append(summ)
                key = f"rolling_pf_w{window}_t{threshold}_{mode}"
                trigger_logs[key] = eff[["session_date", "year", "entry_time", "is_flat"]].copy()

    # ---------------- Mechanism 2: rolling diagnostics (overlay only) -------
    diag_frames = {}
    for window in PF_WINDOWS:
        diag_frames[window] = rolling_diagnostics(df, window=window)
    diag_out = pd.concat(
        {str(w): diag_frames[w] for w in PF_WINDOWS}, axis=1
    )
    diag_out.insert(0, "entry_time", df["entry_time"])
    diag_out.insert(1, "year", df["year"])
    diag_out.to_csv(OUT_DIR / f"{config_key}_rolling_diagnostics.csv", index=False)

    # ---------------- Mechanism 3: CUSUM ----------------
    all_r = (df["pnl"] / df["cap"])
    target_mean = float(all_r.mean())  # fixed reference: overall pooled avg R/trade across full history
    baseline_std = float(all_r.std())
    k = baseline_std / 2.0
    h = 4.5 * k  # midpoint of the 4-5x convention
    for cooldown in CUSUM_COOLDOWNS:
        cusum_out = cusum_killswitch(df, target_mean=target_mean, k=k, h=h, cooldown_trades=cooldown)
        flat = cusum_out["flat"]
        eff = apply_flat_mask(df, flat)
        summ = summarize(eff)
        summ.update({
            "mechanism": "cusum",
            "params": f"k={k:.4f},h={h:.4f},cooldown={cooldown}",
            "config": config_key,
        })
        summ["bad_period_breakdown"] = period_breakdown(eff, BAD_PERIODS)
        summ["good_period_breakdown"] = period_breakdown(eff, GOOD_PERIODS)
        summ["flat_stats"] = flat_run_stats(flat, df["entry_time"])
        results.append(summ)
        key = f"cusum_cooldown{cooldown}"
        log = eff[["session_date", "year", "entry_time", "is_flat"]].copy()
        log["cusum_alarm_down"] = cusum_out["cusum_alarm_down"].to_numpy()
        log["cusum_alarm_up"] = cusum_out["cusum_alarm_up"].to_numpy()
        trigger_logs[key] = log

    # ---------------- Mechanism 4: non-winning streak vs build baseline ----
    build_mask = df["year"].isin(cfg["build_years"])
    baseline_streaks = compute_nonwin_streaks(df[build_mask])
    for pct in STREAK_PERCENTILES:
        flat = streak_killswitch(df, baseline_streaks=baseline_streaks, percentile=pct, resume_after_wins=STREAK_RESUME_WINS)
        eff = apply_flat_mask(df, flat)
        summ = summarize(eff)
        thr_val = float(np.percentile(baseline_streaks, pct)) if len(baseline_streaks) else None
        summ.update({
            "mechanism": "nonwin_streak",
            "params": f"percentile={pct}(threshold_len={thr_val}),resume_wins={STREAK_RESUME_WINS}",
            "config": config_key,
        })
        summ["bad_period_breakdown"] = period_breakdown(eff, BAD_PERIODS)
        summ["good_period_breakdown"] = period_breakdown(eff, GOOD_PERIODS)
        summ["flat_stats"] = flat_run_stats(flat, df["entry_time"])
        results.append(summ)
        key = f"streak_p{pct}"
        trigger_logs[key] = eff[["session_date", "year", "entry_time", "is_flat"]].copy()

    return results, trigger_logs, baseline_streaks


def main():
    all_results = []
    for config_key in CONFIGS:
        results, trigger_logs, baseline_streaks = run_for_config(config_key)
        all_results.extend(results)
        for key, log in trigger_logs.items():
            log.to_csv(OUT_DIR / f"{config_key}_trigger_log_{key}.csv", index=False)
        np.save(OUT_DIR / f"{config_key}_build_year_nonwin_streaks.npy", baseline_streaks)
        print(f"[{config_key}] build-year non-winning streak baseline (n={len(baseline_streaks)}): "
              f"max={baseline_streaks.max() if len(baseline_streaks) else None}, "
              f"p90={np.percentile(baseline_streaks,90):.2f}, p95={np.percentile(baseline_streaks,95):.2f}, "
              f"p99={np.percentile(baseline_streaks,99):.2f}")

    # flatten for CSV summary (drop nested dicts into a JSON sidecar, keep headline metrics in CSV)
    rows = []
    for r in all_results:
        row = {k: v for k, v in r.items() if k not in ("bad_period_breakdown", "good_period_breakdown", "flat_stats")}
        row.update({f"flat_{k}": v for k, v in r["flat_stats"].items()})
        rows.append(row)
    summary_df = pd.DataFrame(rows)
    summary_df.to_csv(OUT_DIR / "killswitch_summary.csv", index=False)

    with open(OUT_DIR / "killswitch_summary_full.json", "w") as f:
        json.dump(all_results, f, indent=2, default=lambda o: None if (isinstance(o, float) and np.isnan(o)) else o)

    print(f"\nWrote {OUT_DIR / 'killswitch_summary.csv'} ({len(summary_df)} rows)")
    print(f"Wrote {OUT_DIR / 'killswitch_summary_full.json'}")


if __name__ == "__main__":
    main()
