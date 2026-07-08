#!/usr/bin/env python3
"""Streamlit Prop Lab for the OG two-month forward ledgers."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st


APP_PATH = Path(__file__).resolve()
REPO_ROOT = APP_PATH.parents[1] if APP_PATH.parent.name == "apps" else APP_PATH.parent
FINAL_DIR = REPO_ROOT / "artifacts/forward_ledger/final"
FORECAST_START = pd.Timestamp("2026-07-08")
FORECAST_END = pd.Timestamp("2026-08-31")
POINT_VALUE_MNQ = 2.0


@st.cache_data
def load_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(FINAL_DIR / name)


@st.cache_data
def load_json(name: str):
    with open(FINAL_DIR / name) as f:
        return json.load(f)


def point_metrics(pnl: pd.Series) -> dict:
    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float(-pnl[pnl < 0].sum())
    net = float(pnl.sum())
    pf = gross_profit / gross_loss if gross_loss else np.nan
    return {"gross_profit": gross_profit, "gross_loss": gross_loss, "net": net, "pf": pf}


def rolling_pf(window: list[float]) -> float:
    vals = np.asarray(window[-100:], dtype=float)
    if len(vals) < 100:
        return np.inf
    gains = vals[vals > 0].sum()
    losses = -vals[vals < 0].sum()
    return float(gains / losses) if losses else np.inf


def integrity_checks(ledger: pd.DataFrame, anchor: pd.DataFrame, rr: str) -> pd.DataFrame:
    target_cap = 200.0 if rr == "1rr" else 300.0
    checks = [
        ("single_rr_config", set(ledger["rr_config_id"]) == {rr}, str(sorted(ledger["rr_config_id"].unique()))),
        ("mae_mfe_complete", ledger["mae_points"].notna().all() and ledger["mfe_points"].notna().all(), "MAE/MFE non-null"),
        ("raw_stop_cap_200", ledger["raw_stop_points"].max() <= 200.0, f"max={ledger['raw_stop_points'].max():.2f}"),
        ("effective_stop_cap_200", ledger["effective_stop_points"].max() <= 200.0, f"max={ledger['effective_stop_points'].max():.2f}"),
        ("target_cap", ledger["target_points"].max() <= target_cap, f"max={ledger['target_points'].max():.2f}"),
        ("pnl_r_math", (ledger["pnl_R"] * ledger["raw_stop_points"] - ledger["pnl_points"]).abs().max() < 1e-9, "ok"),
        ("mae_r_math", (ledger["mae_R"] * ledger["raw_stop_points"] - ledger["mae_points"]).abs().max() < 1e-9, "ok"),
        ("mfe_r_math", (ledger["mfe_R"] * ledger["raw_stop_points"] - ledger["mfe_points"]).abs().max() < 1e-9, "ok"),
        ("one_anchor_for_selected_rr", len(anchor[anchor["rr_config_id"] == rr]) == 1, f"rows={len(anchor[anchor['rr_config_id'] == rr])}"),
        ("anchor_alternatives_mutually_exclusive", anchor["mutually_exclusive_config_alternative"].astype(bool).all(), "ok"),
    ]
    return pd.DataFrame([{"check": name, "ok": bool(ok), "detail": detail} for name, ok, detail in checks])


def scenario_for(manifest: dict, rr: str, pf_id: str, regime: str) -> dict:
    matches = [
        s for s in manifest["scenarios"]
        if s["rr_config_id"] == rr and s["pf_assumption_id"] == pf_id and s["regime_path"] == regime
    ]
    if not matches:
        raise ValueError(f"missing scenario {rr}/{pf_id}/{regime}")
    return matches[0]


def scale_multiplier(scale_id: str) -> float:
    return {
        "scale_central": 1.0,
        "scale_minus_10": 0.90,
        "scale_plus_10": 1.10,
        "scale_minus_15": 0.85,
        "scale_plus_15": 1.15,
        "scale_minus_20": 0.80,
        "scale_plus_20": 1.20,
    }[scale_id]


def choose_block_weights(scenario: dict) -> pd.DataFrame:
    weights = pd.DataFrame(scenario["block_weights"])
    weights = weights[weights["scenario_weight"] > 0].copy()
    weights["scenario_weight"] = weights["scenario_weight"] / weights["scenario_weight"].sum()
    return weights


def month_candidates(ledger: pd.DataFrame, block_id: str, target_month: int) -> pd.DataFrame:
    _, ym = block_id.split("|")
    year, month = [int(x) for x in ym.split("-")]
    rows = ledger[(ledger["source_year"] == year) & (ledger["source_month"] == month)].copy()
    if rows.empty:
        return rows
    source_days = pd.to_datetime(rows["source_session_date"]).dt.day.clip(1, 31)
    if target_month == 7:
        days = source_days.clip(lower=8, upper=31)
        rows["forecast_date"] = pd.to_datetime({"year": 2026, "month": 7, "day": days})
    else:
        days = source_days.clip(lower=1, upper=31)
        rows["forecast_date"] = pd.to_datetime({"year": 2026, "month": 8, "day": days})
    return rows.sort_values(["forecast_date", "entry_time"]).reset_index(drop=True)


def apply_point_scale(candidates: pd.DataFrame, rr: str, mult: float) -> pd.DataFrame:
    out = candidates.copy()
    raw = np.minimum(out["raw_stop_points"].astype(float).to_numpy() * mult, 200.0)
    target_cap = 200.0 if rr == "1rr" else 300.0
    out["forward_raw_stop_points"] = raw
    out["forward_effective_stop_points"] = np.minimum(out["effective_stop_R"].astype(float) * raw, 200.0)
    out["forward_target_points"] = np.minimum(out["target_R"].astype(float) * raw, target_cap)
    out["forward_pnl_points"] = out["pnl_R"].astype(float) * raw
    out["forward_mae_points"] = out["mae_R"].astype(float) * raw
    out["forward_mfe_points"] = out["mfe_R"].astype(float) * raw
    return out


def simulate_path(ledger: pd.DataFrame, scenario: dict, rr: str, scale_id: str, rng: np.random.Generator, path_idx: int) -> tuple[pd.DataFrame, dict]:
    weights = choose_block_weights(scenario)
    probs = weights["scenario_weight"].to_numpy(float)
    block_ids = weights["calendar_block_id"].tolist()
    chosen = {
        7: block_ids[int(rng.choice(np.arange(len(block_ids)), p=probs))],
        8: block_ids[int(rng.choice(np.arange(len(block_ids)), p=probs))],
    }
    candidates = []
    for month in (7, 8):
        c = month_candidates(ledger, chosen[month], month)
        if not c.empty:
            candidates.append(c)
    if candidates:
        cand = pd.concat(candidates, ignore_index=True).sort_values(["forecast_date", "entry_time"]).reset_index(drop=True)
    else:
        cand = pd.DataFrame(columns=ledger.columns)
    cand = apply_point_scale(cand, rr, scale_multiplier(scale_id))

    warm = ledger.sort_values("entry_time")["historical_unfiltered_pnl_points"].astype(float).tail(100).tolist()
    monitor_window = list(warm)
    state_flat = False
    rows = []
    for i, row in cand.iterrows():
        pf_before = rolling_pf(monitor_window)
        prev_state = state_flat
        if len(monitor_window) >= 100:
            if state_flat and pf_before >= 1.10:
                state_flat = False
            elif not state_flat and pf_before < 1.10:
                state_flat = True
        executed = not state_flat
        pnl = float(row["forward_pnl_points"]) if executed else 0.0
        # The monitor observes candidate opportunity outcomes for causal re-entry,
        # while exposure/account metrics only use executed P&L.
        monitor_window.append(float(row["forward_pnl_points"]))
        monitor_window = monitor_window[-100:]
        rows.append({
            "path_index": path_idx,
            "candidate_index": i,
            "forecast_date": row["forecast_date"],
            "trade_packet_id": row["trade_packet_id"],
            "exit_reason": row["exit_reason"],
            "rolling_pf_before": pf_before if np.isfinite(pf_before) else np.nan,
            "gate_state_before": "FLAT" if state_flat else "ON",
            "gate_triggered": prev_state != state_flat,
            "was_executed": executed,
            "executed_pnl_points": pnl,
            "candidate_pnl_points": float(row["forward_pnl_points"]),
            "forward_raw_stop_points": float(row["forward_raw_stop_points"]),
            "forward_mae_points": float(row["forward_mae_points"]),
            "forward_mfe_points": float(row["forward_mfe_points"]),
        })
    trades = pd.DataFrame(rows)
    executed_pnl = trades.loc[trades["was_executed"], "executed_pnl_points"] if len(trades) else pd.Series(dtype=float)
    m = point_metrics(executed_pnl)
    summary = {
        "path_index": path_idx,
        "common_strategy_path_id": f"{scenario['scenario_id']}|{scale_id}|{path_idx:05d}",
        "candidate_trades": int(len(trades)),
        "executed_trades": int(trades["was_executed"].sum()) if len(trades) else 0,
        "forecast_net_points": m["net"],
        "gross_profit_points": m["gross_profit"],
        "gross_loss_points": m["gross_loss"],
        "path_points_pf": m["pf"],
        "gate_off_pct": float((~trades["was_executed"]).mean()) if len(trades) else 0.0,
        "end_gate_state": str(trades["gate_state_before"].iloc[-1]) if len(trades) else "ON",
        "july_net_points": float(trades.loc[trades["forecast_date"].dt.month == 7, "executed_pnl_points"].sum()) if len(trades) else 0.0,
        "august_net_points": float(trades.loc[trades["forecast_date"].dt.month == 8, "executed_pnl_points"].sum()) if len(trades) else 0.0,
    }
    return trades, summary


@st.cache_data(show_spinner=False)
def run_monte_carlo(rr: str, pf_id: str, regime: str, scale_id: str, paths: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    ledger_file = "forward_1rr.csv" if rr == "1rr" else "forward_1_5rr.csv"
    ledger = load_csv(ledger_file)
    manifest = load_json("forward_scenario_manifest.json")
    scenario = scenario_for(manifest, rr, pf_id, regime)
    rng = np.random.default_rng(seed)
    summaries = []
    first_path = None
    for i in range(paths):
        trades, summary = simulate_path(ledger, scenario, rr, scale_id, rng, i)
        summaries.append(summary)
        if i == 0:
            first_path = trades
    return pd.DataFrame(summaries), first_path if first_path is not None else pd.DataFrame()


def account_results(paths: pd.DataFrame, anchor_points: float, contracts: int, start_balance: float, trailing_dd: float, profit_target: float, daily_loss_limit: float, commission: float) -> pd.DataFrame:
    out = paths.copy()
    multiplier = contracts * POINT_VALUE_MNQ
    out["combined_with_anchor_points"] = out["forecast_net_points"] + anchor_points
    out["anchor_dollars"] = anchor_points * multiplier
    out["forecast_dollars"] = out["forecast_net_points"] * multiplier - out["executed_trades"] * contracts * commission
    out["ending_balance"] = start_balance + out["anchor_dollars"] + out["forecast_dollars"]
    out["net_dollars"] = out["ending_balance"] - start_balance
    out["profit_target_hit"] = out["net_dollars"] >= profit_target
    # Conservative path-level proxy when only summary is retained.
    out["trailing_drawdown_breach"] = out["forecast_dollars"] <= -trailing_dd
    out["daily_loss_breach"] = False if daily_loss_limit <= 0 else out[["july_net_points", "august_net_points"]].min(axis=1) * multiplier <= -daily_loss_limit
    out["passed_basic_rules"] = ~(out["trailing_drawdown_breach"] | out["daily_loss_breach"])
    return out


def summarize(series: pd.Series) -> dict:
    s = pd.Series(series, dtype=float)
    return {
        "p10": s.quantile(0.10),
        "p25": s.quantile(0.25),
        "p50": s.quantile(0.50),
        "mean": s.mean(),
        "p75": s.quantile(0.75),
        "p90": s.quantile(0.90),
    }


def main() -> None:
    st.set_page_config(page_title="OG Prop Lab", layout="wide")
    st.title("OG NQ Prop Lab")
    st.caption("Two-month Monte Carlo lab for July 8-August 31, 2026. Historical source ledgers are inputs, not headline results.")

    required = ["forward_1rr.csv", "forward_1_5rr.csv", "realized_anchor.csv", "calendar_blocks.csv", "point_scale_scenarios.json", "forward_scenario_manifest.json"]
    missing = [name for name in required if not (FINAL_DIR / name).exists()]
    if missing:
        st.error(f"Missing final artifacts: {missing}")
        st.stop()

    anchor = load_csv("realized_anchor.csv")
    manifest = load_json("forward_scenario_manifest.json")
    point_scales = load_json("point_scale_scenarios.json")

    st.sidebar.header("Strategy")
    rr = st.sidebar.radio("RR config", ["1rr", "1_5rr"], horizontal=True)
    pf_ids = sorted({s["pf_assumption_id"] for s in manifest["scenarios"] if s["rr_config_id"] == rr})
    regimes = sorted({s["regime_path"] for s in manifest["scenarios"] if s["rr_config_id"] == rr})
    scales = [s["point_scale_scenario_id"] for s in point_scales if s["rr_config_id"] == rr]
    pf_id = st.sidebar.selectbox("PF assumption", pf_ids, index=pf_ids.index("FORWARD_PF_ASSUMPTION_1_50"))
    regime = st.sidebar.selectbox("Regime path", regimes)
    scale_id = st.sidebar.selectbox("Point scale", scales, index=scales.index("scale_central") if "scale_central" in scales else 0)

    st.sidebar.header("Monte Carlo")
    n_paths = st.sidebar.slider("Paths", min_value=250, max_value=10000, value=2000, step=250)
    seed = st.sidebar.number_input("Seed", min_value=1, value=20260708, step=1)
    run = st.sidebar.button("Run Monte Carlo", type="primary")

    st.sidebar.header("Prop Account")
    contracts = st.sidebar.slider("MNQ contracts", 1, 4, 1)
    start_balance = st.sidebar.number_input("Starting balance ($)", min_value=0.0, value=50000.0, step=1000.0)
    trailing_dd = st.sidebar.number_input("Trailing/max drawdown limit ($)", min_value=0.0, value=2500.0, step=100.0)
    profit_target = st.sidebar.number_input("Profit target ($)", min_value=0.0, value=3000.0, step=100.0)
    daily_loss = st.sidebar.number_input("Daily loss limit ($, 0 disables)", min_value=0.0, value=0.0, step=100.0)
    commission = st.sidebar.number_input("Round-turn commission per MNQ ($)", min_value=0.0, value=0.0, step=0.25)

    ledger_file = "forward_1rr.csv" if rr == "1rr" else "forward_1_5rr.csv"
    ledger = load_csv(ledger_file)
    anchor_points = float(anchor.loc[anchor["rr_config_id"] == rr, "realized_pnl_points"].iloc[0])

    with st.expander("Ledger integrity", expanded=False):
        checks = integrity_checks(ledger, anchor, rr)
        st.dataframe(checks, use_container_width=True, hide_index=True)
        st.download_button("Download selected source ledger", ledger.to_csv(index=False).encode(), ledger_file, "text/csv")

    if not run:
        st.info("Choose settings in the sidebar, then click **Run Monte Carlo**. This app reports forward MC results, not full-history net points.")
        st.stop()

    with st.spinner("Running forward paths..."):
        paths, first_path = run_monte_carlo(rr, pf_id, regime, scale_id, int(n_paths), int(seed))
        account = account_results(paths, anchor_points, contracts, start_balance, trailing_dd, profit_target, daily_loss, commission)

    st.subheader("Forward Monte Carlo Results")
    net_stats = summarize(account["forecast_net_points"])
    combined_stats = summarize(account["forecast_net_points"] + anchor_points)
    dollar_stats = summarize(account["net_dollars"])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Forecast p50 pts", f"{net_stats['p50']:,.0f}")
    c2.metric("Forecast mean pts", f"{net_stats['mean']:,.0f}")
    c3.metric("With July 7 p50 pts", f"{combined_stats['p50']:,.0f}")
    c4.metric("Median net $", f"${dollar_stats['p50']:,.0f}")
    c5.metric("Rule pass %", f"{100 * account['passed_basic_rules'].mean():.1f}%")

    st.write("Point distributions")
    st.dataframe(pd.DataFrame({
        "forecast_points": net_stats,
        "forecast_plus_anchor_points": combined_stats,
        "net_dollars": dollar_stats,
    }), use_container_width=True)

    c6, c7, c8, c9 = st.columns(4)
    c6.metric("Negative forecast paths", f"{100 * (account['forecast_net_points'] < 0).mean():.1f}%")
    c7.metric("Profit target hit", f"{100 * account['profit_target_hit'].mean():.1f}%")
    c8.metric("DD breach proxy", f"{100 * account['trailing_drawdown_breach'].mean():.1f}%")
    c9.metric("Avg executed trades", f"{account['executed_trades'].mean():.1f}")

    st.subheader("Path Distribution")
    st.line_chart(account[["forecast_net_points", "combined_with_anchor_points"]].head(500))
    st.dataframe(account, use_container_width=True, height=360)
    st.download_button("Download MC summary CSV", account.to_csv(index=False).encode(), "prop_lab_mc_summary.csv", "text/csv")

    st.subheader("First Generated Strategy Path")
    st.caption("Same strategy path can be reused across 1-4 MNQ; sizing is applied after path generation.")
    st.dataframe(first_path, use_container_width=True, height=420)
    st.download_button("Download first path CSV", first_path.to_csv(index=False).encode(), "prop_lab_first_path.csv", "text/csv")

    st.subheader("Anchor Alternatives")
    st.dataframe(anchor, use_container_width=True, hide_index=True)
    st.warning("The two July 7 rows are mutually exclusive RR alternatives. A selected RR config adds exactly one +150 anchor.")


if __name__ == "__main__":
    main()
