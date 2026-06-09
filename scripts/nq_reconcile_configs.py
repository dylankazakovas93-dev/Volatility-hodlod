#!/usr/bin/env python3
"""
Reconcile Claude vs Codex config results.

Runs exactly these configs from the same ledger and outputs year-by-year tables:
  1. sl_only_cap160   TP=raw_sl,          SL=min(raw,160)
  2. tp_sl_cap160     TP=SL=min(raw,160), (RR=1.0)
  3. cap120_rr1.5     SL=min(raw,120),    TP=min(raw, 120*1.5)
  4. cap140_rr1.5     SL=min(raw,140),    TP=min(raw, 140*1.5)
  5. sl_only_cap200   TP=raw_sl,          SL=min(raw,200)
  6. tp_sl_cap200     TP=SL=min(raw,200), (RR=1.0)

IS = 2021,2023,2024,2025,2026   OOS = 2022

Codex reference table:
  20d_sl_only_cap160  IS +11857.8  PF 1.674  OOS +2847.8  PF 1.649
  20d_tp_sl_cap160    IS +11287.0  PF 1.661  OOS +2607.7  PF 1.595
  cap120_rr1.5        IS +10186.2  PF 1.588  OOS +2772.8  PF 1.647
  20d_tp_sl_cap200    IS +12040.8  PF 1.692  OOS +2963.3  PF 1.679
  20d_sl_only_cap200  IS +12142.8  PF 1.691  OOS +2870.5  PF 1.658
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch

LINE_DAYS = 20
IS_YEARS  = {2021, 2023, 2024, 2025, 2026}
OOS_YEARS = {2022}


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


def session_cutoff(touched_at: pd.Timestamp) -> pd.Timestamp | None:
    et = touched_at.tz_convert("America/New_York")
    d  = et.strftime("%Y-%m-%d")
    co = pd.Timestamp(f"{d} 15:00", tz="America/New_York")
    re = pd.Timestamp(f"{d} 19:00", tz="America/New_York")
    if et < co:
        return co.tz_convert(touched_at.tz)
    if et >= re:
        nxt = et.normalize() + pd.Timedelta(days=1)
        return pd.Timestamp(f"{nxt.date()} 15:00", tz="America/New_York").tz_convert(touched_at.tz)
    return None


def bar_ranges(bars: pd.DataFrame) -> pd.Series:
    r = bars.resample("60min", label="left", closed="left").agg({"high": "max", "low": "min"}).dropna()
    return r["high"] - r["low"]


def prev_completed_range(ranges: pd.Series, ts: pd.Timestamp) -> float | None:
    prev = ts.floor("60min") - pd.Timedelta(minutes=60)
    v = ranges.get(prev)
    return float(v) if v is not None and not pd.isna(v) and v > 0 else None


def simulate(path: pd.DataFrame, entry: float, sign: float, tp: float, sl: float) -> float:
    if path.empty:
        return 0.0
    target = entry + sign * tp
    stop   = entry - sign * sl
    for _, bar in path.iterrows():
        hi, lo = float(bar["high"]), float(bar["low"])
        if sign > 0:
            if lo <= stop: return -sl
            if hi >= target: return tp
        else:
            if hi >= stop: return -sl
            if lo <= target: return tp
    return sign * (float(path["close"].iloc[-1]) - entry)


def profit_factor(s: pd.Series) -> float:
    g = float(s[s > 0].sum())
    l = float(-s[s < 0].sum())
    return g / l if l > 0 else (float("inf") if g > 0 else 0.0)


def max_drawdown(s: pd.Series) -> float:
    eq = s.cumsum()
    return float((eq - eq.cummax()).min()) if not s.empty else 0.0


def max_streak(s: pd.Series) -> int:
    streak = best = 0
    for v in s:
        streak = streak + 1 if v < 0 else 0
        best   = max(best, streak)
    return best


def apply_sal(records: list[dict], col: str) -> pd.DataFrame:
    df = pd.DataFrame(records).sort_values("touched_at")
    kept = []
    for _, day in df.groupby("sess_date"):
        lost = False
        for _, row in day.iterrows():
            if not lost:
                kept.append(row.to_dict())
                if row[col] < 0:
                    lost = True
    return pd.DataFrame(kept)


# ── config P&L functions ──────────────────────────────────────────────────────

def pnl_sl_only(raw_sl: float, sl_cap: float, path: pd.DataFrame, entry: float, sign: float) -> float:
    """TP = raw_sl (uncapped), SL = min(raw_sl, sl_cap)."""
    sl = min(raw_sl, sl_cap)
    tp = raw_sl          # full original target
    return simulate(path, entry, sign, tp, sl)


def pnl_tp_sl_cap(raw_sl: float, sl_cap: float, path: pd.DataFrame, entry: float, sign: float) -> float:
    """TP = SL = min(raw_sl, sl_cap).  Equal risk, both capped."""
    cap = min(raw_sl, sl_cap)
    return simulate(path, entry, sign, cap, cap)


def pnl_cap_rr(raw_sl: float, sl_cap: float, rr: float, path: pd.DataFrame, entry: float, sign: float) -> float:
    """Codex cap+RR: SL=min(raw,cap), TP=min(raw, cap*rr). Tight trades unchanged (1:1)."""
    sl = min(raw_sl, sl_cap)
    tp = min(raw_sl, sl_cap * rr)
    return simulate(path, entry, sign, tp, sl)


# ── build raw ledger ──────────────────────────────────────────────────────────

def build_ledger(bars: pd.DataFrame, vxn: pd.Series) -> pd.DataFrame:
    all_levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges     = bar_ranges(bars)
    lvl_list   = list(all_levels.itertuples(index=False))
    records    = []

    for i, lv in enumerate(lvl_list):
        expiry = lvl_list[i + LINE_DAYS].created_at if i + LINE_DAYS < len(lvl_list) else bars.index[-1]
        search = bars.loc[lv.created_at: expiry]

        for side, col in (("upper", lv.upper_level), ("lower", lv.lower_level)):
            lvl  = float(col)
            ft   = _first_touch(search, lvl)
            if ft is None or not entry_allowed(ft):
                continue
            anchor = prev_completed_range(ranges, ft)
            if anchor is None:
                continue
            co = session_cutoff(ft)
            if co is None:
                continue
            path = bars.loc[ft: co].iloc[1:]
            if path.empty:
                continue

            records.append({
                "sess_date":   session_date(ft),
                "year":        pd.Timestamp(session_date(ft)).year,
                "side":        side,
                "touched_at":  ft,
                "level":       lvl,
                "anchor":      anchor,
                "raw_sl":      1.5 * anchor,
                "_path":       path,
                "_entry":      lvl,
                "_sign":       -1.0 if side == "upper" else 1.0,
            })

    return pd.DataFrame(records)


# ── run a config ──────────────────────────────────────────────────────────────

CONFIGS = [
    ("sl_only_cap160",  "sl_only",  160,  1.0),
    ("tp_sl_cap160",    "tp_sl",    160,  1.0),
    ("cap120_rr1.5",    "cap_rr",   120,  1.5),
    ("cap140_rr1.5",    "cap_rr",   140,  1.5),
    ("sl_only_cap200",  "sl_only",  200,  1.0),
    ("tp_sl_cap200",    "tp_sl",    200,  1.0),
]


def run_config(raw: pd.DataFrame, mode: str, sl_cap: float, rr: float, col_name: str) -> pd.DataFrame:
    pnls = []
    for _, row in raw.iterrows():
        p = row["_path"]
        e = row["_entry"]
        s = row["_sign"]
        rs = row["raw_sl"]
        if mode == "sl_only":
            pnl = pnl_sl_only(rs, sl_cap, p, e, s)
        elif mode == "tp_sl":
            pnl = pnl_tp_sl_cap(rs, sl_cap, p, e, s)
        else:
            pnl = pnl_cap_rr(rs, sl_cap, rr, p, e, s)
        pnls.append(pnl)
    df = raw.copy()
    df[col_name] = pnls
    return df


def summarize(df: pd.DataFrame, col: str, years: set[int]) -> dict:
    recs = df[["sess_date", "year", "touched_at", col, "raw_sl"]].rename(columns={col: "pts"}).to_dict("records")
    kept = apply_sal(recs, "pts")
    if kept.empty:
        return {}
    sub = kept[kept["year"].isin(years)]
    pts = sub["pts"]
    return {
        "n":      len(pts),
        "net":    float(pts.sum()),
        "pf":     profit_factor(pts),
        "wr":     float((pts > 0).mean()),
        "maxdd":  max_drawdown(pts),
        "streak": max_streak(pts),
        "df":     sub,
    }


def print_year_table(df: pd.DataFrame, col: str, label: str, all_years: list[int]) -> None:
    print(f"\n{'─'*72}")
    print(f"  {label}")
    print(f"{'─'*72}")
    print(f"  {'Year':6} {'Tag':4} {'n':>5} {'net':>10} {'PF':>7} {'WR':>6} {'maxDD':>10} {'streak':>7}")
    for yr in sorted(all_years):
        tag = "OOS" if yr in OOS_YEARS else "IS"
        recs = df[df["year"] == yr][["sess_date", "touched_at", col, "raw_sl"]].rename(columns={col: "pts"}).to_dict("records")
        kept = apply_sal(recs, "pts")
        if kept.empty:
            print(f"  {yr:6} {tag:4} {'—':>5}")
            continue
        pts = kept["pts"]
        print(f"  {yr:6} {tag:4} {len(pts):>5} {pts.sum():>10.2f} {profit_factor(pts):>7.3f} {(pts>0).mean():>6.3f} {max_drawdown(pts):>10.2f} {max_streak(pts):>7}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", required=True)
    parser.add_argument("--vxn",  default="data/vxn_daily_2020_2026.csv")
    args = parser.parse_args()

    print("Loading data …")
    bars = load_1m_ohlcv(args.bars)
    vxn  = load_gvz_daily(args.vxn)

    print("Building raw ledger (lineDays=20) …")
    raw = build_ledger(bars, vxn)
    print(f"  Raw touches (before SAL): {len(raw)}")

    all_years = sorted(IS_YEARS | OOS_YEARS)

    # ── Cross-validation summary table ──────────────────────────────────────
    print(f"\n{'='*80}")
    print("CROSS-VALIDATION SUMMARY")
    hdr = "cap\\RR"
    print(f"  {'Config':<20} {'IS n':>6} {'IS net':>10} {'IS PF':>7} {'IS WR':>6} {'IS DD':>10} {'st':>3}  |  {'OOS n':>6} {'OOS net':>9} {'OOS PF':>7} {'OOS DD':>9}")
    print("-" * 100)

    codex_ref = {
        "sl_only_cap160": ("Codex", 11857.8, 1.674, 2847.8, 1.649),
        "tp_sl_cap160":   ("Codex", 11287.0, 1.661, 2607.7, 1.595),
        "cap120_rr1.5":   ("Codex", 10186.2, 1.588, 2772.8, 1.647),
        "tp_sl_cap200":   ("Codex", 12040.8, 1.692, 2963.3, 1.679),
        "sl_only_cap200": ("Codex", 12142.8, 1.691, 2870.5, 1.658),
    }

    results = {}
    for name, mode, sl_cap, rr in CONFIGS:
        df = run_config(raw, mode, sl_cap, rr, "pnl")
        is_s  = summarize(df, "pnl", IS_YEARS)
        oos_s = summarize(df, "pnl", OOS_YEARS)
        results[name] = (df, is_s, oos_s)

        is_n   = is_s.get("n", 0)
        is_net = is_s.get("net", 0)
        is_pf  = is_s.get("pf", 0)
        is_wr  = is_s.get("wr", 0)
        is_dd  = is_s.get("maxdd", 0)
        is_st  = is_s.get("streak", 0)
        o_n    = oos_s.get("n", 0)
        o_net  = oos_s.get("net", 0)
        o_pf   = oos_s.get("pf", 0)
        o_dd   = oos_s.get("maxdd", 0)

        print(f"  {name:<20} {is_n:>6} {is_net:>10.2f} {is_pf:>7.3f} {is_wr:>6.3f} {is_dd:>10.2f} {is_st:>3}  |  {o_n:>6} {o_net:>9.2f} {o_pf:>7.3f} {o_dd:>9.2f}")

    # ── Codex reference ──────────────────────────────────────────────────────
    print(f"\n{'─'*100}")
    print("  Codex reference (for comparison):")
    for name, (src, is_net, is_pf, oos_net, oos_pf) in codex_ref.items():
        print(f"  {name:<20} {'':>6} {is_net:>10.1f} {is_pf:>7.3f} {'':>6} {'':>10} {'':>3}  |  {'':>6} {oos_net:>9.1f} {oos_pf:>7.3f}")

    # ── Year-by-year for each config ─────────────────────────────────────────
    for name, mode, sl_cap, rr in CONFIGS:
        df, _, _ = results[name]
        print_year_table(df, "pnl", f"{name}  (mode={mode}, sl_cap={sl_cap}, rr={rr})", all_years)

    print()


if __name__ == "__main__":
    main()
