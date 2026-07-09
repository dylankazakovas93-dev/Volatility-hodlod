"""Same interpretable MAE/MFE formula study as
scripts/gc_mae_mfe_formula_study.py, but on Definition A labels (realized
in-position MAE/MFE, entry -> the strategy's ACTUAL exit: TP/SL/BE/cutoff)
instead of Definition C (entry -> fixed session-cutoff horizon).

CENSORING CAVEAT (label contract requirement, stated explicitly, not
silently mixed with the other definition): Definition A is bounded by the
strategy's own exit rules (1:1 TP/SL, conditional BE at bar 45, forced
15:00 ET cutoff). A trade that gets stopped out just before a large
favorable reversal records a small MFE here even though the market kept
moving favorably after the strategy was already flat -- any formula fit on
this target is at risk of learning "what does this exit system look like"
rather than "what does the market actually do." This is a deliberate,
requested choice for this pass (contrasted against LABEL_DEFINITION.md's
Definition C variant already in this repo), not an oversight.

Population: the 427 EXECUTED trades only (Definition A is inherently about
"the strategy's actual exit," which only exists for trades the strategy
actually took -- unlike the excursion-grid population, which deliberately
used every physical touch).

Reuses every model-fitting/evaluation function from
gc_mae_mfe_formula_study.py unmodified -- only the touch-dataset builder
and the labels differ.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_loader import load_1m_ohlcv, load_gvz_daily
from src.level_generation import GC_PARAMS, generate_levels
from src.strict_engine import bar_ranges, physical_touches, run_strict

from scripts.gc_mae_mfe_formula_study import (
    BARS_PATH, VOL_PATH, TRAIN_END, VAL_END, FEATURES,
    contract_lookup, chronological_split, fit_baselines, fit_linear, fit_quantiles,
    eval_point, pinball_loss, formula_candidates_rows, run_walk_forward,
    calibration_report, leakage_audit, mean_absolute_error, rmse, median_absolute_error,
)

DOC_DIR = "docs/gc_mae_mfe_study"
OUT_DIR = "outputs/gc_mae_mfe_study"
ET = "America/New_York"

SIGMA_MULT, OFFSET_PCT, IB_MINUTES = 2.0, 0.08, 30  # winning grid params, unchanged from the excursion study


def build_realized_touch_dataset(bars, ranges, vol_series, contracts, sigma_mult, offset_pct, ib_minutes):
    params = replace(GC_PARAMS, sigma_mult=sigma_mult, offset_pct=offset_pct, ib_minutes=ib_minutes,
                      fixed_offset=None)
    levels = generate_levels(bars, vol_series, params=params, rth_start="09:30", rth_end="16:00")
    ib_range_series = (levels["ib_high"] - levels["ib_low"])
    trailing_ib = ib_range_series.rolling(window=5, min_periods=1).mean().shift(1)
    lvls = list(levels.itertuples(index=False))

    events = physical_touches(bars, lvls)
    summary, executed, skipped = run_strict(bars, ranges, events)

    rows = []
    for _, t in executed.iterrows():
        i = int(t["level_id"].split("_")[0])
        lv = lvls[i]
        ts, exit_ts = t["entry_time"], t["exit_time"]
        entry = t["entry_price"]
        sign = 1.0 if t["side"] == "lower" else -1.0
        cap = t["cap"]
        if cap <= 0:
            continue

        path = bars.loc[ts:exit_ts]
        if path.empty:
            continue
        path_high, path_low = float(path["high"].max()), float(path["low"].min())
        if sign > 0:
            mfe_pts = max(0.0, path_high - entry)
            mae_pts = max(0.0, entry - path_low)
        else:
            mfe_pts = max(0.0, entry - path_low)
            mae_pts = max(0.0, path_high - entry)

        pos = bars.index.get_indexer([ts])[0]
        prior_close = float(bars["close"].iloc[pos - 1]) if pos > 0 else float(bars["close"].iloc[pos])
        et = ts.tz_convert(ET)
        day = et.date()

        rows.append({
            "touched_at": ts, "side": t["side"], "entry_price": entry, "sign": sign,
            "sigma_day": float(lv.sigma_day), "vol_close_prior": float(lv.vix_close),
            "ib_range_pts": float(lv.ib_high - lv.ib_low),
            "level_distance_from_open_pts": abs(entry - float(lv.cash_open)),
            "side_direction": sign,
            "entry_hour_et": et.hour + et.minute / 60.0,
            "day_of_week": et.dayofweek,
            "dist_prior_bar_close_pts": abs(entry - prior_close),
            "trailing_5session_avg_ib_range_pts": (
                float(trailing_ib.iloc[i]) if not pd.isna(trailing_ib.iloc[i])
                else float(ib_range_series.iloc[:i].mean() if i > 0 else ib_range_series.iloc[i])
            ),
            "stop_distance_R_cap": cap,
            "year": et.year,
            "exit_reason": t["exit_reason"], "pnl": t["pnl"],
            "cutoff_ts": exit_ts,  # reused name so chronological_split()/run_walk_forward() work unmodified
            "mae_pts": mae_pts, "mfe_pts": mfe_pts,
            "mae_R": mae_pts / cap, "mfe_R": mfe_pts / cap,
        })

    return pd.DataFrame(rows).sort_values("touched_at").reset_index(drop=True)


def main():
    bars = load_1m_ohlcv(BARS_PATH)
    ranges = bar_ranges(bars)
    vol_series = load_gvz_daily(VOL_PATH)
    contracts = contract_lookup(BARS_PATH)

    df = build_realized_touch_dataset(bars, ranges, vol_series, contracts, SIGMA_MULT, OFFSET_PCT, IB_MINUTES)
    df = df.dropna(subset=FEATURES + ["mae_R", "mfe_R"]).reset_index(drop=True)
    print(f"realized (Definition A) dataset: {len(df)} executed trades, "
          f"span {df['touched_at'].min()} -> {df['touched_at'].max()}")
    df.to_csv(os.path.join(OUT_DIR, "touch_dataset_realized.csv"), index=False)

    train, val, test, embargoed = chronological_split(df, TRAIN_END, VAL_END)
    print(f"train={len(train)} val={len(val)} test={len(test)} embargoed={embargoed}")

    vol_bounds = train["sigma_day"].quantile([1 / 3, 2 / 3]).to_numpy()
    def vol_tercile(s):
        return pd.cut(s, bins=[-np.inf, vol_bounds[0], vol_bounds[1], np.inf], labels=["low", "mid", "high"])
    def tod_bucket(h):
        return pd.cut(h, bins=[-0.01, 11, 15, 24], labels=["pre-11:00", "11:00-15:00(blocked pop.)", "15:00-24:00"])
    for sub in (train, val, test):
        if len(sub):
            sub["_vol_tercile"] = vol_tercile(sub["sigma_day"])
            sub["_tod_bucket"] = tod_bucket(sub["entry_hour_et"])

    split_manifest = {
        "label_definition": "A (realized in-position: entry -> strategy's actual exit) -- CENSORED by TP/SL/BE/cutoff, see module docstring",
        "params": {"sigma_mult": SIGMA_MULT, "offset_pct": OFFSET_PCT, "ib_minutes": IB_MINUTES},
        "population": "executed trades only (427 total before split), not all physical touches",
        "train": {"end": TRAIN_END, "n": len(train)},
        "validation": {"start": TRAIN_END, "end": VAL_END, "n": len(val)},
        "test": {"start": VAL_END, "n": len(test)},
        "embargoed_rows_dropped_at_boundaries": embargoed,
        "total_rows": len(df),
        "vol_tercile_boundaries_fit_on_train": vol_bounds.tolist(),
        "feature_columns": FEATURES,
    }
    with open(os.path.join(DOC_DIR, "SPLIT_MANIFEST_realized.json"), "w") as f:
        json.dump(split_manifest, f, indent=2, default=str)

    for name, sub in [("train", train), ("val", val), ("test", test)]:
        sub.to_csv(os.path.join(OUT_DIR, f"touches_realized_{name}.csv"), index=False)

    quantiles_by_target = {"mae_R": [0.5, 0.75, 0.9, 0.95], "mfe_R": [0.25, 0.5, 0.75, 0.9]}
    rows, linear_models, quantile_models, baselines = formula_candidates_rows(
        train, val, test, FEATURES, quantiles_by_target
    )
    pd.DataFrame(rows).to_csv(os.path.join(DOC_DIR, "FORMULA_CANDIDATES_realized.csv"), index=False)

    wf = run_walk_forward(df, FEATURES)
    wf.to_csv(os.path.join(DOC_DIR, "WALK_FORWARD_RESULTS_realized.csv"), index=False)

    calib = calibration_report(val.copy(), test.copy(), linear_models, quantile_models, FEATURES)
    with open(os.path.join(DOC_DIR, "CALIBRATION_REPORT_realized.md"), "w") as f:
        f.write("**Label definition: A (realized in-position, censored by the strategy's own exit rules)**\n\n" + calib)

    audit_text, audit_pass = leakage_audit(df, FEATURES)
    with open(os.path.join(DOC_DIR, "LEAKAGE_AUDIT_realized.md"), "w") as f:
        f.write(audit_text)

    print(f"leakage audit: {'PASS' if audit_pass else 'FAIL'}")

    # quick negative-prediction check, same as the Definition C pass
    full = pd.concat([train, val, test])
    neg_report = []
    for target in ["mae_R", "mfe_R"]:
        lin_preds = linear_models[target].predict(full[FEATURES].to_numpy())
        q50_preds = quantile_models[target][0.5].predict(full[FEATURES].to_numpy())
        neg_report.append({
            "target": target,
            "linear_n_negative": int((lin_preds < 0).sum()), "linear_min": float(lin_preds.min()),
            "q50_n_negative": int((q50_preds < 0).sum()), "q50_min": float(q50_preds.min()),
            "n_total": len(full),
        })
    print(pd.DataFrame(neg_report).to_string(index=False))

    return df, train, val, test, wf, neg_report


if __name__ == "__main__":
    main()
