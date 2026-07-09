"""Schema definitions and deterministic CSV writers for Stage 1 output files.

Every writer is deterministic: stable column order, fixed precision, UTC
timestamps, no randomisation.
"""
from __future__ import annotations

import csv
import hashlib
import os
from datetime import datetime, timezone

LEVELS_COLUMNS = [
    "level_id",
    "config_id",
    "session_date",
    "direction",
    "level_price",
    "cash_open",
    "vix_close",
    "vix_source_date",
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
    "created_at",
    "ib_minutes",
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
    "touch_type",
    "gap_through",
    "session_created",
    "session_touched",
    "overlap_cluster_id",
]

EXCURSIONS_COLUMNS = [
    "touch_id",
    "config_id",
    "level_direction",
    "touch_direction",
    "horizon",
    "horizon_minutes",
    "mae",
    "mfe",
    "start_timestamp",
    "end_timestamp",
    "first_passage",
]

PROVENANCE_COLUMNS = [
    "feature_name",
    "source_stage",
    "description",
    "created_at_utc",
    "commit_hash",
    "parameters",
]


def write_levels_csv(df, path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df = df[LEVELS_COLUMNS].copy()
    df = df.sort_values(["session_date", "direction"])
    df.to_csv(path, index=False, float_format="%.10f")


def write_touches_csv(df, path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cols = [c for c in TOUCHES_COLUMNS if c in df.columns]
    df_out = df[cols].copy()
    df_out = df_out.sort_values(["touch_bar_timestamp", "touch_id"])
    df_out.to_csv(path, index=False, float_format="%.10f")


def write_excursions_csv(df, path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cols = [c for c in EXCURSIONS_COLUMNS if c in df.columns]
    df_out = df[cols].copy()
    df_out = df_out.sort_values(["touch_id", "horizon"])
    df_out.to_csv(path, index=False, float_format="%.10f")


def write_provenance_csv(
    entries: list[dict], path: str, commit_hash: str = "UNCOMMITTED"
):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for e in entries:
        rows.append({
            "feature_name": e.get("feature_name", ""),
            "source_stage": e.get("source_stage", "stage1"),
            "description": e.get("description", ""),
            "created_at_utc": e.get("created_at_utc", now),
            "commit_hash": e.get("commit_hash", commit_hash),
            "parameters": e.get("parameters", "{}"),
        })
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PROVENANCE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()
