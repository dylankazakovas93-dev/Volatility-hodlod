#!/usr/bin/env python3
"""
NQ level-fade: cross-validate Codex's cap+RR variants, curve-fitting diagnostics,
and Monte Carlo simulation with prop firm rules.

Codex variant model:
  raw_sl = raw_tp = 1.5 * anchor
  capped_sl = min(raw_sl, SL_CAP)
  TP = capped_sl * RR          (not raw TP — both derived from capped SL)
  SL = capped_sl

Monte Carlo:
  - Resample trade sequences (with replacement, preserving session SAL blocks)
  - Apply prop firm rules per simulation path
  - Report pass rate, expected drawdown distribution, time-to-breach

Prop rules modelled:
  - Daily loss limit (DDL): breach if any session net < -DDL
  - Max trailing drawdown (MTD): breach if equity from peak drops > MTD
  - Profit target (PT): pass when equity from start >= PT
  - Consistency cap: no single day may contribute > CONS_PCT of total profit
    (many prop firms use 30-50%)
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch

LINE_DAYS = 20
MNQ_PTS  = 2.0  # $/pt per micro


# ── shared helpers ─────────────────────────────────────────────────────────────

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


def prev_completed_range(ranges: pd.Series, ts: pd.Timestamp) -> float | None:
    prev = ts.floor("60min") - pd.Timedelta(minutes=60)
    v = ranges.get(prev)
    return float(v) if v is not None and not pd.isna(v) and v > 0 else None


def simulate(path_bars: pd.DataFrame, entry: float, sign: float, tp_pts: float, sl_pts: float) -> tuple[str, float]:
    if path_bars.empty:
        return "no_path", 0.0
    target = entry + sign * tp_pts
    stop   = entry - sign * sl_pts
    for _, bar in path_bars.iterrows():
        hi, lo = float(bar["high"]), float(bar["low"])
        if sign > 0:
            hs, ht = lo <= stop, hi >= target
        else:
            hs, ht = hi >= stop, lo <= target
        if hs:
            return "SL", -sl_pts
        if ht:
            return "TP",  tp_pts
    return "cutoff", sign * (float(path_bars["close"].iloc[-1]) - entry)


# ── stat helpers ───────────────────────────────────────────────────────────────

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


def max_loss_streak(pts) -> int:
    streak = best = 0
    for v in pts:
        streak = streak + 1 if v < 0 else 0
        best   = max(best, streak)
    return best


def apply_session_sal(records: list[dict], pts_col: str) -> list[dict]:
    df = pd.DataFrame(records).sort_values("touched_at")
    kept = []
    for _, day in df.groupby("sess_date"):
        lost = False
        for _, row in day.iterrows():
            r = row.to_dict()
            r["sal_excluded"] = False
            if lost:
                r["sal_excluded"] = True
            elif r[pts_col] < 0:
                lost = True
            kept.append(r)
    return kept


# ── build raw ledger (reused across all variants) ─────────────────────────────

def build_raw_ledger(bars: pd.DataFrame, vxn: pd.Series) -> pd.DataFrame:
    all_levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges     = bar_ranges(bars, 60)
    lvl_list   = list(all_levels.itertuples(index=False))
    records    = []

    for i, lv in enumerate(lvl_list):
        expiry = lvl_list[i + LINE_DAYS].created_at if i + LINE_DAYS < len(lvl_list) else bars.index[-1]
        search = bars.loc[lv.created_at: expiry]

        for side, col in (("upper", lv.upper_level), ("lower", lv.lower_level)):
            lvl    = float(col)
            ft     = _first_touch(search, lvl)
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

            sign    = -1.0 if side == "upper" else 1.0
            raw_sl  = 1.5 * anchor   # raw SL = raw TP = 1.5x anchor

            records.append({
                "level_sess":  str(lv.session_date),
                "touched_at":  ft,
                "sess_date":   session_date(ft),
                "year":        pd.Timestamp(session_date(ft)).year,
                "side":        side,
                "level":       lvl,
                "anchor":      anchor,
                "raw_sl":      raw_sl,
                "_path_start": path.index[0],
                "_cutoff_ts":  co,
                "_entry":      lvl,
                "_sign":       sign,
            })

    return pd.DataFrame(records)


def resim(bars: pd.DataFrame, raw: pd.DataFrame, sl_cap: float, rr: float) -> pd.Series:
    """Codex model:
      SL = min(raw_sl, sl_cap)
      TP = min(raw_sl, sl_cap * rr)   ← cap TP at sl_cap*rr; don't inflate tight trades
    For tight trades (raw_sl <= sl_cap): SL=raw_sl, TP=raw_sl → original 1:1 RR preserved.
    For wide trades  (raw_sl >  sl_cap): SL=sl_cap, TP=sl_cap*rr → RR multiplier applies.
    """
    results = []
    for _, row in raw.iterrows():
        raw_sl = row["raw_sl"]
        csl    = min(raw_sl, sl_cap)
        tp     = min(raw_sl, sl_cap * rr)   # never increase TP beyond raw; cap wide trades
        path   = bars.loc[row["_path_start"]: row["_cutoff_ts"]]
        _, pnl = simulate(path, row["_entry"], row["_sign"], tp, csl)
        results.append(pnl)
    return pd.Series(results, index=raw.index)


def apply_and_summarize(raw: pd.DataFrame, pnl_col: str, years: set[int]) -> dict:
    recs = raw.to_dict("records")
    sal  = apply_session_sal(recs, pnl_col)
    df   = pd.DataFrame(sal)
    kept = df[~df["sal_excluded"] & df["year"].isin(years)]
    pts  = kept[pnl_col]
    if pts.empty:
        return {}
    return {
        "n":      len(pts),
        "net":    float(pts.sum()),
        "pf":     profit_factor(pts),
        "wr":     float((pts > 0).mean()),
        "maxdd":  max_drawdown(pts),
        "streak": max_loss_streak(pts.values),
        "maxsl":  float(kept["raw_sl"].clip(upper=raw[pnl_col.replace("pnl_","raw_sl").replace("pnl","raw_sl")].max()).clip(upper=min(kept["raw_sl"].max(), float(pnl_col.split("_")[1]) if "_" in pnl_col else 9999)).max()) if False else float(kept["raw_sl"].min()),  # placeholder
        "df_kept": kept,
    }


# ── curve-fitting diagnostics ─────────────────────────────────────────────────

def curve_fit_diagnostics(kept: pd.DataFrame, pnl_col: str, label: str, all_years: list[int]) -> None:
    print(f"\n  [{label}] Curve-fitting diagnostics:")
    annual_nets = []
    for yr in sorted(all_years):
        sub = kept[kept["year"] == yr][pnl_col]
        net = float(sub.sum())
        n   = len(sub)
        annual_nets.append(net)
        tag = ""
        if net < 0:
            tag = " *** NEGATIVE YEAR"
        print(f"    {yr}: n={n:3d}  net={net:8.2f}{tag}")

    nets = np.array(annual_nets)
    mean_ann = nets.mean()
    std_ann  = nets.std(ddof=1) if len(nets) > 1 else 0.0
    sharpe   = mean_ann / std_ann if std_ann > 0 else float("inf")
    t_stat   = mean_ann / (std_ann / math.sqrt(len(nets))) if std_ann > 0 else float("inf")
    n_neg    = int((nets < 0).sum())
    pct_above_zero = 100 * float((nets > 0).mean())

    print(f"    Annual Sharpe (pts): {sharpe:.3f}   t-stat: {t_stat:.3f}")
    print(f"    Positive years: {int((nets > 0).sum())}/{len(nets)} ({pct_above_zero:.0f}%)")
    print(f"    Mean annual net: {mean_ann:.1f}   Std: {std_ann:.1f}   Min: {nets.min():.1f}   Max: {nets.max():.1f}")
    if n_neg > 0:
        print(f"    WARNING: {n_neg} negative year(s) in IS — fragility flag")
    if sharpe < 1.0:
        print(f"    WARNING: annual Sharpe < 1.0 — high year-to-year variance relative to mean")


# ── Monte Carlo simulator ─────────────────────────────────────────────────────

def run_montecarlo(
    session_daily_pnls: list[float],   # list of per-session net P&L (after SAL), in dollars
    n_sims: int,
    account_size: float,               # starting equity
    profit_target_pct: float,          # pass when equity >= account * (1 + PT_PCT)
    max_daily_loss: float,             # breach if single session < -DDL (dollars)
    max_trailing_dd: float,            # breach if equity drops > MTD from peak
    consistency_cap_pct: float,        # no single day > this % of total profit (0 = off)
    n_sessions: int,                   # how many sessions to run each sim
    rng_seed: int = 42,
) -> dict:
    rng = np.random.default_rng(rng_seed)
    sessions = np.array(session_daily_pnls, dtype=float)

    profit_target = account_size * profit_target_pct
    results = {
        "passed": 0,
        "breached_daily": 0,
        "breached_dd": 0,
        "breached_consistency": 0,
        "still_running": 0,
        "days_to_pass": [],
        "final_equity": [],
        "max_dd_seen": [],
    }

    for _ in range(n_sims):
        # Bootstrap: sample n_sessions from the session P&L pool
        draws = rng.choice(sessions, size=n_sessions, replace=True)
        equity = account_size
        peak   = account_size
        passed = False
        breached = False
        breach_type = None
        cumulative_profit = 0.0
        day_profits = []

        # Fixed dollar daily profit cap = consistency_cap_pct × profit_target
        # Most prop firms check this at evaluation end, but we flag any single day
        # exceeding the cap as a consistency breach (conservative).
        daily_profit_cap = consistency_cap_pct * profit_target if consistency_cap_pct > 0 else float("inf")

        for day_i, sess_pnl in enumerate(draws):
            # Daily loss limit check
            if sess_pnl < -max_daily_loss:
                breached = True
                breach_type = "daily"
                break

            equity += sess_pnl
            cumulative_profit += sess_pnl
            day_profits.append(sess_pnl)
            peak = max(peak, equity)

            # Trailing drawdown check
            if (peak - equity) > max_trailing_dd:
                breached = True
                breach_type = "dd"
                break

            # Consistency check: single day profit cap (fixed $ = cap_pct × profit_target)
            if consistency_cap_pct > 0 and sess_pnl > daily_profit_cap:
                breached = True
                breach_type = "consistency"
                break

            # Profit target check
            if equity - account_size >= profit_target:
                passed = True
                results["days_to_pass"].append(day_i + 1)
                break

        if passed:
            results["passed"] += 1
        elif breached:
            results[f"breached_{breach_type}"] += 1
        else:
            results["still_running"] += 1

        results["final_equity"].append(equity)
        results["max_dd_seen"].append(float(peak - min(equity, peak)))  # simplified; actual max

    # Compute max drawdown per path more accurately
    max_dds = []
    for _ in range(min(n_sims, 1000)):  # compute accurate DD on subset
        draws = rng.choice(sessions, size=n_sessions, replace=True)
        eq = account_size + np.cumsum(draws)
        eq_series = np.concatenate([[account_size], eq])
        peaks = np.maximum.accumulate(eq_series)
        dd = float((peaks - eq_series).max())
        max_dds.append(dd)
    results["max_dd_seen"] = max_dds

    total = n_sims
    results["pass_rate"]      = results["passed"] / total
    results["breach_daily_rate"] = results["breached_daily"] / total
    results["breach_dd_rate"] = results["breached_dd"] / total
    results["breach_cons_rate"] = results["breached_consistency"] / total
    results["p50_final_equity"] = float(np.percentile(results["final_equity"], 50))
    results["p10_final_equity"] = float(np.percentile(results["final_equity"], 10))
    results["p90_final_equity"] = float(np.percentile(results["final_equity"], 90))
    results["p50_max_dd"] = float(np.percentile(results["max_dd_seen"], 50))
    results["p90_max_dd"] = float(np.percentile(results["max_dd_seen"], 90))
    results["p95_max_dd"] = float(np.percentile(results["max_dd_seen"], 95))
    results["median_days_to_pass"] = float(np.median(results["days_to_pass"])) if results["days_to_pass"] else float("nan")
    return results


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars",             required=True)
    parser.add_argument("--vxn",              default="data/vxn_daily_2020_2026.csv")
    parser.add_argument("--in-sample-years",  default="2021,2023,2024,2025,2026")
    parser.add_argument("--oos-year",         default="2022")
    parser.add_argument("--mc-sims",          type=int, default=10000)
    parser.add_argument("--mc-sessions",      type=int, default=120,
                        help="Sessions per sim path (~6 months of trading)")
    parser.add_argument("--account",          type=float, default=50000,
                        help="Prop account starting equity $")
    parser.add_argument("--profit-target-pct", type=float, default=0.08,
                        help="Pass when equity gains this fraction of account (default 8%%)")
    parser.add_argument("--daily-loss-limit", type=float, default=1000,
                        help="Max session loss before breach ($)")
    parser.add_argument("--max-trailing-dd",  type=float, default=2500,
                        help="Max trailing drawdown before breach ($)")
    parser.add_argument("--consistency-cap",  type=float, default=0.40,
                        help="No single day > this fraction of total profit (0=off)")
    parser.add_argument("--micros",           type=int,   default=2,
                        help="Number of MNQ micros per trade")
    args = parser.parse_args()

    in_sample = {int(y) for y in args.in_sample_years.split(",")}
    oos_year  = int(args.oos_year)
    all_years = sorted(in_sample | {oos_year})

    print("Loading data …")
    bars = load_1m_ohlcv(args.bars)
    vxn  = load_gvz_daily(args.vxn)

    print("Building raw ledger (lineDays=20) …")
    raw = build_raw_ledger(bars, vxn)
    print(f"  Raw touches (before SAL): {len(raw)}")

    # ── REPRODUCE CODEX'S CAP+RR TABLE ───────────────────────────────────────
    variants = [
        ("cap120 RR1.5",  120, 1.5),
        ("cap120 RR1.25", 120, 1.25),
        ("cap120 RR1.0",  120, 1.0),
        ("cap120 RR2.0",  120, 2.0),
        ("cap100 RR2.0",  100, 2.0),
        ("cap100 RR1.5",  100, 1.5),
        ("cap80  RR1.5",   80, 1.5),
        ("cap140 RR1.5",  140, 1.5),
        ("cap160 RR1.5",  160, 1.5),  # close to baseline
    ]

    print(f"\n{'='*80}")
    print("CROSS-VALIDATION: Codex cap+RR variants")
    print(f"{'SL cap/RR':20} {'IS n':>6} {'IS net':>9} {'IS PF':>7} {'IS WR':>6} "
          f"{'IS DD':>8} {'streak':>6}  |  {'OOS n':>6} {'OOS net':>9} {'OOS PF':>7} {'OOS DD':>8}")
    print("-" * 110)

    best_variant = None
    best_col     = None

    for label, sl_cap, rr in variants:
        col = f"pnl_{label.replace(' ','_')}"
        raw[col] = resim(bars, raw, sl_cap, rr)

        # IS
        recs_is = apply_session_sal(raw.to_dict("records"), col)
        df_is   = pd.DataFrame(recs_is)
        kept_is = df_is[~df_is["sal_excluded"] & df_is["year"].isin(in_sample)]
        pts_is  = kept_is[col]

        # OOS
        kept_oos = df_is[~df_is["sal_excluded"] & (df_is["year"] == oos_year)]
        pts_oos  = kept_oos[col]

        maxsl_is = float(kept_is["raw_sl"].clip(upper=sl_cap).max())

        def fmt(pts):
            if pts.empty:
                return "     —         —      —"
            return (f"{len(pts):6d} {pts.sum():9.2f} {profit_factor(pts):7.3f} "
                    f"{float((pts>0).mean()):6.3f} {max_drawdown(pts):8.2f} "
                    f"{max_loss_streak(pts.values):6d}")

        print(f"  {label:20} {fmt(pts_is)}  |  "
              f"{len(pts_oos):6d} {pts_oos.sum():9.2f} {profit_factor(pts_oos):7.3f} "
              f"{max_drawdown(pts_oos):8.2f}")

        if label == "cap120 RR1.5":
            best_variant = (label, sl_cap, rr, kept_is, kept_oos, col)
            best_col     = col

    # ── YEAR-BY-YEAR FOR TOP CANDIDATE ───────────────────────────────────────
    label_b, sl_cap_b, rr_b, kept_is_b, kept_oos_b, col_b = best_variant
    print(f"\n{'='*80}")
    print(f"YEAR-BY-YEAR: {label_b} (top candidate)")
    print(f"{'='*80}")

    recs_all = apply_session_sal(raw.to_dict("records"), col_b)
    df_all   = pd.DataFrame(recs_all)
    kept_all = df_all[~df_all["sal_excluded"]]
    print(f"  {'Year':6} {'Tag':4} {'n':>5} {'net':>9} {'PF':>7} {'WR':>6} {'maxDD':>8} {'streak':>6} {'maxSL':>7}")
    for yr in sorted(all_years):
        sub  = kept_all[kept_all["year"] == yr]
        pts  = sub[col_b]
        tag  = "IS" if yr in in_sample else "OOS"
        pf   = profit_factor(pts)
        wr   = float((pts > 0).mean()) if not pts.empty else 0.0
        dd   = max_drawdown(pts)
        ls   = max_loss_streak(pts.values)
        msl  = float(sub["raw_sl"].clip(upper=sl_cap_b).max()) if not sub.empty else 0
        print(f"  {yr:6d} {tag:4} {len(pts):5d} {pts.sum():9.2f} {pf:7.3f} {wr:6.3f} {dd:8.2f} {ls:6d} {msl:7.1f}")

    # ── CURVE-FITTING DIAGNOSTICS ─────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("CURVE-FITTING DIAGNOSTICS")
    print(f"{'='*80}")
    print("  Tests: all years positive, annual Sharpe, t-stat, consistency\n")

    # Compare baseline vs cap120 RR1.5
    for diag_label, diag_col, diag_sl_cap in [
        ("Baseline (SL cap=160, RR=1.0)", "pnl_cap160_RR1.0", 160),
        ("cap120 RR1.5 [top candidate]",  col_b, 120),
    ]:
        # Recompute baseline if needed
        if diag_col not in raw.columns:
            raw[diag_col] = resim(bars, raw, diag_sl_cap, 1.0)
        recs_d = apply_session_sal(raw.to_dict("records"), diag_col)
        df_d   = pd.DataFrame(recs_d)
        kept_d = df_d[~df_d["sal_excluded"]]
        # Use ALL years for diagnostics
        curve_fit_diagnostics(kept_d, diag_col, diag_label, sorted(all_years))

    # Additional: parameter sensitivity around cap120 RR1.5
    print(f"\n  Parameter sensitivity (nearby cap/RR combos, IS net):")
    header = "cap\\RR"
    print(f"  {header:8} {'1.0':>9} {'1.25':>9} {'1.5':>9} {'2.0':>9}")
    for cap in [100, 110, 120, 130, 140]:
        row_vals = []
        for rr in [1.0, 1.25, 1.5, 2.0]:
            c = f"_sens_{cap}_{rr}"
            raw[c] = resim(bars, raw, float(cap), rr)
            recs = apply_session_sal(raw.to_dict("records"), c)
            df   = pd.DataFrame(recs)
            kept = df[~df["sal_excluded"] & df["year"].isin(in_sample)]
            row_vals.append(kept[c].sum())
        print(f"  cap={cap:3d}    {row_vals[0]:9.0f} {row_vals[1]:9.0f} {row_vals[2]:9.0f} {row_vals[3]:9.0f}")

    # ── MONTE CARLO ───────────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("MONTE CARLO SIMULATION — prop firm challenge")
    print(f"  Account: ${args.account:,.0f}")
    print(f"  Profit target: {args.profit_target_pct*100:.0f}%  = ${args.account * args.profit_target_pct:,.0f}")
    print(f"  Daily loss limit: ${args.daily_loss_limit:,.0f}")
    print(f"  Max trailing drawdown: ${args.max_trailing_dd:,.0f}")
    print(f"  Consistency cap: {args.consistency_cap*100:.0f}% of total profit per day")
    print(f"  Contracts: {args.micros} MNQ micro(s) @ $2/pt each")
    print(f"  Sessions per sim: {args.mc_sessions}  Simulations: {args.mc_sims:,}")
    print(f"{'='*80}")

    # Build per-session P&L for the MC (cap120 RR1.5 variant)
    recs_mc = apply_session_sal(raw.to_dict("records"), col_b)
    df_mc   = pd.DataFrame(recs_mc)

    # Use ALL years (2021-2026 + 2022) for the MC pool
    kept_mc  = df_mc[~df_mc["sal_excluded"]]

    # Build session-level daily P&L (dollar)
    sess_dollar = (
        kept_mc.groupby("sess_date")[col_b].sum() * args.micros * MNQ_PTS
    ).values.tolist()

    print(f"\n  Session P&L pool: {len(sess_dollar)} sessions, "
          f"mean=${np.mean(sess_dollar):.2f}, "
          f"std=${np.std(sess_dollar):.2f}, "
          f"min=${min(sess_dollar):.2f}, "
          f"max=${max(sess_dollar):.2f}")
    print(f"  Positive sessions: {100*np.mean(np.array(sess_dollar)>0):.1f}%")

    # Run multiple sizing scenarios
    mc_scenarios = [
        (f"1 micro  cap120 RR1.5",  1),
        (f"2 micros cap120 RR1.5",  2),
    ]
    if args.micros not in [1, 2]:
        mc_scenarios.append((f"{args.micros} micros", args.micros))

    for mc_label, n_mic in mc_scenarios:
        # Rebuild session pool for this sizing
        sess_pool = (
            kept_mc.groupby("sess_date")[col_b].sum() * n_mic * MNQ_PTS
        ).values.tolist()

        res = run_montecarlo(
            session_daily_pnls   = sess_pool,
            n_sims               = args.mc_sims,
            account_size         = args.account,
            profit_target_pct    = args.profit_target_pct,
            max_daily_loss       = args.daily_loss_limit,
            max_trailing_dd      = args.max_trailing_dd,
            consistency_cap_pct  = args.consistency_cap,
            n_sessions           = args.mc_sessions,
        )

        print(f"\n  ── {mc_label} ──")
        print(f"    Pass rate:            {res['pass_rate']*100:6.1f}%")
        print(f"    Breach (daily limit): {res['breach_daily_rate']*100:6.1f}%")
        print(f"    Breach (trailing DD): {res['breach_dd_rate']*100:6.1f}%")
        print(f"    Breach (consistency): {res['breach_cons_rate']*100:6.1f}%")
        print(f"    Still running at end: {res['still_running']/args.mc_sims*100:6.1f}%")
        print(f"    Median days to pass:  {res['median_days_to_pass']:.0f} sessions")
        print(f"    Final equity p10/p50/p90: "
              f"${res['p10_final_equity']:,.0f} / ${res['p50_final_equity']:,.0f} / ${res['p90_final_equity']:,.0f}")
        print(f"    Max DD seen p50/p90/p95:  "
              f"${res['p50_max_dd']:,.0f} / ${res['p90_max_dd']:,.0f} / ${res['p95_max_dd']:,.0f}")

    # Additional MC: sensitivity to daily_loss_limit
    print(f"\n  ── Sensitivity to daily loss limit (2 micros, other rules fixed) ──")
    print(f"  {'DDL ($)':>10} {'Pass%':>8} {'Breach DD%':>12} {'Breach Day%':>13} {'Median days':>12}")
    for ddl in [500, 750, 1000, 1500, 2000]:
        sess_pool = (
            kept_mc.groupby("sess_date")[col_b].sum() * 2 * MNQ_PTS
        ).values.tolist()
        res = run_montecarlo(
            session_daily_pnls   = sess_pool,
            n_sims               = 5000,
            account_size         = args.account,
            profit_target_pct    = args.profit_target_pct,
            max_daily_loss       = ddl,
            max_trailing_dd      = args.max_trailing_dd,
            consistency_cap_pct  = args.consistency_cap,
            n_sessions           = args.mc_sessions,
        )
        print(f"  {ddl:10.0f} {res['pass_rate']*100:8.1f} "
              f"{res['breach_dd_rate']*100:12.1f} "
              f"{res['breach_daily_rate']*100:13.1f} "
              f"{res['median_days_to_pass']:12.0f}")


if __name__ == "__main__":
    main()
