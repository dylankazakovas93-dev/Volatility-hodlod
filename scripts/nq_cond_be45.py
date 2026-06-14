#!/usr/bin/env python3
"""LOCKED CONFIG: NQ level-fade, Conditional-BE@45 ("tp_sl_cap200" + cond-BE45).

Rules (all fixed, no curve-fitting knobs left open):
  - Levels: generate_levels() per session, anchored at 09:30 ET cash open
    (see volgen/levels.py for the sigma/IB/offset formula).
  - lineDays = 20: a level stays live until 20 newer levels exist.
  - Entry: fade a level on first touch. upper_level touch -> SHORT,
    lower_level touch -> LONG. Only touches in 19:00-11:00 ET count;
    11:00-15:00 ET is skipped entirely.
  - Risk: cap = min(1.5 x previous completed 1h range, 200).  TP = SL = cap
    (strict 1:1 RR).
  - Conditional BE @45: at minute 45 after entry, look at the close of
    minute 44. If it's on the profit side of entry, arm BE (move stop to
    entry -> worst case is now a 0pt scratch). If it's not, leave the
    original SL in place for the rest of the trade. (This is why it's
    "conditional" -- BE never turns a trade that's still in profit into a
    loss, and never fires while underwater.)
  - SAL (stop-after-loss): per session (19:00 ET -> next-day 15:00 ET), the
    first REAL loss (pnl < 0, exit != BE) stops all further entries for that
    session. A BE scratch (~0pts) does not stop the session.

Usage:
    python3 scripts/nq_cond_be45.py \
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
import scripts.build_be60_enriched as B  # session/entry/cutoff helpers, LINE_DAYS, SL_CAP

BE_BARS = 45


def simulate_cond_be(path, entry, sign, cap, be_bars=BE_BARS):
    """1:1 TP/SL with conditional BE arming at `be_bars`.

    Returns (pnl, exit_type) where exit_type in {TP, SL, BE, cutoff}.
    """
    target = entry + sign * cap
    orig_stop = entry - sign * cap
    hi, lo, op, cl = (path["high"].values, path["low"].values,
                      path["open"].values, path["close"].values)
    armed = checked = False
    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        if i < be_bars:
            stop = orig_stop
        else:
            if not checked:
                checked = True
                o = float(op[i])
                armed = (o >= entry) if sign > 0 else (o <= entry)
            stop = entry if armed else orig_stop
        if sign > 0:
            if l <= stop:
                return sign * (stop - entry), ("BE" if (i >= be_bars and armed) else "SL")
            if h >= target:
                return cap, "TP"
        else:
            if h >= stop:
                return sign * (stop - entry), ("BE" if (i >= be_bars and armed) else "SL")
            if l <= target:
                return cap, "TP"
    return sign * (float(cl[-1]) - entry), "cutoff"


def build_ledger(bars, vxn):
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = B.bar_ranges(bars)
    lvls = list(levels.itertuples(index=False))
    records = []
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
            sign = -1.0 if side == "upper" else 1.0
            pnl, ex = simulate_cond_be(path, lvl, sign, cap)
            records.append({
                "sess_date": B.session_date(ft),
                "year": pd.Timestamp(B.session_date(ft)).year,
                "side": side, "touched_at": ft, "level": lvl,
                "anchor": anchor, "cap": cap, "pnl": pnl, "exit": ex,
            })
    return pd.DataFrame(records)


def apply_sal(df):
    """SAL: first real loss (pnl<0 and exit!=BE) stops the rest of the session."""
    kept = []
    for _, day in df.sort_values("touched_at").groupby("sess_date"):
        lost = False
        for _, row in day.iterrows():
            if not lost:
                kept.append(row.to_dict())
                if row["pnl"] < -0.1 and row["exit"] != "BE":
                    lost = True
    return pd.DataFrame(kept).sort_values("touched_at").reset_index(drop=True)


def profit_factor(s):
    g, l = float(s[s > 0].sum()), float(-s[s < 0].sum())
    return g / l if l > 0 else float("inf")


def max_drawdown(s):
    eq = s.cumsum()
    return float((eq - eq.cummax()).min())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)

    raw = build_ledger(bars, vxn)
    kept = apply_sal(raw)
    years = sorted(kept["year"].unique())

    print(f"raw touches (pre-SAL): {len(raw)}   kept (post-SAL): {len(kept)}\n")
    print(f"{'Year':6} {'n':>5} {'net':>10} {'PF':>7} {'maxDD':>8} {'TP':>5} {'SL':>5} {'BE':>5} {'cut':>5}")
    for yr in years:
        sub = kept[kept["year"] == yr]
        p = sub["pnl"]
        ex = sub["exit"].value_counts()
        print(f"{yr:<6} {len(sub):>5} {p.sum():>10.1f} {profit_factor(p):>7.3f} {max_drawdown(p):>8.1f} "
              f"{ex.get('TP', 0):>5} {ex.get('SL', 0):>5} {ex.get('BE', 0):>5} {ex.get('cutoff', 0):>5}")

    p = kept["pnl"]
    ex = kept["exit"].value_counts()
    print("-" * 60)
    print(f"{'ALL':<6} {len(kept):>5} {p.sum():>10.1f} {profit_factor(p):>7.3f} {max_drawdown(p):>8.1f} "
          f"{ex.get('TP', 0):>5} {ex.get('SL', 0):>5} {ex.get('BE', 0):>5} {ex.get('cutoff', 0):>5}")

    tp, sl = ex.get("TP", 0), ex.get("SL", 0)
    wins = (p > 0.1).sum()
    print(f"\ntWR (TP/(TP+SL)) = {tp/(tp+sl)*100:.1f}%   outright win rate = {wins/len(kept)*100:.1f}%")


if __name__ == "__main__":
    main()
