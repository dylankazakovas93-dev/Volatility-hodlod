#!/usr/bin/env python3
"""Compare local Codex strict replay against Claude 1 canonical outputs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CLAUDE = Path("/tmp/vh_claude1")
OUT = ROOT / "outputs"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_id(x: str) -> str:
    return str(x).replace(":", "_")


def pf(s: pd.Series) -> float:
    gross = float(s[s > 0].sum())
    loss = float(-s[s < 0].sum())
    return gross / loss if loss else float("inf")


def maxdd(s: pd.Series) -> float:
    if s.empty:
        return 0.0
    eq = s.cumsum()
    return float((eq - eq.cummax()).min())


def clean_json(value):
    if isinstance(value, dict):
        return {k: clean_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_json(v) for v in value]
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return value


def summary(df: pd.DataFrame, pnl_col: str = "pnl", exit_col: str = "exit") -> dict:
    p = df[pnl_col].astype(float)
    ex = df[exit_col].value_counts()
    tp = int(ex.get("TP", 0))
    sl = int(ex.get("SL", 0))
    return {
        "n": len(df),
        "net": float(p.sum()),
        "pf": pf(p),
        "maxdd": maxdd(p),
        "avg": float(p.mean()) if len(p) else 0.0,
        "wr": float((p > 0.1).mean() * 100) if len(p) else 0.0,
        "twr": tp / (tp + sl) * 100 if tp + sl else 0.0,
        "TP": tp,
        "SL": sl,
        "BE": int(ex.get("BE", 0)),
        "cutoff": int(ex.get("cutoff", 0)),
    }


def load_claude_executed() -> pd.DataFrame:
    df = pd.read_csv(CLAUDE / "outputs/nq_strict_executed.csv")
    df["norm_level_id"] = df["level_id"].map(norm_id)
    df["physical_touch"] = pd.to_datetime(df["entry_time"], utc=True).astype(str)
    df["identity"] = df["norm_level_id"] + "|" + df["side"] + "|" + df["physical_touch"]
    return df


def load_codex_executed() -> pd.DataFrame:
    df = pd.read_csv(OUT / "canonical_strict_executed.csv")
    df["norm_level_id"] = df["level_id"].map(norm_id)
    df["physical_touch"] = pd.to_datetime(df["touched_at"], utc=True).astype(str)
    df["identity"] = df["norm_level_id"] + "|" + df["side"] + "|" + df["physical_touch"]
    return df


def classify(row: pd.Series) -> str:
    if row["_merge"] == "left_only":
        return "reference_only"
    if row["_merge"] == "right_only":
        return "codex_only"
    if row.get("exit_reason") != row.get("exit"):
        return "same_entry_different_exit"
    pnl_ref = row.get("pnl_ref")
    pnl_codex = row.get("pnl_codex")
    if pd.notna(pnl_ref) and pd.notna(pnl_codex) and abs(float(pnl_ref) - float(pnl_codex)) > 1e-6:
        return "same_exit_different_pnl"
    return "matched"


def main() -> None:
    ref = load_claude_executed()
    codex = load_codex_executed()

    merged = ref.merge(
        codex,
        on="identity",
        how="outer",
        suffixes=("_ref", "_codex"),
        indicator=True,
    )
    merged["mismatch_class"] = merged.apply(classify, axis=1)
    merged["net_impact_ref_minus_codex"] = merged["pnl_ref"].fillna(0) - merged["pnl_codex"].fillna(0)

    # User-facing compact columns.
    out = pd.DataFrame({
        "mismatch_class": merged["mismatch_class"],
        "identity": merged["identity"],
        "level_id_ref": merged.get("level_id_ref"),
        "level_id_codex": merged.get("level_id_codex"),
        "side_ref": merged.get("side_ref"),
        "side_codex": merged.get("side_codex"),
        "touch_ref": merged.get("physical_touch_ref"),
        "touch_codex": merged.get("physical_touch_codex"),
        "exit_ref": merged.get("exit_reason"),
        "exit_codex": merged.get("exit"),
        "pnl_ref": merged.get("pnl_ref"),
        "pnl_codex": merged.get("pnl_codex"),
        "net_impact_ref_minus_codex": merged["net_impact_ref_minus_codex"],
    })
    out = out[out["mismatch_class"] != "matched"].copy()
    out.to_csv(OUT / "codex_vs_claude1_differences.csv", index=False)

    # Compare physical touch populations by level side.
    ref_phys = pd.read_csv(CLAUDE / "outputs/nq_physical_first_touches.csv")
    cod_phys = pd.read_csv(OUT / "local_physical_touches.csv")
    ref_phys["norm_level_id"] = ref_phys["level_id"].map(norm_id)
    cod_phys["norm_level_id"] = cod_phys["level_id"].map(norm_id)
    phys = ref_phys.merge(cod_phys, on="norm_level_id", how="outer", suffixes=("_ref", "_codex"), indicator=True)
    phys_diff = phys[
        (phys["_merge"] != "both")
        | (pd.to_datetime(phys["touched_at_ref"], utc=True, errors="coerce").astype(str)
           != pd.to_datetime(phys["touched_at_codex"], utc=True, errors="coerce").astype(str))
    ].copy()
    phys_diff.to_csv(OUT / "codex_vs_claude1_physical_touch_differences.csv", index=False)

    # Canonical reference costs and concentration.
    cost_rows = []
    for cost in [0.0, 0.5, 1.0, 2.0]:
        adj = ref.copy()
        adj["pnl_adj"] = adj["pnl"] - cost
        cost_rows.append({"cost_pts": cost, **summary(adj, "pnl_adj", "exit_reason")})
    pd.DataFrame(cost_rows).to_csv(OUT / "codex_claude1_canonical_costs.csv", index=False)

    conc_rows = []
    for label, sub in [
        ("full_2018_2026", ref),
        ("exclude_2026", ref[ref["year"] <= 2025]),
        ("exclude_2025_2026", ref[ref["year"] <= 2024]),
        ("2018_2024_only", ref[ref["year"] <= 2024]),
    ]:
        conc_rows.append({"period": label, **summary(sub, "pnl", "exit_reason")})
    pd.DataFrame(conc_rows).to_csv(OUT / "codex_claude1_canonical_concentration.csv", index=False)

    first_div = out.copy()
    if not first_div.empty:
        first_div["_sort_touch"] = pd.to_datetime(first_div["touch_ref"].fillna(first_div["touch_codex"]), utc=True, errors="coerce")
        first_div = first_div.sort_values("_sort_touch")
        first = first_div.iloc[0].drop(labels=["_sort_touch"]).to_dict()
    else:
        first = None

    summary_obj = {
        "repository_url": "https://github.com/dylankazakovas93-dev/Volatility-hodlod",
        "codex_branch": "codex/nq-strict-reconciliation",
        "codex_commit": "49f1b3c468f02556e02e467dfec6e1d19318b52e",
        "claude1_branch": "strict-one-position-reconciliation",
        "claude1_commit": "c8c4337e2f88e8fc17a14bee88a5ed676e856f10",
        "claude1_hashes_verified_from_outputs": {
            "nq_strict_executed.csv": sha256(CLAUDE / "outputs/nq_strict_executed.csv"),
            "nq_eligible_1841.csv": sha256(CLAUDE / "outputs/nq_eligible_1841.csv"),
            "nq_strict_yearly.csv": sha256(CLAUDE / "outputs/nq_strict_yearly.csv"),
        },
        "claude1_reference": summary(ref, "pnl", "exit_reason"),
        "codex_noncanonical_local": summary(codex, "pnl", "exit"),
        "matched_rows": int((merged["mismatch_class"] == "matched").sum()),
        "reference_only_rows": int((merged["mismatch_class"] == "reference_only").sum()),
        "codex_only_rows": int((merged["mismatch_class"] == "codex_only").sum()),
        "same_entry_different_exit": int((merged["mismatch_class"] == "same_entry_different_exit").sum()),
        "same_exit_different_pnl": int((merged["mismatch_class"] == "same_exit_different_pnl").sum()),
        "total_net_impact_ref_minus_codex": float(merged["net_impact_ref_minus_codex"].sum()),
        "first_chronological_divergence": first,
        "physical_touch_diff_rows": int(len(phys_diff)),
        "canonical_bars_available_locally": False,
        "canonical_command_status": "BLOCKED_MISSING_CANONICAL_BARS_FILE",
    }
    (OUT / "codex_vs_claude1_summary.json").write_text(json.dumps(clean_json(summary_obj), indent=2, default=str) + "\n")
    codex.to_csv(OUT / "codex_canonical_executed.csv", index=False)
    pd.read_csv(OUT / "canonical_strict_skipped.csv").to_csv(OUT / "codex_canonical_skipped.csv", index=False)
    pd.read_csv(OUT / "canonical_strict_yearly.csv").to_csv(OUT / "codex_canonical_yearly.csv", index=False)
    print(json.dumps(clean_json(summary_obj), indent=2, default=str))


if __name__ == "__main__":
    main()
