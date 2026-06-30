#!/usr/bin/env python3
"""Fit a per-trade adaptive TP formula from pre-entry market structure
(prior 1h range, ATR at two lengths, hourly RSI) instead of a fixed
TP=cap, then backtest it.

Method:
  1. For every canonical entry (9:30 anchor, same touches as the locked
     baseline), compute features known BEFORE entry, no lookahead:
       anchor  = prev completed 1h range (same one cap is built from)
       atr14   = 14-period ATR on hourly bars, as of the last completed hour
       atr50   = 50-period ATR on hourly bars, same
       rsi14   = 14-period RSI on hourly closes, same
  2. Target = raw MFE (max favorable excursion), measured over the FULL
     available path to session cutoff, ignoring any stop/target -- this
     is "how far would price have run in our favor," the thing a TP
     formula should be sized against. No lookahead in the target itself
     since it's computed post-entry purely for fitting, never used live.
  3. OLS fit (closed form, no sklearn dependency): mfe ~ b0 + b1*anchor +
     b2*atr14 + b3*atr50 + b4*rsi14.
  4. Backtest: SL stays the fixed cap (unchanged risk side). TP becomes
     formula_pred * k for a swept scalar k, floored/ceilinged to keep it
     sane. Same cond@45 BE + SAL as everywhere else. Compare net/PF/n to
     the fixed TP=cap baseline.

Usage:
    python3 scripts/nq_formula_tp_fit.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch
import scripts.build_be60_enriched as B

BE_BARS = 45
MIN_TP, MAX_TP = 15.0, 200.0


def hourly_features(bars):
    h = bars.resample("60min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    prev_close = h["close"].shift(1)
    tr = pd.concat([
        h["high"] - h["low"],
        (h["high"] - prev_close).abs(),
        (h["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    atr50 = tr.rolling(50).mean()

    delta = h["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi14 = 100 - 100 / (1 + rs)
    rsi14 = rsi14.fillna(50.0)

    return pd.DataFrame({"atr14": atr14, "atr50": atr50, "rsi14": rsi14}).dropna()


def lookup_prev_hour(feat_df, ts):
    prev = ts.floor("60min") - pd.Timedelta(minutes=60)
    if prev not in feat_df.index:
        return None
    row = feat_df.loc[prev]
    if row.isna().any():
        return None
    return row


def build_trades(bars, vxn, feat_df):
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = B.bar_ranges(bars)
    lvls = list(levels.itertuples(index=False))
    trades = []
    for i, lv in enumerate(lvls):
        expiry = lvls[i + B.LINE_DAYS].created_at if i + B.LINE_DAYS < len(lvls) else bars.index[-1]
        search = bars.loc[lv.created_at: expiry]
        for side, col in (("upper", lv.upper_level), ("lower", lv.lower_level)):
            lvl = float(col)
            ft = _first_touch(search, lvl)
            if ft is None or not B.entry_allowed(ft):
                continue
            anchor = B.prev_completed_range(ranges, ft)
            if anchor is None:
                continue
            feat = lookup_prev_hour(feat_df, ft)
            if feat is None:
                continue
            co = B.session_cutoff(ft)
            if co is None:
                continue
            path = bars.loc[ft: co].iloc[1:]
            if path.empty:
                continue
            cap = min(1.5 * anchor, B.SL_CAP)
            sg = -1.0 if side == "upper" else 1.0
            hi, lo = path["high"].values.astype(float), path["low"].values.astype(float)
            e = lvl
            raw_mfe = float(np.max((hi - e) if sg > 0 else (e - lo)))
            raw_mae = float(np.max((e - lo) if sg > 0 else (hi - e)))
            trades.append({
                "sd": B.session_date(ft), "yr": pd.Timestamp(B.session_date(ft)).year, "ta": ft,
                "e": e, "sg": sg, "cap": cap, "anchor": anchor,
                "atr14": feat["atr14"], "atr50": feat["atr50"], "rsi14": feat["rsi14"],
                "raw_mfe": raw_mfe, "raw_mae": raw_mae,
                "hi": hi, "lo": lo,
                "op": path["open"].values.astype(float), "cl": path["close"].values.astype(float),
            })
    return trades


def sim(t, tp_dist, be_bars=BE_BARS):
    e, sg, c = t["e"], t["sg"], t["cap"]
    target = e + sg * tp_dist
    orig_stop = e - sg * c
    hi, lo, op, cl = t["hi"], t["lo"], t["op"], t["cl"]
    armed = checked = False
    for i in range(len(hi)):
        h, l = hi[i], lo[i]
        if i < be_bars:
            stop = orig_stop
        else:
            if not checked:
                checked = True
                o = float(op[i])
                armed = (o >= e) if sg > 0 else (o <= e)
            stop = e if armed else orig_stop
        if sg > 0:
            if l <= stop:
                return sg * (stop - e), ("BE" if (i >= be_bars and armed) else "SL")
            if h >= target:
                return tp_dist, "TP"
        else:
            if h >= stop:
                return sg * (stop - e), ("BE" if (i >= be_bars and armed) else "SL")
            if l <= target:
                return tp_dist, "TP"
    return sg * (float(cl[-1]) - e), "cutoff"


def apply_sal(trades, pnls_exits):
    rows = [{"sd": t["sd"], "ta": t["ta"], "p": pe[0], "ex": pe[1]} for t, pe in zip(trades, pnls_exits)]
    df = pd.DataFrame(rows).sort_values("ta")
    kept = []
    for _, day in df.groupby("sd"):
        lost = False
        for _, r in day.iterrows():
            if not lost:
                kept.append(r.to_dict())
                if r["p"] < -0.1 and r["ex"] != "BE":
                    lost = True
    return pd.DataFrame(kept)


def pf(s):
    g, l = float(s[s > 0].sum()), float(-s[s < 0].sum())
    return g / l if l > 0 else float("inf")


def maxdd(s):
    e = s.cumsum()
    return float((e - e.cummax()).min())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)

    feat_df = hourly_features(bars)
    trades = build_trades(bars, vxn, feat_df)
    print(f"trades with full feature set: {len(trades)}\n")

    df = pd.DataFrame(trades)
    X_cols = ["anchor", "atr14", "atr50", "rsi14"]
    X = np.column_stack([np.ones(len(df))] + [df[c].values for c in X_cols])
    y = df["raw_mfe"].values

    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ coef
    ss_res = np.sum((y - pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot

    print("=== Fitted formula: MFE_pred = b0 + b1*anchor + b2*atr14 + b3*atr50 + b4*rsi14 ===")
    names = ["b0(intercept)"] + [f"b_{c}" for c in X_cols]
    for n, c in zip(names, coef):
        print(f"  {n:>15} = {c:+.4f}")
    print(f"  R^2 = {r2:.4f}   (n={len(df)})")

    # correlation of each individual feature with raw_mfe, for context
    print("\n  individual correlations with raw MFE:")
    for c in X_cols:
        print(f"    corr(MFE, {c}) = {np.corrcoef(df[c], y)[0,1]:+.3f}")

    df["mfe_pred"] = pred

    # baseline: fixed TP=cap
    base_res = [sim(t, t["cap"]) for t in trades]
    base = apply_sal(trades, base_res)
    base_net, base_pf = base["p"].sum(), pf(base["p"])
    print(f"\nBASELINE (TP=cap fixed): n={len(base)} net={base_net:.0f} PF={base_pf:.3f} maxDD={maxdd(base['p']):.0f}")

    print(f"\n=== formula-derived TP = clip(k * mfe_pred, {MIN_TP}, {MAX_TP}), SL=cap unchanged ===")
    print(f"{'k':>5} {'n':>5} {'net':>9} {'PF':>7} {'maxDD':>8} {'dNet':>8} {'TP':>5} {'SL':>5} {'BE':>5} {'cut':>5}")
    for k in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2):
        tp_list = np.clip(k * df["mfe_pred"].values, MIN_TP, MAX_TP)
        res = [sim(t, tp) for t, tp in zip(trades, tp_list)]
        kept = apply_sal(trades, res)
        p = kept["p"]
        ex = kept["ex"].value_counts()
        print(f"{k:>5.2f} {len(kept):>5} {p.sum():>9.0f} {pf(p):>7.3f} {maxdd(p):>8.0f} "
              f"{p.sum()-base_net:>+8.0f} {ex.get('TP',0):>5} {ex.get('SL',0):>5} "
              f"{ex.get('BE',0):>5} {ex.get('cutoff',0):>5}")


if __name__ == "__main__":
    main()
