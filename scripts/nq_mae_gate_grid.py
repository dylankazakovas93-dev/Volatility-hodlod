#!/usr/bin/env python3
"""Test: tighten the stop early if MAE hasn't shown real heat yet.

Three things tested, all on the exact canonical entry set (same touches,
same cap formula, same SAL):

1. MAE-GATE: at bar `gate_bar`, if the trade's running MAE has never
   exceeded `gate_frac` x cap (i.e. it's been flat/in-profit/only mildly
   underwater this whole time), tighten the stop from full -cap to
   -gate_frac*cap right then. Conditional BE@45 still layers on top and
   can tighten further to entry. The stop only ever ratchets toward
   entry, never loosens. Swept across several gate_bar values.

2. ASYMMETRIC RR: TP = tp_frac*cap (smaller target, reached more often),
   SL stays the full cap (so SL is a fixed multiple of TP -- 1/tp_frac).
   Crossed with the MAE-gate above.

3. BE-TAKE-NOW: instead of arming BE at bar 45 and continuing to hold
   (worst case scratch, upside uncapped), close the trade immediately at
   the bar-45 open price if it's on the profit side then. If it's not on
   the profit side at bar 45, the original full SL stays in place for
   the rest of the trade (no BE protection at all for that case) --
   this isolates the specific question "should I just take BE-arm-time
   profit instead of holding."

Usage:
    python3 scripts/nq_mae_gate_grid.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch
import scripts.build_be60_enriched as B

BE_BARS = 45
CANONICAL_RAW_PRE_SAL = 1841


def build_trades(bars, vxn):
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
            co = B.session_cutoff(ft)
            if co is None:
                continue
            path = bars.loc[ft: co].iloc[1:]
            if path.empty:
                continue
            cap = min(1.5 * anchor, B.SL_CAP)
            sg = -1.0 if side == "upper" else 1.0
            trades.append({
                "sd": B.session_date(ft), "yr": pd.Timestamp(B.session_date(ft)).year, "ta": ft,
                "e": lvl, "sg": sg, "cap": cap,
                "hi": path["high"].values.astype(float), "lo": path["low"].values.astype(float),
                "op": path["open"].values.astype(float), "cl": path["close"].values.astype(float),
            })
    return trades


def sim_gate(t, gate_bar, gate_frac, tp_frac, be_bars=BE_BARS):
    e, sg, c = t["e"], t["sg"], t["cap"]
    target = e + sg * tp_frac * c
    orig_stop = e - sg * c
    hi, lo, op, cl = t["hi"], t["lo"], t["op"], t["cl"]
    stop = orig_stop
    label = "SL"
    adverse = 0.0
    gate_done = be_chk = armed = False
    for i in range(len(hi)):
        h, l = hi[i], lo[i]
        adverse = max(adverse, (e - l) if sg > 0 else (h - e))

        if gate_bar is not None and i == gate_bar and not gate_done:
            gate_done = True
            if adverse <= gate_frac * c:
                cand = e - sg * gate_frac * c
                if (sg > 0 and cand > stop) or (sg < 0 and cand < stop):
                    stop, label = cand, "GATE"

        if i >= be_bars:
            if not be_chk:
                be_chk = True
                armed = (op[i] >= e) if sg > 0 else (op[i] <= e)
            if armed:
                cand = e
                if (sg > 0 and cand > stop) or (sg < 0 and cand < stop):
                    stop, label = cand, "BE"

        if sg > 0:
            if l <= stop:
                return sg * (stop - e), label
            if h >= target:
                return tp_frac * c, "TP"
        else:
            if h >= stop:
                return sg * (stop - e), label
            if l <= target:
                return tp_frac * c, "TP"
    return sg * (float(cl[-1]) - e), "cutoff"


def sim_be_take_now(t, be_bars=BE_BARS):
    e, sg, c = t["e"], t["sg"], t["cap"]
    target = e + sg * c
    orig_stop = e - sg * c
    hi, lo, op, cl = t["hi"], t["lo"], t["op"], t["cl"]
    for i in range(len(hi)):
        h, l = hi[i], lo[i]
        if i == be_bars:
            o = float(op[i])
            armed = (o >= e) if sg > 0 else (o <= e)
            if armed:
                return sg * (o - e), "BE_NOW"
        if sg > 0:
            if l <= orig_stop:
                return sg * (orig_stop - e), "SL"
            if h >= target:
                return c, "TP"
        else:
            if h >= orig_stop:
                return sg * (orig_stop - e), "SL"
            if l <= target:
                return c, "TP"
    return sg * (float(cl[-1]) - e), "cutoff"


def apply_sal(trades, results):
    rows = [{"sd": t["sd"], "ta": t["ta"], "p": r[0], "ex": r[1]} for t, r in zip(trades, results)]
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
    trades = build_trades(bars, vxn)
    print(f"raw touches (pre-SAL): {len(trades)}  ({'matches' if len(trades)==CANONICAL_RAW_PRE_SAL else '*** MISMATCH ***'} canonical {CANONICAL_RAW_PRE_SAL})\n")

    # baseline (gate_bar=None == no gate, tp_frac=1.0 == current locked config)
    base = apply_sal(trades, [sim_gate(t, None, 0.25, 1.0) for t in trades])
    base_net, base_pf, base_dd = base["p"].sum(), pf(base["p"]), maxdd(base["p"])
    print(f"BASELINE (cond@45, TP=SL=cap): n={len(base)} net={base_net:.0f} PF={base_pf:.3f} maxDD={base_dd:.0f}\n")

    print("=== 1+2. MAE-GATE (tighten to 0.25*cap if no real heat by gate_bar) x TP fraction ===")
    print(f"{'gate_bar':>8} {'tp_frac':>7} {'n':>5} {'net':>9} {'PF':>7} {'maxDD':>8} {'dNet':>8} "
          f"{'TP':>5} {'SL':>5} {'GATE':>5} {'BE':>5} {'cut':>5}")
    for gate_bar in (15, 20, 30, 45, 60):
        for tp_frac in (1.0, 0.75, 0.5):
            res = [sim_gate(t, gate_bar, 0.25, tp_frac) for t in trades]
            k = apply_sal(trades, res)
            p = k["p"]
            ex = k["ex"].value_counts()
            print(f"{gate_bar:>8} {tp_frac:>7.2f} {len(k):>5} {p.sum():>9.0f} {pf(p):>7.3f} {maxdd(p):>8.0f} "
                  f"{p.sum()-base_net:>+8.0f} {ex.get('TP',0):>5} {ex.get('SL',0):>5} "
                  f"{ex.get('GATE',0):>5} {ex.get('BE',0):>5} {ex.get('cutoff',0):>5}")

    print("\n=== 3. BE-TAKE-NOW (close at bar-45 open if on profit side, instead of arming+holding) ===")
    res = [sim_be_take_now(t) for t in trades]
    k = apply_sal(trades, res)
    p = k["p"]
    ex = k["ex"].value_counts()
    print(f"n={len(k)} net={p.sum():.0f} PF={pf(p):.3f} maxDD={maxdd(p):.0f}  delta vs baseline={p.sum()-base_net:+.0f}")
    print(f"  exits: TP={ex.get('TP',0)} SL={ex.get('SL',0)} BE_NOW={ex.get('BE_NOW',0)} cutoff={ex.get('cutoff',0)}")
    be_now = k[k["ex"] == "BE_NOW"]["p"]
    if len(be_now):
        print(f"  BE_NOW trades: n={len(be_now)} avg pnl={be_now.mean():.1f} sum={be_now.sum():.0f}")


if __name__ == "__main__":
    main()
