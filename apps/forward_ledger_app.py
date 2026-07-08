#!/usr/bin/env python3
"""Streamlit explorer for the final forward-ledger bundle."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st


APP_PATH = Path(__file__).resolve()
REPO_ROOT = APP_PATH.parents[1] if APP_PATH.parent.name == "apps" else APP_PATH.parent
FINAL_DIR = REPO_ROOT / "artifacts/forward_ledger/final"


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
    pf = gross_profit / gross_loss if gross_loss else None
    return {
        "gross_profit_points": gross_profit,
        "gross_loss_points": gross_loss,
        "net_points": net,
        "points_pf": pf,
    }


def validate_bundle(ledger: pd.DataFrame, anchor: pd.DataFrame, rr_config_id: str) -> list[dict]:
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    add("single_rr_config", set(ledger["rr_config_id"]) == {rr_config_id}, str(sorted(ledger["rr_config_id"].unique())))
    add("mae_mfe_present", ledger["mae_points"].notna().all() and ledger["mfe_points"].notna().all(), "MAE/MFE non-null")
    add("raw_stop_cap_200", float(ledger["raw_stop_points"].max()) <= 200.0, f"max={ledger['raw_stop_points'].max():.3f}")
    add(
        "effective_stop_cap_200",
        float(ledger["effective_stop_points"].max()) <= 200.0,
        f"max={ledger['effective_stop_points'].max():.3f}",
    )
    target_cap = 200.0 if rr_config_id == "1rr" else 300.0
    add("target_cap", float(ledger["target_points"].max()) <= target_cap, f"max={ledger['target_points'].max():.3f}")
    add(
        "pnl_r_relationship",
        ((ledger["pnl_R"] * ledger["raw_stop_points"] - ledger["pnl_points"]).abs().max() < 1e-9),
        "pnl_R * raw_stop == pnl_points",
    )
    add(
        "mae_r_relationship",
        ((ledger["mae_R"] * ledger["raw_stop_points"] - ledger["mae_points"]).abs().max() < 1e-9),
        "mae_R * raw_stop == mae_points",
    )
    add(
        "mfe_r_relationship",
        ((ledger["mfe_R"] * ledger["raw_stop_points"] - ledger["mfe_points"]).abs().max() < 1e-9),
        "mfe_R * raw_stop == mfe_points",
    )
    anchor_sel = anchor[anchor["rr_config_id"] == rr_config_id]
    add("one_anchor_for_selected_rr", len(anchor_sel) == 1, f"rows={len(anchor_sel)}")
    add(
        "anchor_mutual_exclusion_marked",
        "mutually_exclusive_config_alternative" in anchor.columns and anchor["mutually_exclusive_config_alternative"].astype(bool).all(),
        "mutual-exclusion flag present for both alternatives",
    )
    metrics = point_metrics(ledger["pnl_points"])
    if metrics["gross_loss_points"]:
        add(
            "pf_net_invariant",
            (metrics["net_points"] > 0 and metrics["points_pf"] > 1) or (metrics["net_points"] < 0 and metrics["points_pf"] < 1) or metrics["net_points"] == 0,
            f"net={metrics['net_points']:.3f}, pf={metrics['points_pf']:.6f}",
        )
    add(
        "net_equals_gross_profit_minus_loss",
        abs(metrics["net_points"] - (metrics["gross_profit_points"] - metrics["gross_loss_points"])) < 1e-9,
        "net identity",
    )
    return checks


def main() -> None:
    st.set_page_config(page_title="OG Forward Ledger", layout="wide")
    st.title("OG NQ Forward Ledger Explorer")
    st.caption("July 8-August 31, 2026 forward-source bundle. No annual paths. No position sizing baked in.")

    required = [
        "forward_1rr.csv",
        "forward_1_5rr.csv",
        "realized_anchor.csv",
        "calendar_blocks.csv",
        "point_scale_scenarios.json",
        "forward_scenario_manifest.json",
        "schema.json",
    ]
    missing = [name for name in required if not (FINAL_DIR / name).exists()]
    if missing:
        st.error(f"Missing final artifacts: {missing}")
        st.stop()

    rr_label = st.sidebar.radio("RR configuration", ["1rr", "1_5rr"], horizontal=True)
    ledger_file = "forward_1rr.csv" if rr_label == "1rr" else "forward_1_5rr.csv"
    ledger = load_csv(ledger_file)
    anchor = load_csv("realized_anchor.csv")
    blocks = load_csv("calendar_blocks.csv")
    point_scales = load_json("point_scale_scenarios.json")
    manifest = load_json("forward_scenario_manifest.json")

    pf_ids = sorted({s["pf_assumption_id"] for s in manifest["scenarios"] if s["rr_config_id"] == rr_label})
    regime_paths = sorted({s["regime_path"] for s in manifest["scenarios"] if s["rr_config_id"] == rr_label})
    scale_ids = [s["point_scale_scenario_id"] for s in point_scales if s["rr_config_id"] == rr_label]
    pf_id = st.sidebar.selectbox("PF assumption", pf_ids, index=pf_ids.index("FORWARD_PF_ASSUMPTION_1_50") if "FORWARD_PF_ASSUMPTION_1_50" in pf_ids else 0)
    regime = st.sidebar.selectbox("Regime path", regime_paths)
    scale = st.sidebar.selectbox("Point-scale scenario", scale_ids)

    metrics = point_metrics(ledger["pnl_points"])
    selected_anchor = anchor[anchor["rr_config_id"] == rr_label]
    anchor_points = float(selected_anchor["realized_pnl_points"].sum())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Rows", f"{len(ledger):,}")
    c2.metric("Net points", f"{metrics['net_points']:,.1f}")
    c3.metric("Points PF", f"{metrics['points_pf']:.3f}" if metrics["points_pf"] else "n/a")
    c4.metric("July 7 anchor", f"{anchor_points:,.1f}")
    c5.metric("Combined historical+anchor", f"{metrics['net_points'] + anchor_points:,.1f}")

    st.subheader("Integrity Checks")
    checks = pd.DataFrame(validate_bundle(ledger, anchor, rr_label))
    st.dataframe(checks, use_container_width=True, hide_index=True)
    if not checks["ok"].all():
        st.error("One or more integrity checks failed.")
    else:
        st.success("All fast integrity checks passed for the selected RR config.")

    st.subheader("Selected Scenario Metadata")
    selected_scenario = [
        s for s in manifest["scenarios"]
        if s["rr_config_id"] == rr_label and s["pf_assumption_id"] == pf_id and s["regime_path"] == regime
    ]
    selected_scale = [s for s in point_scales if s["rr_config_id"] == rr_label and s["point_scale_scenario_id"] == scale]
    col_a, col_b = st.columns(2)
    with col_a:
        st.json(selected_scenario[0] if selected_scenario else {})
    with col_b:
        st.json(selected_scale[0] if selected_scale else {})

    st.subheader("Exit Mix")
    st.bar_chart(ledger["effective_exit_reason"].value_counts())

    st.subheader("Ledger")
    cols = [
        "trade_packet_id",
        "source_year",
        "source_month",
        "source_session_date",
        "direction",
        "exit_reason",
        "effective_exit_reason",
        "pnl_points",
        "raw_stop_points",
        "target_points",
        "mae_points",
        "mfe_points",
        "pnl_R",
        "mae_R",
        "mfe_R",
        "rolling_pf_switch_state",
    ]
    st.dataframe(ledger[cols], use_container_width=True, height=520)
    st.download_button(
        "Download selected RR ledger CSV",
        ledger.to_csv(index=False).encode(),
        file_name=ledger_file,
        mime="text/csv",
    )

    st.subheader("Anchor Alternatives")
    st.dataframe(anchor, use_container_width=True, hide_index=True)
    st.info("Select exactly one RR config before adding the July 7 +150 anchor. The two anchor rows are mutually exclusive alternatives, not two portfolio trades.")

    st.subheader("Calendar Blocks")
    st.dataframe(blocks[blocks["rr_config_id"] == rr_label], use_container_width=True, height=360)


if __name__ == "__main__":
    main()
