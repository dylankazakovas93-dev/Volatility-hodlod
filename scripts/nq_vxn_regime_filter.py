#!/usr/bin/env python3
"""Reproduce and sweep Codex's prior-VXN regime filter on the level strategy.

Takes the raw always_reversal + event_continuation trade log from
nq_event_mode_study.py, attaches the prior-day VXN close to every trade, then
applies the candidate policy (CPI continuation + stop_after_first_loss) with a
VXN minimum filter swept over a configurable range.

Goal: verify Codex's reported VXN >= 24 numbers independently and check that
the result is smooth across nearby thresholds (22-26). A jagged,
non-monotonic response to tiny threshold changes would be a curve-fit warning.
"""

from __future__ import annotations

import argparse

import pandas as pd


def load_vxn(path: str) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.sort_values("date").drop_duplicates("date")
    return df.set_index("date")["close"].rename("vxn_close")


def profit_factor(pts: pd.Series) -> float:
    gp = float(pts[pts > 0].sum())
    gl = float(-pts[pts < 0].sum())
    if gl == 0:
        return float("inf") if gp > 0 else 0.0
    return gp / gl


def max_drawdown(pts: pd.Series) -> float:
    if pts.empty:
        return 0.0
    equity = pts.cumsum()
    return float((equity - equity.cummax()).min())


def attach_prior_vxn(df: pd.DataFrame, vxn: pd.Series) -> pd.DataFrame:
    """Add prior-day VXN close to every trade row."""
    date_et = pd.to_datetime(df["date_et"])
    prior_dates = date_et - pd.Timedelta(days=1)

    def prior_vxn(d: pd.Timestamp) -> float | None:
        target = pd.Timestamp(d.normalize().date())
        idx = vxn.index.searchsorted(target)
        if idx == 0:
            return None
        return float(vxn.iloc[idx - 1])

    df = df.copy()
    df["prior_vxn"] = [prior_vxn(d) for d in date_et]
    return df


def choose_policy_cpi(df: pd.DataFrame) -> pd.DataFrame:
    """CPI continuation, all others reversal. Same join logic as policy report."""
    always = df[df["mode"].eq("always_reversal")].copy()
    cont = df[df["mode"].eq("event_continuation")].copy()

    def _key(r):
        return f"{r['session_date']}|{r['side']}|{r['touched_at']}|{round(r['entry'], 6)}"

    cont["_key"] = cont.apply(_key, axis=1)
    cont_by_key = cont.set_index("_key")

    rows = []
    for _, row in always.iterrows():
        k = _key(row)
        event_types = {p for p in str(row.get("event_types", "")).split("|") if p}
        if "cpi" in event_types and k in cont_by_key.index:
            picked = cont_by_key.loc[k].copy()
        else:
            picked = row.copy()
        rows.append(picked)
    return pd.DataFrame(rows).drop(columns=["_key"], errors="ignore")


def apply_stop_after_loss(df: pd.DataFrame) -> pd.DataFrame:
    keep = []
    for _, day in df.sort_values("touched_at").groupby("date_et"):
        for idx, row in day.iterrows():
            keep.append(idx)
            if row["pts"] < 0:
                break
    return df.loc[keep].sort_values("touched_at")


def summarize_by_year(df: pd.DataFrame) -> None:
    for year in sorted(df["year"].unique()):
        sub = df[df["year"] == year]["pts"]
        print(
            f"  {year}: n={len(sub):3d}  net={sub.sum():9.2f}  PF={profit_factor(sub):.3f}  maxDD={max_drawdown(sub):.2f}"
        )
    all_pts = df["pts"]
    print(
        f"  ALL : n={len(all_pts):3d}  net={all_pts.sum():9.2f}  PF={profit_factor(all_pts):.3f}  maxDD={max_drawdown(all_pts):.2f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trades", required=True, help="Trade CSV from nq_event_mode_study --out-prefix")
    parser.add_argument("--vxn", default="data/vxn_daily_2020_2026.csv")
    parser.add_argument("--min-vxn", default="18,20,22,23,24,25,26,28", help="Comma-separated VXN thresholds to sweep")
    args = parser.parse_args()

    df = pd.read_csv(args.trades)
    df["touched_at"] = pd.to_datetime(df["touched_at"], utc=True)
    df["date_et"] = df["touched_at"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    df["year"] = df["touched_at"].dt.tz_convert("America/New_York").dt.year

    vxn = load_vxn(args.vxn)
    df = attach_prior_vxn(df, vxn)

    thresholds = [float(x) for x in args.min_vxn.split(",")]

    # Baseline: no VXN filter, CPI continuation + stop_after_loss
    policy_all = choose_policy_cpi(df)
    policy_all_sal = apply_stop_after_loss(policy_all)
    print("=== BASELINE (no VXN filter) — CPI continuation + stop_after_loss ===")
    summarize_by_year(policy_all_sal)

    # VXN sweep
    print(f"\n=== VXN FILTER SWEEP (CPI continuation + stop_after_loss) ===")
    for threshold in thresholds:
        filtered = df[df["prior_vxn"].notna() & df["prior_vxn"].ge(threshold)]
        if filtered.empty:
            print(f"\nVXN >= {threshold:.0f}: no trades")
            continue
        policy = choose_policy_cpi(filtered)
        policy_sal = apply_stop_after_loss(policy)
        print(f"\nVXN >= {threshold:.0f}:")
        summarize_by_year(policy_sal)


if __name__ == "__main__":
    main()
