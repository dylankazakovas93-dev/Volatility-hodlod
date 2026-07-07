"""Assemble one continuous chronological trade sequence per config, spanning
every year ever computed in this research line for that config:
2013,2014,2015 (external) + 2018,2020,2023,2026 (build) + 2019,2021,2022,2024,2025 (validation).

2016 and 2017 were never computed for either config -- they are absent from
the sequence, not fabricated. This script only concatenates, sorts, and
checks for duplication/overlap; it does not recompute or alter any trade.
"""
from __future__ import annotations
import pandas as pd
from pathlib import Path

OUT_DIR = Path("outputs/og_regime_killswitch")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SOURCES = {
    "primary_150r": [
        ("external_2013_2015", "outputs/og_external_2013_2015/primary_150r_trades.csv"),
        ("build_years", "outputs/og_build_years/final_buildoff_B_build_years_trades.csv"),
        ("validation", "outputs/og_validation/OG_PRIMARY_150R_validation_trades.csv"),
    ],
    "operational_100r": [
        ("external_2013_2015", "outputs/og_external_2013_2015/operational_100r_trades.csv"),
        ("build_years", "outputs/og_build_years/final_buildoff_A_build_years_trades.csv"),
        ("validation", "outputs/og_validation/OG_OPERATIONAL_100R_validation_trades.csv"),
    ],
}

# Build-year files also contain years outside the "build years" set in this
# research line (they only ever hold 2018/2020/2023/2026 per prior audits, but
# we assert this explicitly rather than assume it).
EXPECTED_BUILD_YEARS = {2018, 2020, 2023, 2026}
EXPECTED_EXTERNAL_YEARS = {2013, 2014, 2015}
EXPECTED_VALIDATION_YEARS = {2019, 2021, 2022, 2024, 2025}


def assemble(config_key: str, parts):
    frames = []
    for source_tag, path in parts:
        df = pd.read_csv(path)
        df["source"] = source_tag
        frames.append(df)

    # verify years match expectation per source before concatenating
    for source_tag, df in zip([p[0] for p in parts], frames):
        yrs = set(df["year"].unique().tolist())
        if source_tag == "external_2013_2015":
            assert yrs == EXPECTED_EXTERNAL_YEARS, f"{config_key}/{source_tag} years {yrs}"
        elif source_tag == "build_years":
            assert yrs == EXPECTED_BUILD_YEARS, f"{config_key}/{source_tag} years {yrs}"
        elif source_tag == "validation":
            assert yrs == EXPECTED_VALIDATION_YEARS, f"{config_key}/{source_tag} years {yrs}"

    full = pd.concat(frames, ignore_index=True)
    full["_entry_time_utc"] = pd.to_datetime(full["entry_time"], utc=True)
    full["_exit_time_utc"] = pd.to_datetime(full["exit_time"], utc=True)
    full = full.sort_values("_entry_time_utc", kind="mergesort").reset_index(drop=True)
    full = full.drop(columns=["_exit_time_utc"])

    # Duplication / overlap check: no level_id+entry_time combination should
    # appear more than once across sources (that would indicate a seam
    # duplication between e.g. external and build-year extracts).
    dup_key = full["level_id"].astype(str) + "|" + full["entry_time"].astype(str) + "|" + full["source"]
    assert dup_key.is_unique, "Duplicate (level_id, entry_time, source) rows found"

    key2 = full["level_id"].astype(str) + "|" + full["entry_time"].astype(str)
    dup_across_sources = full[key2.duplicated(keep=False)]
    if len(dup_across_sources):
        raise AssertionError(
            f"Found {len(dup_across_sources)} rows with identical level_id+entry_time "
            f"across different sources (possible seam duplication):\n{dup_across_sources}"
        )

    all_years = sorted(full["year"].unique().tolist())
    gap_years = [y for y in range(min(all_years), max(all_years) + 1) if y not in all_years]

    span_min, span_max = full["_entry_time_utc"].min(), full["_entry_time_utc"].max()
    out_path = OUT_DIR / f"{config_key}_full_chronological_trades.csv"
    full.drop(columns=["_entry_time_utc"]).to_csv(out_path, index=False)

    print(f"[{config_key}] n_trades={len(full)} span={span_min} .. {span_max}")
    print(f"[{config_key}] years present: {all_years}")
    print(f"[{config_key}] gap years (never computed, expected {{2016,2017}}): {gap_years}")
    print(f"[{config_key}] wrote {out_path}")
    return full


if __name__ == "__main__":
    for config_key, parts in SOURCES.items():
        assemble(config_key, parts)
