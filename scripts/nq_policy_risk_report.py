#!/usr/bin/env python3
"""Build policy and concentration reports from nq_event_mode_study trades."""

from __future__ import annotations

import argparse
import os

import pandas as pd


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


def trade_key(df: pd.DataFrame) -> pd.Series:
    return (
        df["session_date"].astype(str)
        + "|"
        + df["side"].astype(str)
        + "|"
        + df["touched_at"].astype(str)
        + "|"
        + df["entry"].round(6).astype(str)
    )


def choose_policy(df: pd.DataFrame, name: str, continuation_events: set[str], skip_events: set[str] | None = None) -> pd.DataFrame:
    skip_events = skip_events or set()
    always = df[df["mode"].eq("always_reversal")].copy()
    continuation = df[df["mode"].eq("event_continuation")].copy()
    always["_key"] = trade_key(always)
    continuation["_key"] = trade_key(continuation)
    cont_by_key = continuation.set_index("_key")

    rows = []
    for _, row in always.iterrows():
        event_types = {part for part in str(row["event_types"]).split("|") if part}
        if event_types & skip_events:
            continue
        if event_types & continuation_events and row["_key"] in cont_by_key.index:
            picked = cont_by_key.loc[row["_key"]].copy()
        else:
            picked = row.copy()
        picked["policy"] = name
        rows.append(picked)
    return pd.DataFrame(rows).drop(columns=["_key"], errors="ignore")


def apply_max_trades_per_day(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.sort_values("touched_at").groupby("date_et").head(n)


def apply_stop_after_loss(df: pd.DataFrame) -> pd.DataFrame:
    keep = []
    for _, day in df.sort_values("touched_at").groupby("date_et"):
        for idx, row in day.iterrows():
            keep.append(idx)
            if row["pts"] < 0:
                break
    return df.loc[keep].sort_values("touched_at")


def apply_cooldown(df: pd.DataFrame, hours: float) -> pd.DataFrame:
    rows = []
    next_ok = pd.Timestamp.min.tz_localize("UTC")
    for _, row in df.sort_values("touched_at").iterrows():
        ts = row["touched_at"]
        if ts < next_ok:
            continue
        rows.append(row)
        if row["pts"] < 0 and str(row["result"]) == "stop":
            next_ok = ts + pd.Timedelta(minutes=float(row["bars_held"])) + pd.Timedelta(hours=hours)
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, policy: str, variant: str) -> dict[str, object]:
    ordered = df.sort_values("touched_at")
    monthly = ordered.groupby("month")["pts"].sum()
    weekly = ordered.groupby(ordered["touched_at"].dt.tz_convert("America/New_York").dt.strftime("%Y-%U"))["pts"].sum()
    best_week = float(weekly.max()) if not weekly.empty else 0.0
    net = float(ordered["pts"].sum())
    return {
        "policy": policy,
        "variant": variant,
        "trades": len(ordered),
        "net_points": net,
        "win_rate": float(ordered["pts"].gt(0).mean()) if not ordered.empty else float("nan"),
        "profit_factor": profit_factor(ordered["pts"]) if not ordered.empty else float("nan"),
        "max_drawdown": max_drawdown(ordered["pts"]),
        "worst_month": float(monthly.min()) if not monthly.empty else 0.0,
        "negative_months": int((monthly < 0).sum()),
        "best_week_points": best_week,
        "best_week_net_pct": best_week / net if net else float("nan"),
    }


def event_type_report(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    always = df[df["mode"].eq("always_reversal")]
    cont = df[df["mode"].eq("event_continuation")]
    for event_type in sorted({p for raw in df["event_types"].dropna().astype(str) for p in raw.split("|") if p}):
        for label, subset in (("reversal", always), ("continuation", cont)):
            parts = subset["event_types"].fillna("").astype(str).str.split("|")
            g = subset[parts.apply(lambda values: event_type in values)]
            rows.append(
                {
                    "event_type": event_type,
                    "logic": label,
                    "trades": len(g),
                    "net_points": float(g["pts"].sum()),
                    "win_rate": float(g["pts"].gt(0).mean()) if not g.empty else float("nan"),
                    "profit_factor": profit_factor(g["pts"]) if not g.empty else float("nan"),
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trades", required=True)
    parser.add_argument("--out-prefix", required=True)
    args = parser.parse_args()

    df = pd.read_csv(args.trades)
    df["touched_at"] = pd.to_datetime(df["touched_at"], utc=True)
    df["date_et"] = df["touched_at"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    df["month"] = df["touched_at"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m")

    policies = [
        choose_policy(df, "always_reversal", set()),
        choose_policy(df, "continue_cpi", {"cpi"}),
        choose_policy(df, "continue_tariff", {"tariff_headline"}),
        choose_policy(df, "continue_cpi_tariff", {"cpi", "tariff_headline"}),
        choose_policy(df, "continue_cpi_tariff_home", {"cpi", "tariff_headline", "home_sales"}),
        choose_policy(df, "skip_tariff", set(), {"tariff_headline"}),
        choose_policy(df, "skip_all_events", set(), {"cpi", "fomc", "home_sales", "mag7_earnings", "nfp", "tariff_headline"}),
    ]

    summary_rows = []
    trade_outputs = []
    for policy_df in policies:
        if policy_df.empty:
            continue
        policy = str(policy_df["policy"].iloc[0])
        variants = {
            "base": policy_df,
            "max_1_per_day": apply_max_trades_per_day(policy_df, 1),
            "max_2_per_day": apply_max_trades_per_day(policy_df, 2),
            "stop_after_loss": apply_stop_after_loss(policy_df),
            "cooldown_2h_after_stop": apply_cooldown(policy_df, 2),
            "cooldown_3h_after_stop": apply_cooldown(policy_df, 3),
        }
        for variant, variant_df in variants.items():
            summary_rows.append(summarize(variant_df, policy, variant))
            out = variant_df.copy()
            out["variant"] = variant
            trade_outputs.append(out)

    summary = pd.DataFrame(summary_rows).sort_values(["net_points", "profit_factor"], ascending=False)
    events = event_type_report(df)
    trades_out = pd.concat(trade_outputs, ignore_index=True) if trade_outputs else pd.DataFrame()

    os.makedirs(os.path.dirname(args.out_prefix) or ".", exist_ok=True)
    summary.to_csv(f"{args.out_prefix}_summary.csv", index=False)
    events.to_csv(f"{args.out_prefix}_event_types.csv", index=False)
    trades_out.to_csv(f"{args.out_prefix}_trades.csv", index=False)

    print("=== POLICY SUMMARY ===")
    print(summary.round(3).to_string(index=False))
    print("\n=== EVENT TYPES ===")
    print(events.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
