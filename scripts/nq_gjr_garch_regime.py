#!/usr/bin/env python3
"""GJR-GARCH(1,1) regime classification + backtest split for NQ level-fade system.

Workflow:
  1. Fit GJR-GARCH(1,1,1) with Student-t errors on daily NQ close returns
     (Student-t captures fat tails appropriate for equity index futures).
     GJR adds asymmetry: negative shocks increase vol more than positive
     ones -- the leverage effect that EGARCH also captures but in log space.
  2. Extract the in-sample conditional volatility series (per calendar day).
  3. Classify each day as LOW / MID / HIGH regime via rolling 252-day
     33rd and 67th percentile thresholds (same approach as the skeleton).
  4. Join regime labels onto the canonical locked-baseline trade ledger
     (scripts/nq_cond_be45.py) via session_date, then report:
       - per-regime: n, net, PF, maxDD, tWR, true WR, annualized Sharpe
       - whether filtering to one regime improves Sharpe or avoids DD
  5. Also test: what happens if we SKIP all HIGH-vol trades vs. all LOW-vol
     trades, report the resulting filtered ledgers.

No lookahead: the regime label for a session is assigned using only the
conditional vol from the PRIOR session's model output, not the current one.

Usage:
    python3 scripts/nq_gjr_garch_regime.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings

import numpy as np
import pandas as pd
from arch import arch_model

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import load_1m_ohlcv, load_gvz_daily
import scripts.nq_cond_be45 as C
import scripts.build_be60_enriched as B

TRADING_DAYS = 252
ROLLING_WINDOW = 252


def fit_gjr_garch(bars):
    daily = bars.resample("1D").agg({"close": "last"}).dropna()
    ret = daily["close"].pct_change().dropna() * 100
    ret = ret[ret.index.weekday < 5]  # drop weekends

    print(f"Fitting GJR-GARCH(1,1,1) with Student-t on {len(ret)} daily returns ...", flush=True)
    am = arch_model(ret, vol="GARCH", p=1, o=1, q=1, dist="t")
    res = am.fit(disp="off")

    print(f"  omega={res.params['omega']:.4f}  alpha={res.params['alpha[1]']:.4f}  "
          f"gamma={res.params['gamma[1]']:.4f}  beta={res.params['beta[1]']:.4f}  "
          f"nu(df)={res.params['nu']:.2f}")

    cond_vol = res.conditional_volatility.rename("cond_vol")

    # rolling quantile thresholds
    q33 = cond_vol.rolling(ROLLING_WINDOW).quantile(0.33)
    q67 = cond_vol.rolling(ROLLING_WINDOW).quantile(0.67)

    def classify(vol, lo, hi):
        if pd.isna(lo) or pd.isna(hi):
            return "MID"
        if vol < lo:
            return "LOW"
        elif vol < hi:
            return "MID"
        else:
            return "HIGH"

    regime = pd.Series(
        [classify(v, lo, hi) for v, lo, hi in zip(cond_vol, q33, q67)],
        index=cond_vol.index,
        name="regime",
    )

    # shift by 1 so we use PRIOR day's vol to classify today (no lookahead)
    regime_lagged = regime.shift(1).fillna("MID")

    return pd.DataFrame({"cond_vol": cond_vol, "q33": q33, "q67": q67,
                          "regime": regime_lagged})


def ann_sharpe(daily_pnl):
    if daily_pnl.std(ddof=1) == 0 or len(daily_pnl) < 5:
        return float("nan")
    return float(daily_pnl.mean() / daily_pnl.std(ddof=1) * np.sqrt(TRADING_DAYS))


def stats(df):
    p = df["pnl"]
    ex = df["exit"].value_counts()
    tp, sl = ex.get("TP", 0), ex.get("SL", 0)
    daily = df.groupby("sess_date")["pnl"].sum()
    return {
        "n": len(df),
        "net": float(p.sum()),
        "PF": C.profit_factor(p),
        "maxDD": C.max_drawdown(p),
        "tWR": tp / (tp + sl) * 100 if (tp + sl) > 0 else float("nan"),
        "trueWR": (p > 0.1).sum() / len(df) * 100,
        "sharpe": ann_sharpe(daily),
        "TP": int(tp), "SL": int(sl),
        "BE": int(ex.get("BE", 0)), "cut": int(ex.get("cutoff", 0)),
    }


def print_stats(label, s, width=28):
    print(f"  {label:<{width}}  n={s['n']:>5}  net={s['net']:>8.0f}  PF={s['PF']:.3f}  "
          f"maxDD={s['maxDD']:>7.0f}  tWR={s['tWR']:.1f}%  trueWR={s['trueWR']:.1f}%  "
          f"Sharpe={s['sharpe']:.2f}  TP={s['TP']} SL={s['SL']} BE={s['BE']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)

    # -- fit model
    regime_df = fit_gjr_garch(bars)

    # -- build canonical baseline ledger (same 1256-trade set as the frozen fingerprint)
    raw = C.build_ledger(bars, vxn)
    kept = C.apply_sal(raw).sort_values("touched_at").reset_index(drop=True)
    print(f"\nCanonical ledger: {len(raw)} raw -> {len(kept)} kept (post-SAL)\n")

    # attach regime: match each trade's sess_date to the regime label for that calendar day
    # sess_date is already a string "YYYY-MM-DD"; regime_df index is the daily bar date
    regime_dict = {}
    for ts, row in regime_df.iterrows():
        date_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
        regime_dict[date_str] = row["regime"]

    kept["regime"] = kept["sess_date"].map(regime_dict).fillna("MID")

    # regime distribution
    rc = kept["regime"].value_counts()
    print(f"Regime distribution: LOW={rc.get('LOW',0)} MID={rc.get('MID',0)} HIGH={rc.get('HIGH',0)}")
    total_cond_vol = regime_df["cond_vol"]
    print(f"Conditional vol range: {total_cond_vol.min():.3f} – {total_cond_vol.max():.3f} (median {total_cond_vol.median():.3f})\n")

    # -- per-regime stats
    print("=== PERFORMANCE BY REGIME ===")
    print_stats("ALL trades", stats(kept))
    for regime in ["LOW", "MID", "HIGH"]:
        sub = kept[kept["regime"] == regime]
        if sub.empty:
            print(f"  {regime}: no trades")
        else:
            print_stats(regime, stats(sub))

    # -- filter tests: skip HIGH / skip LOW / LOW+MID only
    print("\n=== FILTER TESTS (skip one regime entirely) ===")
    for label, mask in [
        ("skip HIGH (LOW+MID only)", kept["regime"] != "HIGH"),
        ("skip LOW  (MID+HIGH only)", kept["regime"] != "LOW"),
        ("LOW only", kept["regime"] == "LOW"),
        ("MID only", kept["regime"] == "MID"),
        ("HIGH only", kept["regime"] == "HIGH"),
    ]:
        sub = kept[mask]
        if sub.empty:
            continue
        print_stats(label, stats(sub))

    # -- year x regime heatmap (net per year/regime)
    print("\n=== NET P&L BY YEAR x REGIME ===")
    years = sorted(kept["year"].unique())
    regimes = ["LOW", "MID", "HIGH", "ALL"]
    header = f"{'Year':>6}" + "".join(f" {'LOW':>7} {'MID':>7} {'HIGH':>7} {'ALL':>7}")
    print(header)
    for yr in years:
        sub_yr = kept[kept["year"] == yr]
        row = f"{yr:>6}"
        for r in ["LOW", "MID", "HIGH"]:
            sub_r = sub_yr[sub_yr["regime"] == r]
            row += f"  {sub_r['pnl'].sum():>7.0f}" if not sub_r.empty else f"  {'—':>7}"
        row += f"  {sub_yr['pnl'].sum():>7.0f}"
        print(row)
    for r in ["LOW", "MID", "HIGH"]:
        pass
    row = f"{'ALL':>6}"
    for r in ["LOW", "MID", "HIGH"]:
        sub_r = kept[kept["regime"] == r]
        row += f"  {sub_r['pnl'].sum():>7.0f}" if not sub_r.empty else f"  {'—':>7}"
    row += f"  {kept['pnl'].sum():>7.0f}"
    print(row)


if __name__ == "__main__":
    main()
