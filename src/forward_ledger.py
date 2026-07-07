"""Forward-ledger source-pool and scenario helpers.

These helpers operate only on committed OG regime-killswitch ledgers. They do
not recompute or alter historical trades; they normalize already-simulated
trade packets and build explicit scenario metadata for downstream Monte Carlo.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.metrics import max_drawdown, profit_factor


SELECTED_PARAMS = "window=100,threshold=1.1,reentry=symmetric"
ROLLING_PF_WINDOW = 100
ROLLING_PF_THRESHOLD = 1.10
PF_TARGETS = (1.35, 1.50, 1.65)
SCENARIO_FAMILIES = ("stable", "gradual_degradation", "favourable_persistence", "abrupt_tail")
FORWARD_HORIZON_MONTHS = 2
EXTERNAL_2013_2015_BARS = "data/external_2013_2015/raw/glbx-mdp3-20130101-20151231.ohlcv-1m.csv.zst"
DEFAULT_CONTINUOUS_2018_2026_BARS = "data/nq_1m/nq_continuous_2018_2026_1m.csv"
CONTINUOUS_BARS_ENV = "NQ_1M_2018_2026_CSV"
STANDARD_CONTRACT_RE = r"^NQ[HMUZ]\d$"
CONFIGS = {
    "operational_100r": {
        "pool_id": "1rr",
        "rr": 1.0,
        "label": "OG_OPERATIONAL_100R",
        "trade_file": "outputs/og_regime_killswitch/operational_100r_full_chronological_trades.csv",
        "trigger_file": "outputs/og_regime_killswitch/operational_100r_trigger_log_rolling_pf_w100_t1.1_symmetric.csv",
    },
    "primary_150r": {
        "pool_id": "1_5rr",
        "rr": 1.5,
        "label": "OG_PRIMARY_150R",
        "trade_file": "outputs/og_regime_killswitch/primary_150r_full_chronological_trades.csv",
        "trigger_file": "outputs/og_regime_killswitch/primary_150r_trigger_log_rolling_pf_w100_t1.1_symmetric.csv",
    },
}

TRADE_REQUIRED_COLUMNS = {
    "level_id",
    "session_date",
    "year",
    "side",
    "entry_time",
    "exit_time",
    "entry_price",
    "exit_price",
    "level",
    "anchor",
    "cap",
    "exit_reason",
    "pnl",
    "gap_through",
    "source",
}
TRIGGER_REQUIRED_COLUMNS = {"session_date", "year", "entry_time", "is_flat"}
POOL_REQUIRED_COLUMNS = {
    "pool_id",
    "config",
    "level_id",
    "year",
    "source",
    "side",
    "entry_time",
    "exit_time",
    "exit_reason",
    "raw_stop_pts",
    "effective_stop_pts",
    "target_pts",
    "pnl_pts_baseline",
    "pnl_pts_effective",
    "mae_pts",
    "mfe_pts",
    "is_flat",
}
EXCURSION_REQUIRED_COLUMNS = {
    "entry_time",
    "exit_time",
    "entry_price",
    "side",
    "source",
    "exit_reason",
    "cap",
}


@dataclass(frozen=True)
class MetricSummary:
    gross_profit_pts: float
    gross_loss_pts: float
    net_pts: float
    points_pf: float

    def as_dict(self) -> dict:
        return {
            "gross_profit_pts": self.gross_profit_pts,
            "gross_loss_pts": self.gross_loss_pts,
            "net_pts": self.net_pts,
            "points_pf": self.points_pf,
        }


@dataclass(frozen=True)
class ExcursionContext:
    bars_2013_2015: pd.DataFrame
    bars_2018_2026: pd.DataFrame
    bars_2013_2015_path: str
    bars_2018_2026_path: str


def require_columns(df: pd.DataFrame, required: set[str], source_name: str) -> None:
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{source_name} missing required columns: {missing}")


def gross_point_metrics(pnl: pd.Series | np.ndarray) -> MetricSummary:
    s = pd.Series(pnl, dtype=float)
    gross_profit = float(s[s > 0].sum())
    gross_loss = float(-s[s < 0].sum())
    net = float(s.sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    return MetricSummary(gross_profit, gross_loss, net, pf)


def assert_pf_invariants(pnl: pd.Series | np.ndarray) -> None:
    m = gross_point_metrics(pnl)
    assert math.isclose(m.net_pts, m.gross_profit_pts - m.gross_loss_pts, rel_tol=0.0, abs_tol=1e-9)
    if m.gross_loss_pts > 0 and m.net_pts > 0:
        assert m.points_pf > 1.0
    if m.gross_loss_pts > 0 and m.net_pts < 0:
        assert m.points_pf < 1.0


def _read_trades(repo_root: Path, config: str) -> pd.DataFrame:
    info = CONFIGS[config]
    trades = pd.read_csv(repo_root / info["trade_file"])
    trigger = pd.read_csv(repo_root / info["trigger_file"])
    require_columns(trades, TRADE_REQUIRED_COLUMNS, info["trade_file"])
    require_columns(trigger, TRIGGER_REQUIRED_COLUMNS, info["trigger_file"])

    trades = trades.copy()
    trigger = trigger.copy()
    trades["entry_time_utc"] = pd.to_datetime(trades["entry_time"], utc=True)
    trigger["entry_time_utc"] = pd.to_datetime(trigger["entry_time"], utc=True)
    merged = trades.merge(
        trigger[["entry_time_utc", "is_flat"]],
        on="entry_time_utc",
        how="left",
        validate="one_to_one",
    )
    if merged["is_flat"].isna().any():
        raise ValueError(f"{config} trigger log does not cover every chronological trade")
    merged["is_flat"] = merged["is_flat"].astype(bool)
    return merged.drop(columns=["entry_time_utc"])


def _resolve_2018_2026_bars_path(repo_root: Path, explicit_path: str | Path | None = None) -> Path:
    raw = explicit_path or os.environ.get(CONTINUOUS_BARS_ENV) or DEFAULT_CONTINUOUS_2018_2026_BARS
    path = Path(raw)
    if not path.is_absolute():
        path = repo_root / path
    return path


def _load_bars(path: Path, timestamp_col: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"required 1-minute OHLC file not found: {path}")
    bars = pd.read_csv(path, usecols=[timestamp_col, "open", "high", "low", "close"])
    bars[timestamp_col] = pd.to_datetime(bars[timestamp_col], utc=True)
    bars = bars.rename(columns={timestamp_col: "timestamp"}).set_index("timestamp").sort_index()
    if bars.index.has_duplicates:
        bars = bars.groupby(level=0, sort=True)[["open", "high", "low", "close"]].last()
    return bars[["open", "high", "low", "close"]].astype(float)


def _load_external_continuous_bars(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"required 2013-2015 raw OHLC file not found: {path}")
    raw = pd.read_csv(path, usecols=["ts_event", "open", "high", "low", "close", "volume", "symbol"])
    raw["ts_event"] = pd.to_datetime(raw["ts_event"], utc=True)
    raw["date"] = raw["ts_event"].dt.date
    standard = raw[raw["symbol"].str.match(STANDARD_CONTRACT_RE)].copy()
    if standard.empty:
        raise ValueError(f"{path} contained no standard NQ quarterly contract bars")
    daily_volume = standard.groupby(["date", "symbol"])["volume"].sum().reset_index()
    winner = daily_volume.loc[daily_volume.groupby("date")["volume"].idxmax(), ["date", "symbol"]].rename(
        columns={"symbol": "winner"}
    )
    kept = standard.merge(winner, on="date")
    kept = kept[kept["symbol"] == kept["winner"]].sort_values("ts_event")
    kept = kept.rename(columns={"ts_event": "timestamp"}).set_index("timestamp")
    if kept.index.has_duplicates:
        kept = kept.groupby(level=0, sort=True)[["open", "high", "low", "close"]].last()
    return kept[["open", "high", "low", "close"]].astype(float)


def load_excursion_context(repo_root: Path, continuous_2018_2026_path: str | Path | None = None) -> ExcursionContext:
    """Load the raw 1-minute bars needed to compute actual trade excursions.

    The 2013-2015 external bars are committed. The 2018-2026 continuous file is
    intentionally large and is normally supplied as ignored local data or via
    NQ_1M_2018_2026_CSV.
    """
    external_path = repo_root / EXTERNAL_2013_2015_BARS
    continuous_path = _resolve_2018_2026_bars_path(repo_root, continuous_2018_2026_path)
    return ExcursionContext(
        bars_2013_2015=_load_external_continuous_bars(external_path),
        bars_2018_2026=_load_bars(continuous_path, "timestamp"),
        bars_2013_2015_path=str(external_path),
        bars_2018_2026_path=str(continuous_path),
    )


def _bars_for_trade(ctx: ExcursionContext, source: str) -> pd.DataFrame:
    if source == "external_2013_2015":
        return ctx.bars_2013_2015
    if source in {"build_years", "validation"}:
        return ctx.bars_2018_2026
    raise ValueError(f"unknown trade source for excursion scan: {source}")


def compute_trade_excursions(trades: pd.DataFrame, ctx: ExcursionContext) -> pd.DataFrame:
    require_columns(trades, EXCURSION_REQUIRED_COLUMNS, "trade excursion source")
    rows = []
    missing = []
    for idx, row in trades.reset_index(drop=True).iterrows():
        source = str(row["source"])
        bars = _bars_for_trade(ctx, source)
        entry_ts = pd.to_datetime(row["entry_time"], utc=True)
        exit_ts = pd.to_datetime(row["exit_time"], utc=True)
        path = bars.loc[entry_ts:exit_ts]
        if path.empty:
            missing.append((idx, source, str(row["entry_time"]), str(row["exit_time"])))
            rows.append((np.nan, np.nan, 0, "missing_bar_path"))
            continue

        sign = 1.0 if str(row["side"]) == "lower" else -1.0
        entry = float(row["entry_price"])
        fav_high = sign * (path["high"].to_numpy(float) - entry)
        fav_low = sign * (path["low"].to_numpy(float) - entry)
        bar_fav = np.maximum(fav_high, fav_low)
        bar_adv = np.minimum(fav_high, fav_low)
        mfe = max(0.0, float(np.nanmax(bar_fav)))
        mae = max(0.0, -float(np.nanmin(bar_adv)))
        rows.append((mae, mfe, int(len(path)), "computed_from_1m_ohlc_entry_to_exit_inclusive"))

    if missing:
        sample = missing[:5]
        raise ValueError(
            "could not compute MAE/MFE because raw 1-minute bars are missing for "
            f"{len(missing)} trades; first missing paths: {sample}"
        )
    return pd.DataFrame(rows, columns=["mae_pts", "mfe_pts", "intratrade_bar_count", "mae_mfe_status"])


def build_normalized_pool(repo_root: Path, config: str, excursion_context: ExcursionContext | None = None) -> pd.DataFrame:
    info = CONFIGS[config]
    trades = _read_trades(repo_root, config)
    if excursion_context is not None:
        excursions = compute_trade_excursions(trades, excursion_context)
    else:
        excursions = pd.DataFrame(
            {
                "mae_pts": np.nan,
                "mfe_pts": np.nan,
                "intratrade_bar_count": 0,
                "mae_mfe_status": "missing_source_not_loaded",
            },
            index=trades.index,
        )
    out = pd.DataFrame(
        {
            "pool_id": info["pool_id"],
            "config": config,
            "config_label": info["label"],
            "target_r": info["rr"],
            "level_id": trades["level_id"].astype(str),
            "session_date": trades["session_date"],
            "year": trades["year"].astype(int),
            "source": trades["source"].astype(str),
            "side": trades["side"].astype(str),
            "entry_time": trades["entry_time"],
            "exit_time": trades["exit_time"],
            "entry_price": trades["entry_price"].astype(float),
            "exit_price": trades["exit_price"].astype(float),
            "level": trades["level"].astype(float),
            "anchor": trades["anchor"].astype(float),
            "raw_stop_pts": trades["cap"].astype(float),
            "effective_stop_pts": trades["cap"].astype(float),
            "target_pts": trades["cap"].astype(float) * float(info["rr"]),
            "pnl_pts_baseline": trades["pnl"].astype(float),
            "pnl_pts_effective": np.where(trades["is_flat"].to_numpy(), 0.0, trades["pnl"].astype(float)),
            "mae_pts": excursions["mae_pts"].to_numpy(float),
            "mfe_pts": excursions["mfe_pts"].to_numpy(float),
            "intratrade_bar_count": excursions["intratrade_bar_count"].to_numpy(int),
            "mae_mfe_status": excursions["mae_mfe_status"].astype(str).to_numpy(),
            "mae_mfe_resolution": "1m_ohlc_bar_extrema",
            "exit_reason": trades["exit_reason"].astype(str),
            "effective_exit_reason": np.where(trades["is_flat"].to_numpy(), "FLAT", trades["exit_reason"].astype(str)),
            "gap_through": trades["gap_through"].astype(bool),
            "is_flat": trades["is_flat"].astype(bool),
            "rolling_pf_window_trades": ROLLING_PF_WINDOW,
            "rolling_pf_threshold": ROLLING_PF_THRESHOLD,
            "rolling_pf_reentry": "symmetric",
        }
    )
    out["r_multiple_baseline"] = out["pnl_pts_baseline"] / out["effective_stop_pts"]
    out["r_multiple_effective"] = out["pnl_pts_effective"] / out["effective_stop_pts"]
    out["mae_r"] = out["mae_pts"] / out["effective_stop_pts"]
    out["mfe_r"] = out["mfe_pts"] / out["effective_stop_pts"]
    require_columns(out, POOL_REQUIRED_COLUMNS, f"normalized {config} pool")
    return out


def summarize_pool(pool: pd.DataFrame, pnl_col: str = "pnl_pts_effective") -> dict:
    require_columns(pool, POOL_REQUIRED_COLUMNS, "forward pool")
    pnl = pool[pnl_col].astype(float)
    r = pnl / pool["effective_stop_pts"].astype(float)
    counts = pool["effective_exit_reason" if pnl_col == "pnl_pts_effective" else "exit_reason"].value_counts()
    m = gross_point_metrics(pnl)
    return {
        **m.as_dict(),
        "n_trades": int(len(pool)),
        "n_active_trades": int((~pool["is_flat"]).sum()) if pnl_col == "pnl_pts_effective" else int(len(pool)),
        "n_flat_trades": int(pool["is_flat"].sum()) if pnl_col == "pnl_pts_effective" else 0,
        "PF_R": float(profit_factor(r)),
        "avg_R_per_trade": float(r.mean()),
        "max_dd_pts": float(max_drawdown(pnl)),
        "max_dd_R": float(max_drawdown(r)),
        "TP": int(counts.get("TP", 0)),
        "SL": int(counts.get("SL", 0)),
        "BE": int(counts.get("BE", 0)),
        "cutoff": int(counts.get("cutoff", 0)),
        "FLAT": int(counts.get("FLAT", 0)),
    }


def build_block_table(pool: pd.DataFrame) -> pd.DataFrame:
    require_columns(pool, POOL_REQUIRED_COLUMNS, "forward source pool")
    df = pool.copy()
    df["pnl_class"] = np.select(
        [df["pnl_pts_effective"] > 0, df["pnl_pts_effective"] < 0],
        ["profit", "loss"],
        default="scratch_or_flat",
    )
    group_cols = ["config", "pool_id", "source", "year", "side", "effective_exit_reason", "pnl_class"]
    rows = []
    for key, g in df.groupby(group_cols, dropna=False, sort=True):
        pnl = g["pnl_pts_effective"].astype(float)
        m = gross_point_metrics(pnl)
        row = dict(zip(group_cols, key))
        row.update(
            {
                "n_trades": int(len(g)),
                "base_weight": float(len(g) / len(df)),
                **m.as_dict(),
                "avg_stop_pts": float(g["effective_stop_pts"].mean()),
                "avg_target_pts": float(g["target_pts"].mean()),
                "avg_abs_pnl_pts": float(pnl.abs().mean()),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _family_base_multiplier(blocks: pd.DataFrame, family: str) -> np.ndarray:
    mult = np.ones(len(blocks), dtype=float)
    bad_year = blocks["year"].isin([2014, 2015, 2019, 2024]).to_numpy()
    late_year = (blocks["year"].astype(int) >= 2024).to_numpy()
    good_year = blocks["year"].isin([2013, 2018, 2020, 2021, 2022, 2023, 2025, 2026]).to_numpy()
    loss = (blocks["pnl_class"] == "loss").to_numpy()
    profit = (blocks["pnl_class"] == "profit").to_numpy()
    flat = (blocks["effective_exit_reason"] == "FLAT").to_numpy()

    if family == "stable":
        return mult
    if family == "gradual_degradation":
        mult *= np.where(late_year & loss, 1.35, 1.0)
        mult *= np.where(late_year & profit, 0.90, 1.0)
        mult *= np.where(flat, 1.05, 1.0)
        return mult
    if family == "favourable_persistence":
        mult *= np.where(good_year & profit, 1.25, 1.0)
        mult *= np.where(good_year & loss, 0.90, 1.0)
        mult *= np.where(flat, 0.85, 1.0)
        return mult
    if family == "abrupt_tail":
        mult *= np.where(bad_year & loss, 1.70, 1.0)
        mult *= np.where(bad_year & profit, 0.75, 1.0)
        mult *= np.where(flat, 1.15, 1.0)
        return mult
    raise ValueError(f"unknown scenario family {family}")


def _pf_for_weights(blocks: pd.DataFrame, weights: np.ndarray) -> float:
    gp = float(np.sum(weights * blocks["gross_profit_pts"].to_numpy(float)))
    gl = float(np.sum(weights * blocks["gross_loss_pts"].to_numpy(float)))
    return gp / gl if gl > 0 else float("inf")


def solve_pf_weights(blocks: pd.DataFrame, target_pf: float, family: str) -> np.ndarray:
    base = blocks["base_weight"].to_numpy(float) * _family_base_multiplier(blocks, family)
    pnl_signal = blocks["net_pts"].to_numpy(float)
    scale = np.nanmedian(np.abs(pnl_signal[pnl_signal != 0])) if np.any(pnl_signal != 0) else 1.0
    signal = np.clip(pnl_signal / max(scale, 1e-9), -8.0, 8.0)

    def weights_for(lam: float) -> np.ndarray:
        w = base * np.exp(lam * signal)
        return w / w.sum()

    lo, hi = -20.0, 20.0
    pf_lo = _pf_for_weights(blocks, weights_for(lo))
    pf_hi = _pf_for_weights(blocks, weights_for(hi))
    if not (pf_lo <= target_pf <= pf_hi):
        # Keep every block represented even when the exact target is outside
        # the attainable range for these historical blocks.
        return weights_for(lo if abs(pf_lo - target_pf) < abs(pf_hi - target_pf) else hi)
    for _ in range(80):
        mid = (lo + hi) / 2.0
        pf_mid = _pf_for_weights(blocks, weights_for(mid))
        if pf_mid < target_pf:
            lo = mid
        else:
            hi = mid
    return weights_for((lo + hi) / 2.0)


def build_point_scale_scenarios(source_pool: pd.DataFrame) -> list[dict]:
    scenarios = []
    for pool_id, g in source_pool.groupby("pool_id", sort=True):
        stops = g["effective_stop_pts"].astype(float)
        targets = g["target_pts"].astype(float)
        pnl = g["pnl_pts_effective"].astype(float)
        mae = g["mae_pts"].astype(float)
        mfe = g["mfe_pts"].astype(float)
        scenarios.append(
            {
                "point_scale_id": f"{pool_id}_observed_geometry",
                "pool_id": pool_id,
                "controls": ["raw_stop_pts", "effective_stop_pts", "target_pts", "pnl_pts", "mae_pts", "mfe_pts"],
                "stop_pts_quantiles": _quantiles(stops),
                "target_pts_quantiles": _quantiles(targets),
                "abs_pnl_pts_quantiles": _quantiles(pnl.abs()),
                "mae_pts_quantiles": _quantiles(mae),
                "mfe_pts_quantiles": _quantiles(mfe),
                "mae_mfe_status": sorted(g["mae_mfe_status"].dropna().unique().tolist()),
                "mae_mfe_resolution": sorted(g["mae_mfe_resolution"].dropna().unique().tolist()),
                "point_scale_is_independent_from_expectancy": True,
            }
        )
    combined = source_pool.copy()
    scenarios.append(
        {
            "point_scale_id": "combined_current_100_200pt_capable_geometry",
            "pool_id": "combined",
            "controls": ["raw_stop_pts", "effective_stop_pts", "target_pts", "pnl_pts", "mae_pts", "mfe_pts"],
            "stop_pts_quantiles": _quantiles(combined["effective_stop_pts"].astype(float)),
            "target_pts_quantiles": _quantiles(combined["target_pts"].astype(float)),
            "abs_pnl_pts_quantiles": _quantiles(combined["pnl_pts_effective"].abs()),
            "mae_pts_quantiles": _quantiles(combined["mae_pts"].astype(float)),
            "mfe_pts_quantiles": _quantiles(combined["mfe_pts"].astype(float)),
            "mae_mfe_status": sorted(combined["mae_mfe_status"].dropna().unique().tolist()),
            "mae_mfe_resolution": sorted(combined["mae_mfe_resolution"].dropna().unique().tolist()),
            "point_scale_is_independent_from_expectancy": True,
        }
    )
    return scenarios


def _quantiles(s: pd.Series) -> dict:
    return {f"p{int(q * 100):02d}": float(s.quantile(q)) for q in [0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]}


def build_scenarios(source_pool: pd.DataFrame) -> tuple[list[dict], pd.DataFrame]:
    block_frames = []
    manifests = []
    for config, cfg_pool in source_pool.groupby("config", sort=True):
        blocks = build_block_table(cfg_pool).reset_index(drop=True)
        base_summary = summarize_pool(cfg_pool)
        for family in SCENARIO_FAMILIES:
            for target_pf in PF_TARGETS:
                weights = solve_pf_weights(blocks, target_pf, family)
                achieved_pf = _pf_for_weights(blocks, weights)
                manifest_id = f"{config}__pf_{target_pf:.2f}__{family}"
                weighted = blocks.copy()
                weighted["scenario_id"] = manifest_id
                weighted["scenario_family"] = family
                weighted["target_points_pf"] = target_pf
                weighted["scenario_weight"] = weights
                weighted["achieved_points_pf"] = achieved_pf
                block_frames.append(weighted)
                manifests.append(
                    {
                        "scenario_id": manifest_id,
                        "config": config,
                        "rr_config_id": CONFIGS[config]["pool_id"],
                        "target_r": CONFIGS[config]["rr"],
                        "pool_id": CONFIGS[config]["pool_id"],
                        "point_scale_id": f"{CONFIGS[config]['pool_id']}_observed_geometry",
                        "expectancy_id": f"{family}_pf_{target_pf:.2f}",
                        "forward_horizon_months": FORWARD_HORIZON_MONTHS,
                        "scenario_family": family,
                        "target_points_pf": target_pf,
                        "achieved_points_pf": achieved_pf,
                        "base_selected_switch_points_pf": base_summary["points_pf"],
                        "rolling_pf_mechanism": {
                            "window_trades": ROLLING_PF_WINDOW,
                            "threshold": ROLLING_PF_THRESHOLD,
                            "reentry": "symmetric",
                        },
                        "complete_block_weighting": True,
                        "block_count": int(len(blocks)),
                        "weight_sum": float(weights.sum()),
                        "point_scale_expectancy_separate": True,
                    }
                )
    return manifests, pd.concat(block_frames, ignore_index=True)


def build_rr_config_manifest(pools: dict[str, pd.DataFrame]) -> list[dict]:
    out = []
    for config, info in CONFIGS.items():
        pool = pools[config]
        summary = summarize_pool(pool)
        pool_file = {
            "1rr": "historical_trade_pool_1rr.csv",
            "1_5rr": "historical_trade_pool_1_5rr.csv",
        }[info["pool_id"]]
        out.append(
            {
                "rr_config_id": info["pool_id"],
                "config": config,
                "config_label": info["label"],
                "target_r": info["rr"],
                "source_library_file": pool_file,
                "source_library_rows": int(len(pool)),
                "forward_horizon_months": FORWARD_HORIZON_MONTHS,
                "scenario_filter": {
                    "scenario_manifests.config": config,
                    "scenario_block_weights.config": config,
                    "forward_source_pool.pool_id": info["pool_id"],
                },
                "selected_switch_points_pf": summary["points_pf"],
                "selected_switch_pf_r": summary["PF_R"],
                "note": (
                    "This selects the RR geometry and scenario family. The source library "
                    "is historical calibration/input, not a single 2-month forward ledger."
                ),
            }
        )
    return out


def build_two_month_windows(source_pool: pd.DataFrame) -> pd.DataFrame:
    require_columns(source_pool, POOL_REQUIRED_COLUMNS, "forward source pool")
    df = source_pool.copy()
    df["session_month"] = pd.to_datetime(df["session_date"]).dt.to_period("M")
    rows = []
    for config, cfg_pool in df.groupby("config", sort=True):
        cfg_months = sorted(cfg_pool["session_month"].unique())
        month_set = set(cfg_months)
        for start in cfg_months:
            end = start + (FORWARD_HORIZON_MONTHS - 1)
            if end not in month_set:
                continue
            mask = (cfg_pool["session_month"] >= start) & (cfg_pool["session_month"] <= end)
            window = cfg_pool.loc[mask].copy()
            if window.empty:
                continue
            summary = summarize_pool(window)
            rows.append(
                {
                    "rr_config_id": CONFIGS[config]["pool_id"],
                    "config": config,
                    "target_r": CONFIGS[config]["rr"],
                    "window_start_month": str(start),
                    "window_end_month": str(end),
                    "horizon_months": FORWARD_HORIZON_MONTHS,
                    "n_trades": summary["n_trades"],
                    "n_active_trades": summary["n_active_trades"],
                    "n_flat_trades": summary["n_flat_trades"],
                    "gross_profit_pts": summary["gross_profit_pts"],
                    "gross_loss_pts": summary["gross_loss_pts"],
                    "net_pts": summary["net_pts"],
                    "points_pf": summary["points_pf"],
                    "PF_R": summary["PF_R"],
                    "avg_R_per_trade": summary["avg_R_per_trade"],
                    "max_dd_pts": summary["max_dd_pts"],
                    "max_dd_R": summary["max_dd_R"],
                    "TP": summary["TP"],
                    "SL": summary["SL"],
                    "BE": summary["BE"],
                    "cutoff": summary["cutoff"],
                    "FLAT": summary["FLAT"],
                    "median_stop_pts": float(window["effective_stop_pts"].median()),
                    "median_target_pts": float(window["target_pts"].median()),
                    "median_mae_pts": float(window["mae_pts"].median()),
                    "median_mfe_pts": float(window["mfe_pts"].median()),
                }
            )
    return pd.DataFrame(rows)


def build_two_month_forward_horizon(windows: pd.DataFrame, manifests: list[dict]) -> dict:
    if windows.empty:
        raise ValueError("two-month horizon windows are empty")
    configs = {}
    for config, g in windows.groupby("config", sort=True):
        configs[config] = {
            "rr_config_id": CONFIGS[config]["pool_id"],
            "target_r": CONFIGS[config]["rr"],
            "historical_two_month_windows": int(len(g)),
            "n_trades_quantiles": _quantiles(g["n_trades"].astype(float)),
            "n_active_trades_quantiles": _quantiles(g["n_active_trades"].astype(float)),
            "points_pf_quantiles": _quantiles(g["points_pf"].replace([np.inf, -np.inf], np.nan).dropna().astype(float)),
            "net_pts_quantiles": _quantiles(g["net_pts"].astype(float)),
            "median_stop_pts_quantiles": _quantiles(g["median_stop_pts"].astype(float)),
            "median_mae_pts_quantiles": _quantiles(g["median_mae_pts"].astype(float)),
            "median_mfe_pts_quantiles": _quantiles(g["median_mfe_pts"].astype(float)),
            "scenario_ids": [m["scenario_id"] for m in manifests if m["config"] == config],
        }
    return {
        "forward_horizon_id": "two_calendar_months",
        "horizon_months": FORWARD_HORIZON_MONTHS,
        "purpose": (
            "Use this to size and describe two-month forward simulations. "
            "Do not treat the full historical source library as the two-month ledger."
        ),
        "rr_switch_field": "rr_config_id",
        "rr_config_manifest": "rr_config_manifest.json",
        "historical_window_file": "two_month_historical_windows.csv",
        "configs": configs,
    }


def build_expectancy_scenarios(manifests: list[dict]) -> list[dict]:
    out = []
    for family in SCENARIO_FAMILIES:
        out.append(
            {
                "expectancy_family": family,
                "description": {
                    "stable": "Preserve baseline block mix, then tilt only enough to reach target PF.",
                    "gradual_degradation": "Increase later-year loss and flat-state weights before target-PF tilt.",
                    "favourable_persistence": "Increase profitable good-period weights and reduce flat-state weights before target-PF tilt.",
                    "abrupt_tail": "Increase known bad-period loss and flat-state weights before target-PF tilt.",
                }[family],
                "target_points_pf_values": list(PF_TARGETS),
                "controls": ["TP", "SL", "BE", "cutoff", "FLAT", "chronology_block_weights"],
                "does_not_control_point_scale": True,
                "manifest_ids": [m["scenario_id"] for m in manifests if m["scenario_family"] == family],
            }
        )
    return out


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, allow_nan=False)
