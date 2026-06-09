#!/usr/bin/env python3
"""
NQ level-fade risk-engine audit.

Frozen mechanics:
  - NQ continuous 1-minute OHLCV
  - VXN, sigma_mult=1.25, fixed_offset=15.75, IB=60m, RTH 09:30-16:00 ET
  - Fade first touch: lower=long, upper=short
  - Entry allowed 19:00-11:00 ET (skip 11:00-15:00)
  - Session stop-after-first-loss (19:00 -> next-day 15:00 ET)
  - lineDays=20: level pair[i] active from created_at[i] to created_at[i+20]
  - TP = 1.5x prev completed 1h range (uncapped)
  - Raw SL = 1.5x prev completed 1h range

Audit outputs:
  1. Baseline verification (SL cap=160) vs user's 609-trade reference
  2. Stop-bucket breakdown (<= 80, 80-100, 100-120, 120-140, 140-160, >160)
  3. Skip-wide-stop variants (skip raw SL > 80/100/120/140/160/200)
  4. Symmetric TP=SL cap variants (cap at 80/100/120/140/160/200)
  5. Asymmetric SL-only cap (TP uncapped, SL capped)
  6. Scaled-sizing variants (2 micros if SL<=threshold, else 1)
  7. Expectancy by bucket: is wide-stop carrying the edge?

MNQ sizing: $2/pt per micro
"""
from __future__ import annotations

import argparse
import math
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch

# ── constants ─────────────────────────────────────────────────────────────────
MNQ_PTS_PER_DOLLAR = 2.0   # $2/pt per MNQ micro contract
LINE_DAYS = 20              # lineDays=20: active for next 20 generated pairs

# ── helpers ───────────────────────────────────────────────────────────────────

def entry_allowed(ts: pd.Timestamp) -> bool:
    et = ts.tz_convert("America/New_York")
    m  = et.hour * 60 + et.minute
    return not (11 * 60 <= m < 15 * 60)


def session_date(ts: pd.Timestamp) -> str:
    et = ts.tz_convert("America/New_York")
    if et.hour >= 19:
        return (et + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return et.strftime("%Y-%m-%d")


def session_cutoff(touched_at: pd.Timestamp, cutoff="15:00", resume="19:00") -> pd.Timestamp | None:
    et = touched_at.tz_convert("America/New_York")
    d  = et.strftime("%Y-%m-%d")
    co = pd.Timestamp(f"{d} {cutoff}", tz="America/New_York")
    re = pd.Timestamp(f"{d} {resume}", tz="America/New_York")
    if et < co:
        return co.tz_convert(touched_at.tz)
    if et >= re:
        nxt = et.normalize() + pd.Timedelta(days=1)
        return pd.Timestamp(f"{nxt.date()} {cutoff}", tz="America/New_York").tz_convert(touched_at.tz)
    return None


def bar_ranges(bars: pd.DataFrame, minutes: int = 60) -> pd.Series:
    r = bars.resample(f"{minutes}min", label="left", closed="left").agg({"high": "max", "low": "min"}).dropna()
    return r["high"] - r["low"]


def prev_completed_range(ranges: pd.Series, ts: pd.Timestamp, minutes: int = 60) -> float | None:
    prev = ts.floor(f"{minutes}min") - pd.Timedelta(minutes=minutes)
    v = ranges.get(prev)
    return float(v) if v is not None and not pd.isna(v) and v > 0 else None


def simulate(path_bars: pd.DataFrame, entry: float, sign: float, tp_pts: float, sl_pts: float) -> tuple[str, pd.Timestamp | None, float]:
    """Simulate one trade on pre-sliced path bars (already skip first bar).
    Returns (exit_reason, exit_ts, pnl_pts).
    """
    if path_bars.empty:
        return "no_path", None, 0.0
    target = entry + sign * tp_pts
    stop   = entry - sign * sl_pts
    for ts, bar in path_bars.iterrows():
        hi, lo = float(bar["high"]), float(bar["low"])
        if sign > 0:
            hs, ht = lo <= stop, hi >= target
        else:
            hs, ht = hi >= stop, lo <= target
        if hs:
            return "SL", ts, -sl_pts
        if ht:
            return "TP", ts, tp_pts
    last = float(path_bars["close"].iloc[-1])
    return "cutoff", path_bars.index[-1], sign * (last - entry)


def profit_factor(pts: pd.Series) -> float:
    g = float(pts[pts > 0].sum())
    l = float(-pts[pts < 0].sum())
    if l == 0:
        return float("inf") if g > 0 else 0.0
    return g / l


def max_drawdown(pts: pd.Series) -> float:
    if pts.empty:
        return 0.0
    eq = pts.cumsum()
    return float((eq - eq.cummax()).min())


def max_loss_streak(pts: pd.Series) -> int:
    streak = best = 0
    for v in pts:
        streak = streak + 1 if v < 0 else 0
        best = max(best, streak)
    return best


def apply_session_sal(records: list[dict], pts_col: str = "raw_pnl") -> list[dict]:
    df = pd.DataFrame(records).sort_values("touched_at")
    kept = []
    for _, day in df.groupby("sess_date"):
        lost = False
        for _, row in day.iterrows():
            if lost:
                row = row.copy()
                row["sal_excluded"] = True
            else:
                row["sal_excluded"] = False
                if row[pts_col] < 0:
                    lost = True
            kept.append(row.to_dict())
    return kept


def summarize(pts: pd.Series, label: str, n_all: int | None = None) -> None:
    if pts.empty:
        print(f"  {label}: no trades")
        return
    wr = float((pts > 0).mean())
    pf = profit_factor(pts)
    dd = max_drawdown(pts)
    ls = max_loss_streak(pts)
    print(
        f"  {label:40s}  n={len(pts):4d}  net={pts.sum():9.2f}  "
        f"PF={pf:.3f}  WR={wr:.3f}  maxDD={dd:.2f}  streak={ls}"
    )


def summarize_by_year(df: pd.DataFrame, pts_col: str, label: str) -> None:
    print(f"\n=== {label} ===")
    for yr in sorted(df["year"].unique()):
        sub = df[df["year"] == yr][pts_col]
        summarize(sub, str(yr))
    summarize(df[pts_col], "ALL")


# ── build raw trade ledger ────────────────────────────────────────────────────

def build_raw_ledger(bars: pd.DataFrame, vxn: pd.Series, in_sample_years: set[int], oos_year: int) -> pd.DataFrame:
    all_levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = bar_ranges(bars, 60)

    # lineDays=20: level[i] active until level[i+20] is created
    levels_list = list(all_levels.itertuples(index=False))
    records = []

    for i, lv in enumerate(levels_list):
        # Expiry = created_at of the 20th newer level, or end of data
        if i + LINE_DAYS < len(levels_list):
            expiry_ts = levels_list[i + LINE_DAYS].created_at
        else:
            expiry_ts = bars.index[-1]

        search_bars = bars.loc[lv.created_at : expiry_ts]

        for side, col in (("upper", lv.upper_level), ("lower", lv.lower_level)):
            lvl = float(col)
            touched_at = _first_touch(search_bars, lvl)
            if touched_at is None:
                continue
            if not entry_allowed(touched_at):
                continue

            anchor = prev_completed_range(ranges, touched_at, 60)
            if anchor is None:
                continue

            cutoff_ts = session_cutoff(touched_at)
            if cutoff_ts is None:
                continue

            path = bars.loc[touched_at:cutoff_ts].iloc[1:]
            if path.empty:
                continue

            sign = -1.0 if side == "upper" else 1.0
            raw_tp = 1.5 * anchor
            raw_sl = 1.5 * anchor  # before any cap

            exit_reason, exit_ts, raw_pnl = simulate(path, lvl, sign, raw_tp, raw_sl)

            # MAE (max adverse excursion in pts during path)
            if sign > 0:
                mae = float((lvl - path["low"]).clip(lower=0).max())
            else:
                mae = float((path["high"] - lvl).clip(lower=0).max())

            sess = session_date(touched_at)
            et = touched_at.tz_convert("America/New_York")

            records.append(
                {
                    "level_sess": str(lv.session_date),
                    "created_at": lv.created_at,
                    "touched_at": touched_at,
                    "sess_date":  sess,
                    "year":       pd.Timestamp(sess).year,
                    "side":       side,
                    "level":      lvl,
                    "direction":  "short" if sign < 0 else "long",
                    "anchor":     anchor,
                    "raw_tp":     raw_tp,
                    "raw_sl":     raw_sl,
                    "mae":        mae,
                    "exit_reason_raw": exit_reason,
                    "raw_pnl":    raw_pnl,
                    # path stored for re-simulation variants
                    "_path_start": path.index[0],
                    "_path_end":   path.index[-1],
                    "_entry":      lvl,
                    "_sign":       sign,
                    "_cutoff_ts":  cutoff_ts,
                }
            )

    return pd.DataFrame(records)


# ── re-simulate with different tp/sl ─────────────────────────────────────────

def resim_col(bars: pd.DataFrame, df: pd.DataFrame, tp_fn, sl_fn) -> pd.Series:
    """Vectorised re-simulation: tp_fn/sl_fn receive a row and return pts."""
    results = []
    for _, row in df.iterrows():
        tp = tp_fn(row)
        sl = sl_fn(row)
        if tp is None or sl is None:
            results.append(None)
            continue
        path = bars.loc[row["_path_start"]:row["_cutoff_ts"]]
        reason, _, pnl = simulate(path, row["_entry"], row["_sign"], tp, sl)
        results.append(pnl)
    return pd.Series(results, index=df.index)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", required=True)
    parser.add_argument("--vxn", default="data/vxn_daily_2020_2026.csv")
    parser.add_argument("--in-sample-years", default="2021,2023,2024,2025,2026")
    parser.add_argument("--oos-year", default="2022")
    args = parser.parse_args()

    in_sample = {int(y) for y in args.in_sample_years.split(",")}
    oos_year  = int(args.oos_year)

    print("Loading data …")
    bars = load_1m_ohlcv(args.bars)
    vxn  = load_gvz_daily(args.vxn)

    print("Building raw ledger (lineDays=20) …")
    raw = build_raw_ledger(bars, vxn, in_sample, oos_year)
    print(f"  Raw touches (before SAL): {len(raw)}")

    # ── apply baseline cap (SL=min(raw, 160)) and session SAL ────────────────
    raw["base_sl"]  = raw["raw_sl"].clip(upper=160.0)
    # baseline TP uncapped, SL capped at 160 → need to re-sim where raw_sl > 160
    print("Re-simulating capped-SL baseline …")

    def base_tp(r):  return r["raw_tp"]
    def base_sl(r):  return min(r["raw_sl"], 160.0)

    raw["base_pnl"] = resim_col(bars, raw, base_tp, base_sl)

    # session SAL on baseline
    recs_all = raw.to_dict("records")
    recs_all_sal = apply_session_sal(recs_all, "base_pnl")
    df_all = pd.DataFrame(recs_all_sal)
    df_all_kept = df_all[~df_all["sal_excluded"]]

    is_df   = df_all_kept[df_all_kept["year"].isin(in_sample)]
    oos_df  = df_all_kept[df_all_kept["year"] == oos_year]

    print(f"\n{'='*70}")
    print("BASELINE (TP=1.5x anchor, SL=min(1.5x anchor, 160)) + session SAL")
    print(f"{'='*70}")
    summarize_by_year(is_df,  "base_pnl", "IN-SAMPLE")
    summarize_by_year(oos_df, "base_pnl", "OOS 2022")

    # ── STOP BUCKET ANALYSIS ─────────────────────────────────────────────────
    buckets = [
        ("<=80",    lambda r: r["raw_sl"] <= 80),
        ("80-100",  lambda r: 80 < r["raw_sl"] <= 100),
        ("100-120", lambda r: 100 < r["raw_sl"] <= 120),
        ("120-140", lambda r: 120 < r["raw_sl"] <= 140),
        ("140-160", lambda r: 140 < r["raw_sl"] <= 160),
        (">160",    lambda r: r["raw_sl"] > 160),
    ]
    print(f"\n{'='*70}")
    print("STOP BUCKET ANALYSIS (IS only, baseline SL cap=160, session SAL kept trades)")
    print(f"{'='*70}")
    print(f"{'Bucket':12} {'n':>5} {'net_pts':>10} {'PF':>7} {'WR':>6} {'maxDD':>8} "
          f"{'streak':>6} {'avg_anchor':>10} {'carry%':>7}")
    total_net = is_df["base_pnl"].sum()
    for label, fn in buckets:
        sub = is_df[[fn(r) for _, r in is_df.iterrows()]]
        if sub.empty:
            print(f"  {label:12} — no trades")
            continue
        pts = sub["base_pnl"]
        pf  = profit_factor(pts)
        wr  = float((pts > 0).mean())
        dd  = max_drawdown(pts)
        ls  = max_loss_streak(pts)
        avg_a = sub["anchor"].mean()
        carry = 100 * pts.sum() / total_net if total_net != 0 else 0
        print(f"  {label:12} {len(pts):5d} {pts.sum():10.2f} {pf:7.3f} {wr:6.3f} {dd:8.2f} "
              f"{ls:6d} {avg_a:10.2f} {carry:6.1f}%")

    # ── SKIP WIDE-STOP VARIANTS ───────────────────────────────────────────────
    skip_thresholds = [80, 100, 120, 140, 160, 200]
    print(f"\n{'='*70}")
    print("SKIP WIDE-STOP VARIANTS (skip trades where raw SL > threshold, IS)")
    print(f"{'='*70}")
    print(f"{'Variant':30} {'n':>5} {'net_pts':>10} {'PF':>7} {'WR':>6} {'maxDD':>8} {'streak':>6}")
    for thr in skip_thresholds:
        sub = is_df[is_df["raw_sl"] <= thr]
        # Need to re-apply SAL after filtering (some days change)
        sub_sal = apply_session_sal(sub.to_dict("records"), "base_pnl")
        sub_sal_df = pd.DataFrame(sub_sal)
        kept = sub_sal_df[~sub_sal_df["sal_excluded"]]
        pts = kept["base_pnl"]
        label = f"skip raw_SL > {thr}"
        if pts.empty:
            print(f"  {label:30} — no trades")
            continue
        pf = profit_factor(pts)
        wr = float((pts > 0).mean())
        dd = max_drawdown(pts)
        ls = max_loss_streak(pts)
        print(f"  {label:30} {len(pts):5d} {pts.sum():10.2f} {pf:7.3f} {wr:6.3f} {dd:8.2f} {ls:6d}")

    # ── SYMMETRIC TP=SL CAP VARIANTS ─────────────────────────────────────────
    cap_values = [80, 100, 120, 140, 160, 200]
    print(f"\n{'='*70}")
    print("SYMMETRIC TP=SL CAP VARIANTS (cap both at X, IS + OOS)")
    print(f"{'='*70}")
    for cap in cap_values:
        # Re-simulate with capped TP and SL
        col = f"pnl_cap{cap}"
        raw[col] = resim_col(
            bars, raw,
            tp_fn=lambda r, c=cap: min(r["raw_tp"], c),
            sl_fn=lambda r, c=cap: min(r["raw_sl"], c),
        )
        # session SAL on this col
        recs_cap = raw.to_dict("records")
        sal_cap = apply_session_sal(recs_cap, col)
        df_cap = pd.DataFrame(sal_cap)
        kept_cap = df_cap[~df_cap["sal_excluded"]]
        is_cap  = kept_cap[kept_cap["year"].isin(in_sample)]
        oos_cap = kept_cap[kept_cap["year"] == oos_year]
        is_pts  = is_cap[col]
        oos_pts = oos_cap[col]
        print(f"\n  Cap TP=SL={cap}:")
        print(f"    IS : n={len(is_pts):3d}  net={is_pts.sum():9.2f}  PF={profit_factor(is_pts):.3f}  "
              f"WR={float((is_pts>0).mean()):.3f}  maxDD={max_drawdown(is_pts):.2f}  "
              f"streak={max_loss_streak(is_pts)}")
        print(f"    OOS: n={len(oos_pts):3d}  net={oos_pts.sum():9.2f}  PF={profit_factor(oos_pts):.3f}  "
              f"WR={float((oos_pts>0).mean()):.3f}  maxDD={max_drawdown(oos_pts):.2f}  "
              f"streak={max_loss_streak(oos_pts)}")

    # ── ASYMMETRIC SL-ONLY CAP (TP uncapped) ─────────────────────────────────
    print(f"\n{'='*70}")
    print("ASYMMETRIC CAP: TP uncapped, SL capped at X (IS + OOS)")
    print(f"{'='*70}")
    for cap in cap_values:
        col = f"pnl_slcap{cap}"
        raw[col] = resim_col(
            bars, raw,
            tp_fn=lambda r: r["raw_tp"],
            sl_fn=lambda r, c=cap: min(r["raw_sl"], c),
        )
        recs_cap = raw.to_dict("records")
        sal_cap = apply_session_sal(recs_cap, col)
        df_cap = pd.DataFrame(sal_cap)
        kept_cap = df_cap[~df_cap["sal_excluded"]]
        is_cap  = kept_cap[kept_cap["year"].isin(in_sample)]
        oos_cap = kept_cap[kept_cap["year"] == oos_year]
        is_pts  = is_cap[col]
        oos_pts = oos_cap[col]
        print(f"\n  Asym SL cap={cap} (TP free):")
        print(f"    IS : n={len(is_pts):3d}  net={is_pts.sum():9.2f}  PF={profit_factor(is_pts):.3f}  "
              f"WR={float((is_pts>0).mean()):.3f}  maxDD={max_drawdown(is_pts):.2f}  "
              f"streak={max_loss_streak(is_pts)}")
        print(f"    OOS: n={len(oos_pts):3d}  net={oos_pts.sum():9.2f}  PF={profit_factor(oos_pts):.3f}  "
              f"WR={float((oos_pts>0).mean()):.3f}  maxDD={max_drawdown(oos_pts):.2f}  "
              f"streak={max_loss_streak(oos_pts)}")

    # ── SCALED SIZING (MNQ micros) ────────────────────────────────────────────
    # Dollar P&L = pts × $2/pt × n_contracts
    print(f"\n{'='*70}")
    print("SCALED SIZING VARIANTS (MNQ $2/pt per micro, IS in-sample dollars)")
    print(f"{'='*70}")
    scale_thresholds = [80, 100, 120, 140, 160]
    print(f"{'Variant':40} {'n':>5} {'net_$':>10} {'max_loss_$':>12} {'maxDD_$':>10} {'streak':>6}")

    # Flat 1 micro baseline
    sub = is_df.copy()
    sub["dollar_pnl"] = sub["base_pnl"] * MNQ_PTS_PER_DOLLAR * 1
    print(f"\n  Flat 1 micro (baseline):")
    pts1 = sub["dollar_pnl"]
    dd1  = max_drawdown(pts1)
    ml1  = float(-(sub["base_pnl"].clip(upper=0) * MNQ_PTS_PER_DOLLAR * 1).min())
    print(f"  {'flat 1 micro':40} {len(pts1):5d} {pts1.sum():10.2f} {ml1:12.2f} {dd1:10.2f} {max_loss_streak(sub['base_pnl']):6d}")

    # Flat 2 micros
    sub["dollar_pnl"] = sub["base_pnl"] * MNQ_PTS_PER_DOLLAR * 2
    print(f"  {'flat 2 micros':40} {len(pts1):5d} {sub['dollar_pnl'].sum():10.2f} "
          f"{float(-(sub['base_pnl'].clip(upper=0) * MNQ_PTS_PER_DOLLAR * 2).min()):12.2f} "
          f"{max_drawdown(sub['dollar_pnl']):10.2f} {max_loss_streak(sub['base_pnl']):6d}")

    for thr in scale_thresholds:
        label = f"2 micros if SL<={thr}, else 1"
        sub["sz"] = sub["raw_sl"].apply(lambda x: 2 if x <= thr else 1)
        sub["dollar_pnl"] = sub["base_pnl"] * MNQ_PTS_PER_DOLLAR * sub["sz"]
        max_loss = float(-(sub.apply(lambda r: r["base_pnl"] * MNQ_PTS_PER_DOLLAR * r["sz"] if r["base_pnl"] < 0 else 0, axis=1)).min())
        dd = max_drawdown(sub["dollar_pnl"])
        streak = max_loss_streak(sub["base_pnl"])
        print(f"  {label:40} {len(sub):5d} {sub['dollar_pnl'].sum():10.2f} {max_loss:12.2f} {dd:10.2f} {streak:6d}")

    # ── YEAR-BY-YEAR TABLE FOR BEST CANDIDATES ────────────────────────────────
    print(f"\n{'='*70}")
    print("YEAR-BY-YEAR BREAKDOWN: BASELINE vs BEST SYMMETRIC CAP (IS + OOS)")
    print(f"{'='*70}")
    for col, label in [("base_pnl", "Baseline SL cap=160"), ("pnl_cap120", "Symmetric cap=120")]:
        recs = raw.to_dict("records")
        sal_recs = apply_session_sal(recs, col)
        df_s = pd.DataFrame(sal_recs)
        df_k  = df_s[~df_s["sal_excluded"]]
        print(f"\n  [{label}]")
        for yr in sorted(df_k["year"].unique()):
            sub = df_k[df_k["year"] == yr][col]
            pf  = profit_factor(sub)
            wr  = float((sub > 0).mean())
            dd  = max_drawdown(sub)
            tag = "IS" if yr in in_sample else "OOS"
            print(f"    {yr} [{tag}]:  n={len(sub):3d}  net={sub.sum():9.2f}  PF={pf:.3f}  WR={wr:.3f}  maxDD={dd:.2f}")

    # ── EXPECTANCY SUMMARY TABLE ──────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("EXPECTANCY BY BUCKET (IS, baseline, avg pts per trade + % of total P&L)")
    print(f"{'='*70}")
    print(f"  {'Bucket':12} {'n':>5} {'net':>9} {'avg_trade':>10} {'win_avg':>9} {'loss_avg':>9} {'carry%':>7}")
    total_net = is_df["base_pnl"].sum()
    for label, fn in buckets:
        sub = is_df[[fn(r) for _, r in is_df.iterrows()]]
        if sub.empty:
            continue
        pts = sub["base_pnl"]
        wins   = pts[pts > 0]
        losses = pts[pts < 0]
        avg_tr  = pts.mean()
        avg_win = wins.mean() if not wins.empty else 0
        avg_los = losses.mean() if not losses.empty else 0
        carry   = 100 * pts.sum() / total_net if total_net != 0 else 0
        print(f"  {label:12} {len(pts):5d} {pts.sum():9.2f} {avg_tr:10.2f} {avg_win:9.2f} {avg_los:9.2f} {carry:6.1f}%")

    print(f"\nRaw anchor range stats (IS all trades, before SAL):")
    is_raw = raw[raw["year"].isin(in_sample)]
    for pct in [10, 25, 50, 75, 90, 95, 99]:
        v = is_raw["anchor"].quantile(pct / 100)
        print(f"  p{pct:2d}: {v:.2f} pts  (TP=SL raw = {1.5*v:.2f})")


if __name__ == "__main__":
    main()
