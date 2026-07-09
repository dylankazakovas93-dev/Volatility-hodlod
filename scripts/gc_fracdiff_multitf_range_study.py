"""GC study: multi-timeframe prior-completed-candle-range TP/SL sweep,
optionally gated by a causal Python port of the user's Pine v6 "FracDiff
Gate (5m, TREND-sense)" indicator. No changes to any frozen engine file --
only calls generate_levels/physical_touches/session_cutoff unmodified.

CAUSALITY, stated explicitly per timeframe range and the FracDiff gate:

- Range features (5min/30min/1h/4h): for touch at `ts`, the range used is
  the PRIOR COMPLETED bar at that timeframe -- `ts.floor(freq) - freq`,
  i.e. never the bar currently forming at `ts` even if `ts` sits exactly
  on a boundary. Identical convention to the frozen engine's own
  `prev_completed_range()` (60min), just generalized to other frequencies.
- FracDiff gate: computed entirely on 5-minute bars resampled from the
  canonical 1-minute GC series (`label='left', closed='left'`, standard
  non-overlapping OHLC downsampling -- each 5m bar only aggregates its own
  five 1m bars, no future leakage). The fractional-difference value at 5m
  bar i is `fd[i] = sum_{k=0}^{effN} w[k] * close[i-k]` -- built via N
  vectorized `.shift(k)` calls (k>=0 only, i.e. current + STRICTLY PAST
  bars, never negative/future shifts) so its causality is auditable by
  construction, not just asserted. z-score uses a trailing (never
  centered) rolling mean/stdev over the past `zlen` fd values, population
  stdev (ddof=0, matching Pine's `ta.stdev` default) to match the script
  exactly. At entry time `ts`, the gate value actually used is the value
  stamped on the PRIOR COMPLETED 5m bar (`ts.floor('5min') - 5min`), same
  "always strictly prior" rule as the range features -- the forming 5m bar
  containing `ts` itself is never used.
- NO OVERLAP: each touch is evaluated independently against its own single
  prior-completed-bar snapshot per feature; nothing here manages
  concurrent positions (that's a separate question from level/gate
  quality, same reasoning as the earlier MAE/MFE excursion study).
"""
from __future__ import annotations

import sys
import os
from dataclasses import replace

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_loader import load_1m_ohlcv, load_gvz_daily
from src.level_generation import GC_PARAMS, generate_levels
from src.strict_engine import bar_ranges, physical_touches, session_cutoff

BARS_PATH = "data/gc_1m/gc_continuous_2023_2026_1m.csv"
VOL_PATH = "data/vxn_daily_2018_2026.csv"
SIGMA_MULT, OFFSET_PCT, IB_MINUTES = 2.0, 0.08, 30  # winning grid params, unchanged throughout this session

TIMEFRAMES = {"5min": "5min", "30min": "30min", "1h": "1h", "4h": "4h"}
RR_GRID = [0.30, 0.50, 0.75, 1.00]

# --- FracDiff Gate params, verbatim from the Pine script -------------------
FD_D, FD_N, FD_ZLEN, FD_BAND, FD_FAST_THRESH = 0.45, 100, 100, 1.0, 1e-3


def ffd_weights(d, N, thresh):
    w = [1.0]
    wk = 1.0
    for k in range(1, N + 1):
        wk = wk * (k - 1 - d) / k
        if abs(wk) < thresh:
            break
        w.append(wk)
    return w  # w[0]..w[effN]


def resample_ohlc(bars, freq):
    return bars.resample(freq, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()


def compute_fracdiff_gate(bars_1m):
    """Returns a Series indexed by 5m-bar start time -> z-score, computed
    entirely causally (see module docstring)."""
    bars_5m = resample_ohlc(bars_1m, "5min")
    close = bars_5m["close"]

    w = ffd_weights(FD_D, FD_N, FD_FAST_THRESH)
    fd = pd.Series(0.0, index=close.index)
    for k, wk in enumerate(w):
        fd = fd.add(wk * close.shift(k), fill_value=0.0)
    fd.iloc[: len(w) - 1] = np.nan  # not enough history for a full window yet -- no partial-weight leakage

    fd_mean = fd.rolling(FD_ZLEN).mean()
    fd_std = fd.rolling(FD_ZLEN).std(ddof=0)  # population stdev, matches Pine ta.stdev default
    z = (fd - fd_mean) / fd_std
    return z


def prior_bar_start(ts, freq):
    return ts.floor(freq) - pd.Timedelta(freq)


def prior_range_lookup(bars_1m, freq):
    r = resample_ohlc(bars_1m, freq)
    return (r["high"] - r["low"])


def race(entry, sign, cap, k, path_high, path_low):
    target = entry + sign * cap * k
    stop = entry - sign * cap
    for h, l in zip(path_high, path_low):
        if sign > 0:
            hit_stop, hit_target = l <= stop, h >= target
        else:
            hit_stop, hit_target = h >= stop, l <= target
        if hit_stop:
            return "SL", -cap
        if hit_target:
            return "TP", cap * k
    return "undecided", 0.0


def main():
    bars = load_1m_ohlcv(BARS_PATH)
    vol = load_gvz_daily(VOL_PATH)
    params = replace(GC_PARAMS, sigma_mult=SIGMA_MULT, offset_pct=OFFSET_PCT, ib_minutes=IB_MINUTES, fixed_offset=None)
    levels = generate_levels(bars, vol, params=params, rth_start="09:30", rth_end="16:00")
    lvls = list(levels.itertuples(index=False))
    events = physical_touches(bars, lvls)
    touched = [e for e in events if e["touched_at"] is not None]
    print(f"physical touches: {len(touched)}")

    range_lookups = {tf: prior_range_lookup(bars, freq) for tf, freq in TIMEFRAMES.items()}
    z_gate = compute_fracdiff_gate(bars)
    print(f"5m bars: {len(z_gate)}, z non-NaN from bar {z_gate.first_valid_index()}")

    rows = []
    for e in touched:
        ts = e["touched_at"]
        cutoff = session_cutoff(ts)
        if cutoff is None:
            continue
        path = bars.loc[ts:cutoff]
        if path.empty:
            continue
        ph, pl = path["high"].to_numpy(), path["low"].to_numpy()
        entry = e["level"]
        sign = 1.0 if e["side"] == "lower" else -1.0

        gate_bar = prior_bar_start(ts, "5min")
        z = z_gate.get(gate_bar, np.nan)
        gate_pass = (sign > 0 and z >= FD_BAND) or (sign < 0 and z <= -FD_BAND) if pd.notna(z) else False

        row = {"touched_at": ts, "year": ts.year, "side": e["side"], "z_gate": z, "gate_pass": gate_pass}
        for tf, freq in TIMEFRAMES.items():
            prev_bar = prior_bar_start(ts, freq)
            cap = range_lookups[tf].get(prev_bar, np.nan)
            row[f"cap_{tf}"] = cap
        row["entry"], row["sign"] = entry, sign
        row["path_high"], row["path_low"] = ph, pl
        rows.append(row)

    df = pd.DataFrame(rows)
    print(f"touches with cutoff/path available: {len(df)}, gate_pass: {df['gate_pass'].sum()} "
          f"({df['gate_pass'].mean()*100:.1f}%), gate NaN (insufficient 5m history): {df['z_gate'].isna().sum()}")

    results = []
    for tf in TIMEFRAMES:
        for k in RR_GRID:
            for gated in (False, True):
                sub = df[df["gate_pass"]] if gated else df
                sub = sub[sub[f"cap_{tf}"].notna() & (sub[f"cap_{tf}"] > 0)]
                outcomes = [race(r.entry, r.sign, getattr(r, f"cap_{tf}"), k, r.path_high, r.path_low)
                            for r in sub.itertuples()]
                pnl = pd.Series([o[1] for o in outcomes])
                reason = pd.Series([o[0] for o in outcomes])
                decided = pnl[reason != "undecided"]
                reason_d = reason[reason != "undecided"]
                if len(decided) == 0:
                    continue
                gp = decided[decided > 0].sum()
                gl = -decided[decided < 0].sum()
                pf = gp / gl if gl > 0 else float("inf")
                results.append({
                    "timeframe": tf, "RR": k, "gated": gated,
                    "n_touches": len(sub), "n_decided": len(decided),
                    "net_pts": round(decided.sum(), 2),
                    "avg_pts_per_trade": round(decided.mean(), 3),
                    "PF": round(pf, 4), "win_rate": round((reason_d == "TP").mean(), 4),
                    "TP": int((reason_d == "TP").sum()), "SL": int((reason_d == "SL").sum()),
                })

    res = pd.DataFrame(results)
    os.makedirs("outputs/gc_fracdiff_study", exist_ok=True)
    res.to_csv("outputs/gc_fracdiff_study/tf_rr_gate_sweep.csv", index=False)
    df.drop(columns=["path_high", "path_low"]).to_csv("outputs/gc_fracdiff_study/touches_with_gate.csv", index=False)

    pd.set_option("display.width", 220)
    print("\n=== ungated ===")
    print(res[~res.gated].sort_values(["timeframe", "RR"]).to_string(index=False))
    print("\n=== gated (FracDiff z>=+1 for long-fade / z<=-1 for short-fade) ===")
    print(res[res.gated].sort_values(["timeframe", "RR"]).to_string(index=False))


if __name__ == "__main__":
    main()
