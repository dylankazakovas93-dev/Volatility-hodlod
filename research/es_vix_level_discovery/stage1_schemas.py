"""Schema definitions and deterministic CSV writers for Stage 1 output files.

Every writer is deterministic: stable column order, fixed precision, UTC
timestamps, no randomisation.

Writers fail loudly when any required column is absent from the input.
"""
from __future__ import annotations

import csv
import hashlib
import os

LEVELS_COLUMNS = [
    "level_id",
    "config_id",
    "session_date",
    "direction",
    "level_price",
    "cash_open",
    "vix_close",
    "vix_source_date",
    "vix_available_at",
    "sigma_day",
    "sigma_multiplier",
    "imp_up",
    "imp_dn",
    "ib_high",
    "ib_low",
    "ib_range",
    "ib_ext_up",
    "ib_ext_dn",
    "sigma_offset",
    "offset_family",
    "offset_parameter",
    "offset_value",
    "ib_minutes",
    "created_at",
    "first_eligible_at",
    "expiry_session",
    "line_life_sessions",
    "source_contract",
    "roll_day",
]

TOUCHES_COLUMNS = [
    "touch_id",
    "level_id",
    "config_id",
    "level_direction",
    "touch_direction",
    "level_price",
    "touch_bar_timestamp",
    "touch_bar_open",
    "touch_bar_high",
    "touch_bar_low",
    "reference_entry_price",
    "gap_through",
    "session_created",
    "session_touched",
    "level_age_sessions",
    "level_age_minutes",
    "sigma_day",
    "vix_source_date",
    "vix_available_at",
    "deterministic_order",
    "overlap_cluster_id",
]

EXCURSIONS_COLUMNS = [
    "touch_id",
    "config_id",
    "level_direction",
    "touch_direction",
    "horizon",
    "label_status",
    "label_start",
    "requested_end_exclusive",
    "actual_last_bar",
    "required_bar_count",
    "actual_bar_count",
    "mae",
    "mfe",
    "mae_sigma_ratio",
    "mfe_sigma_ratio",
    "mae_ib_range_ratio",
    "mfe_ib_range_ratio",
    "directional_horizon_close_return_sigma",
    "sigma_day",
    "fp_025_sigma",
    "fp_050_sigma",
    "fp_075_sigma",
    "fp_100_sigma",
    "fp_025_timestamp",
    "fp_050_timestamp",
    "fp_075_timestamp",
    "fp_100_timestamp",
]

FEATURE_PROVENANCE_COLUMNS = [
    "feature_name",
    "exact_formula",
    "source_data",
    "source_file",
    "source_timeframe",
    "feature_asof_time_definition",
    "decision_time_definition",
    "causality_rule",
    "causality_pass",
    "missing_value_rule",
    "revised_later",
    "units",
    "description",
]


def _require_columns(df, required: list[str], label: str):
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"{label}: missing required columns: {missing}"
        )


def write_levels_csv(df, path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    _require_columns(df, LEVELS_COLUMNS, "levels")
    df = df[LEVELS_COLUMNS].copy()
    df = df.sort_values(["session_date", "direction"])
    df.to_csv(path, index=False, float_format="%.10f")


def write_touches_csv(df, path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    _require_columns(df, TOUCHES_COLUMNS, "touches")
    df = df[TOUCHES_COLUMNS].copy()
    df = df.sort_values(["touch_bar_timestamp", "touch_id"])
    df.to_csv(path, index=False, float_format="%.10f")


def write_excursions_csv(df, path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    _require_columns(df, EXCURSIONS_COLUMNS, "excursions")
    df = df[EXCURSIONS_COLUMNS].copy()
    df = df.sort_values(["touch_id", "horizon"])
    df.to_csv(path, index=False, float_format="%.10f")


def write_provenance_csv(
    entries: list[dict], path: str
):
    """Write FEATURE_PROVENANCE.csv.

    The caller must supply every required column. No wall-clock timestamp
    is injected — run metadata comes from a frozen manifest supplied by
    the caller.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    for e in entries:
        missing = [c for c in FEATURE_PROVENANCE_COLUMNS if c not in e]
        if missing:
            raise ValueError(
                f"provenance entry missing columns: {missing}"
            )
    rows = [{c: e[c] for c in FEATURE_PROVENANCE_COLUMNS} for e in entries]
    rows.sort(key=lambda r: r["feature_name"])
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FEATURE_PROVENANCE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()
