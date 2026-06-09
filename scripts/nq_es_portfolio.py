#!/usr/bin/env python3
"""
ES sibling backtest — exact same mechanics as locked NQ tp_sl_cap200 strategy.

ES params (Codex canonical):
  sigma_mult  = 1.25
  ib_minutes  = 60
  offset      = sigma_day * 0.02   (dynamic, not fixed 15.75)
  vol_index   = VIX

Rules (identical to NQ):
  - lineDays=20 active levels
  - Fade first touch only (lower=long, upper=short)
  - Entry window 19:00–11:00 ET, skip 11:00–15:00
  - Session SAL: 19:00 ET → next-day 15:00 ET
  - TP = SL = min(1.5 × prev 1h range, 200)
  - No news/holiday/ATR filters

Outputs:
  1. ES y/y stats table
  2. NQ vs ES overlap analysis (±0, ±15, ±30, ±60 min)
  3. Portfolio variants: independent SAL vs global SAL
"""
from __future__ import annotations

import math
import os
import sys

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import InstrumentParams, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch

LINE_DAYS   = 20
SL_CAP      = 200.0
TRADING_DAYS = 252

ES_PARAMS = InstrumentParams(
    sigma_mult   = 1.25,
    offset_pct   = 0.02,   # sigma_day * 0.02  (no fixed_offset)
    ib_minutes   = 60,
    fixed_offset = None,
)


# ── helpers (identical to NQ script) ─────────────────────────────────────────

def entry_allowed(ts: pd.Timestamp) -> bool:
    et = ts.tz_convert("America/New_York")
    m  = et.hour * 60 + et.minute
    return not (660 <= m < 900)   # skip 11:00–15:00


def session_date(ts: pd.Timestamp) -> str:
    et = ts.tz_convert("America/New_York")
    if et.hour >= 19:
        return (et + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return et.strftime("%Y-%m-%d")


def session_cutoff(ts: pd.Timestamp) -> pd.Timestamp | None:
    et = ts.tz_convert("America/New_York")
    d  = et.strftime("%Y-%m-%d")
    co = pd.Timestamp(f"{d} 15:00", tz="America/New_York")
    re = pd.Timestamp(f"{d} 19:00", tz="America/New_York")
    if et < co:
        return co.tz_convert(ts.tz)
    if et >= re:
        nxt = et.normalize() + pd.Timedelta(days=1)
        return pd.Timestamp(f"{nxt.date()} 15:00", tz="America/New_York").tz_convert(ts.tz)
    return None


def bar_ranges(bars: pd.DataFrame) -> pd.Series:
    r = bars.resample("60min", label="left", closed="left").agg({"high": "max", "low": "min"}).dropna()
    return r["high"] - r["low"]


def prev_range(ranges: pd.Series, ts: pd.Timestamp) -> float | None:
    prev = ts.floor("60min") - pd.Timedelta(minutes=60)
    v    = ranges.get(prev)
    return float(v) if v is not None and not pd.isna(v) and v > 0 else None


def simulate(path: pd.DataFrame, entry: float, sign: float, tp: float, sl: float) -> float:
    if path.empty:
        return 0.0
    tgt = entry + sign * tp
    stp = entry - sign * sl
    for _, bar in path.iterrows():
        hi, lo = float(bar["high"]), float(bar["low"])
        if sign > 0:
            if lo <= stp: return -sl
            if hi >= tgt: return tp
        else:
            if hi >= stp: return -sl
            if lo <= tgt: return tp
    return sign * (float(path["close"].iloc[-1]) - entry)


def apply_sal(df: pd.DataFrame, col: str) -> pd.DataFrame:
    kept = []
    for _, day in df.sort_values("touched_at").groupby("sess_date"):
        lost = False
        for _, row in day.iterrows():
            if not lost:
                kept.append(row.to_dict())
                if row[col] < 0:
                    lost = True
    return pd.DataFrame(kept) if kept else pd.DataFrame()


# ── stat helpers ──────────────────────────────────────────────────────────────

def pf(s: pd.Series) -> float:
    g = float(s[s > 0].sum()); l = float(-s[s < 0].sum())
    return g / l if l > 0 else (float("inf") if g > 0 else 0.0)

def ann_sharpe(s: pd.Series) -> float:
    daily = s  # already session-level
    sd = daily.std(ddof=1)
    return float((daily.mean() / sd) * math.sqrt(TRADING_DAYS)) if sd > 0 else 0.0

def sortino(s: pd.Series) -> float:
    dd = s[s < 0]
    ds = math.sqrt(float((dd ** 2).mean())) if len(dd) > 0 else 1e-9
    return float((s.mean() / ds) * math.sqrt(TRADING_DAYS))


# ── build ES ledger ───────────────────────────────────────────────────────────

def build_es_ledger(bars: pd.DataFrame, vix: pd.Series) -> pd.DataFrame:
    all_levels = generate_levels(bars, vix, params=ES_PARAMS)
    ranges     = bar_ranges(bars)
    lvl_list   = list(all_levels.itertuples(index=False))
    records    = []

    for i, lv in enumerate(lvl_list):
        expiry = lvl_list[i + LINE_DAYS].created_at if i + LINE_DAYS < len(lvl_list) else bars.index[-1]
        search = bars.loc[lv.created_at: expiry]

        for side, col in (("upper", lv.upper_level), ("lower", lv.lower_level)):
            lvl = float(col)
            ft  = _first_touch(search, lvl)
            if ft is None or not entry_allowed(ft):
                continue
            anchor = prev_range(ranges, ft)
            if anchor is None:
                continue
            co = session_cutoff(ft)
            if co is None:
                continue
            path = bars.loc[ft: co].iloc[1:]
            if path.empty:
                continue

            cap  = min(1.5 * anchor, SL_CAP)
            sign = -1.0 if side == "upper" else 1.0
            pnl  = simulate(path, lvl, sign, cap, cap)

            records.append({
                "sess_date":  session_date(ft),
                "year":       pd.Timestamp(session_date(ft)).year,
                "side":       side,
                "touched_at": ft,
                "exit_ts":    co,
                "level":      lvl,
                "anchor":     anchor,
                "stop_pts":   cap,
                "pnl":        pnl,
            })

    return pd.DataFrame(records)


# ── year-by-year table ────────────────────────────────────────────────────────

def print_yy(df: pd.DataFrame, col: str, label: str) -> None:
    print(f"\n{'='*95}")
    print(f"  {label}")
    print(f"{'='*95}")
    print(f"  {'Year':4} {'n':>4} {'net pts':>9} {'PF':>6} {'WR':>6} {'Sortino':>8} {'Ann Sharpe':>11}")
    print(f"  {'-'*75}")
    for yr in sorted(df["year"].unique()):
        sub  = df[df["year"] == yr][col]
        sess = df[df["year"] == yr].groupby("sess_date")[col].sum()
        print(f"  {yr:4} {len(sub):>4} {sub.sum():>9.1f} {pf(sub):>6.3f} {(sub>0).mean():>6.3f} "
              f"{sortino(sess):>8.2f} {ann_sharpe(sess):>11.2f}")
    print(f"  {'-'*75}")
    all_sess = df.groupby("sess_date")[col].sum()
    print(f"  {'ALL':4} {len(df):>4} {df[col].sum():>9.1f} {pf(df[col]):>6.3f} {(df[col]>0).mean():>6.3f} "
          f"{sortino(all_sess):>8.2f} {ann_sharpe(all_sess):>11.2f}")


# ── overlap analysis ──────────────────────────────────────────────────────────

def overlap_analysis(es_df: pd.DataFrame, nq_ledger: pd.DataFrame) -> None:
    """Compare ES touches against NQ active positions."""
    # Parse NQ entry/exit timestamps
    nq = nq_ledger[["entry_ts", "exit_ts", "session_id", "pnl_pts"]].copy()
    nq["entry_ts"] = pd.to_datetime(nq["entry_ts"], utc=True)
    nq["exit_ts"]  = pd.to_datetime(nq["exit_ts"],  utc=True)

    def nq_active_at(ts: pd.Timestamp) -> bool:
        return bool(((nq["entry_ts"] <= ts) & (nq["exit_ts"] >= ts)).any())

    def nq_within(ts: pd.Timestamp, minutes: int) -> bool:
        window = pd.Timedelta(minutes=minutes)
        return bool((((nq["entry_ts"] - window) <= ts) & (ts <= (nq["exit_ts"] + window))).any())

    es = es_df.copy()
    es["nq_overlap_exact"] = es["touched_at"].apply(nq_active_at)
    es["nq_within_15"]     = es["touched_at"].apply(lambda t: nq_within(t, 15))
    es["nq_within_30"]     = es["touched_at"].apply(lambda t: nq_within(t, 30))
    es["nq_within_60"]     = es["touched_at"].apply(lambda t: nq_within(t, 60))

    print(f"\n{'='*75}")
    print("  NQ / ES OVERLAP ANALYSIS")
    print(f"{'='*75}")
    total = len(es)
    for label, col in [
        ("ES trades with NQ live at entry (exact overlap)", "nq_overlap_exact"),
        ("ES entries within ±15 min of any NQ trade",       "nq_within_15"),
        ("ES entries within ±30 min of any NQ trade",       "nq_within_30"),
        ("ES entries within ±60 min of any NQ trade",       "nq_within_60"),
    ]:
        n   = es[col].sum()
        sub = es[es[col]]["pnl"]
        nin = es[~es[col]]["pnl"]
        print(f"\n  {label}")
        print(f"    Overlap  : n={n:3d} ({100*n/total:.0f}%)  net={sub.sum():7.1f}  PF={pf(sub):.3f}  WR={(sub>0).mean():.3f}")
        print(f"    No overlap: n={total-n:3d} ({100*(total-n)/total:.0f}%)  net={nin.sum():7.1f}  PF={pf(nin):.3f}  WR={(nin>0).mean():.3f}")

    return es


# ── portfolio variants ────────────────────────────────────────────────────────

def portfolio_stats(es_df: pd.DataFrame, nq_ledger: pd.DataFrame, es_col: str = "pnl") -> None:
    nq = nq_ledger[["entry_ts", "session_id", "pnl_pts"]].copy()
    nq["entry_ts"]   = pd.to_datetime(nq["entry_ts"], utc=True)
    nq["sess_date"]  = nq["session_id"]
    nq["pnl"]        = nq["pnl_pts"]
    nq["instrument"] = "NQ"

    es = es_df[["touched_at", "sess_date", es_col]].copy()
    es = es.rename(columns={es_col: "pnl", "touched_at": "entry_ts"})
    es["instrument"] = "ES"

    # ── Variant A: independent SAL (already applied) ─────────────────────────
    print(f"\n{'='*75}")
    print("  PORTFOLIO VARIANT A — NQ and ES with independent session SAL")
    print(f"{'='*75}")
    nq_net = nq["pnl"].sum()
    es_net = es["pnl"].sum()
    combo  = pd.concat([nq[["sess_date","pnl"]], es[["sess_date","pnl"]]])
    daily  = combo.groupby("sess_date")["pnl"].sum()
    print(f"  NQ net: {nq_net:.1f}  ES net: {es_net:.1f}  Combined: {nq_net+es_net:.1f}")
    print(f"  Combined Ann Sharpe: {ann_sharpe(daily):.2f}   Sortino: {sortino(daily):.2f}")
    print(f"  Combined PF: {pf(combo['pnl']):.3f}   WR: {(combo['pnl']>0).mean():.3f}")

    # ── Variant B: global SAL (first loss on either instrument stops the session)
    print(f"\n{'='*75}")
    print("  PORTFOLIO VARIANT B — Global SAL (first loss on either stops the session)")
    print(f"{'='*75}")
    all_trades = pd.concat([
        nq[["entry_ts","sess_date","pnl","instrument"]],
        es[["entry_ts","sess_date","pnl","instrument"]]
    ]).sort_values("entry_ts")

    kept = []
    for _, day in all_trades.groupby("sess_date"):
        lost = False
        for _, row in day.iterrows():
            if not lost:
                kept.append(row.to_dict())
                if row["pnl"] < 0:
                    lost = True
    kdf   = pd.DataFrame(kept)
    daily = kdf.groupby("sess_date")["pnl"].sum()
    print(f"  Trades kept: {len(kdf)}  Net: {kdf['pnl'].sum():.1f}")
    print(f"  Ann Sharpe: {ann_sharpe(daily):.2f}   Sortino: {sortino(daily):.2f}")
    print(f"  PF: {pf(kdf['pnl']):.3f}   WR: {(kdf['pnl']>0).mean():.3f}")
    nq_k  = kdf[kdf["instrument"]=="NQ"]["pnl"]
    es_k  = kdf[kdf["instrument"]=="ES"]["pnl"]
    print(f"  NQ kept: {len(nq_k)} ({nq_k.sum():.1f})   ES kept: {len(es_k)} ({es_k.sum():.1f})")

    # ── Correlation check ─────────────────────────────────────────────────────
    print(f"\n{'='*75}")
    print("  CORRELATION — daily session P&L (NQ vs ES, shared sessions only)")
    print(f"{'='*75}")
    nq_daily = nq.groupby("sess_date")["pnl"].sum()
    es_daily = es.groupby("sess_date")["pnl"].sum()
    shared   = nq_daily.index.intersection(es_daily.index)
    if len(shared) > 5:
        corr = float(nq_daily[shared].corr(es_daily[shared]))
        print(f"  Shared sessions: {len(shared)}   Pearson r: {corr:.3f}")
        if abs(corr) > 0.6:
            print("  ⚠  High correlation — ES largely mirrors NQ beta risk")
        elif abs(corr) > 0.3:
            print("  ~  Moderate correlation — partial diversification benefit")
        else:
            print("  ✓  Low correlation — meaningful independent edge")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--es-bars",   default="data/es_1m/es_continuous_2024_2026_1m.csv")
    parser.add_argument("--vix",       default="data/vix_daily_2020_2026.csv")
    parser.add_argument("--nq-ledger", default="data/nq_master_ledger.csv")
    args = parser.parse_args()

    print("Loading ES bars …")
    bars = load_1m_ohlcv(args.es_bars)
    print(f"  {len(bars):,} bars  {bars.index[0].date()} → {bars.index[-1].date()}")

    print("Loading VIX …")
    vix = load_gvz_daily(args.vix)

    print("Generating ES levels + ledger …")
    raw = build_es_ledger(bars, vix)
    print(f"  Raw ES touches (before SAL): {len(raw)}")

    es = apply_sal(raw, "pnl")
    print(f"  After SAL: {len(es)} trades")

    # Save ledger
    out = "data/es_canonical_ledger.csv"
    es.to_csv(out, index=False)
    print(f"  Saved → {out}")

    print_yy(es, "pnl", "ES tp_sl_cap200  |  TP=SL=min(1.5×anchor,200)  |  offset=sigma_day×0.02  |  VIX")

    # Load NQ master ledger
    if not os.path.exists(args.nq_ledger):
        print(f"\n  NQ ledger not found at {args.nq_ledger} — skipping overlap analysis")
        return

    nq_ledger = pd.read_csv(args.nq_ledger)

    # Filter NQ to years covered by ES data
    es_years = set(es["year"].unique())
    nq_fil   = nq_ledger[nq_ledger["year"].isin(es_years)].copy()
    print(f"\n  NQ trades in ES years {sorted(es_years)}: {len(nq_fil)}")

    es_with_flags = overlap_analysis(es, nq_fil)
    portfolio_stats(es_with_flags, nq_fil)


if __name__ == "__main__":
    main()
