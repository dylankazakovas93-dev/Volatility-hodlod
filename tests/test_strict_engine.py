from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"


def _load(name: str) -> pd.DataFrame:
    path = OUT / name
    assert path.exists(), f"missing output artifact {path}"
    return pd.read_csv(path)


def test_no_overlapping_positions() -> None:
    df = _load("canonical_strict_executed.csv").sort_values("touched_at")
    entries = pd.to_datetime(df["touched_at"], utc=True)
    exits = pd.to_datetime(df["exit_time"], utc=True)
    for i in range(1, len(df)):
        assert entries.iloc[i] >= exits.iloc[i - 1]


def test_executed_trades_do_not_exceed_candidates_and_level_once() -> None:
    executed = _load("canonical_strict_executed.csv")
    eligible = _load("canonical_eligible_1841.csv")
    physical = _load("local_physical_touches.csv")
    assert len(executed) <= len(eligible)
    assert executed["level_id"].is_unique
    assert physical["level_id"].is_unique


def test_no_entries_during_blocked_hours() -> None:
    df = _load("canonical_strict_executed.csv")
    ts = pd.to_datetime(df["touched_at"], utc=True).dt.tz_convert("America/New_York")
    minutes = ts.dt.hour * 60 + ts.dt.minute
    assert ((minutes >= 19 * 60) | (minutes < 11 * 60)).all()


def test_no_entry_after_sal_activation_in_session() -> None:
    df = _load("canonical_strict_executed.csv").copy()
    df["touched_at"] = pd.to_datetime(df["touched_at"], utc=True)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    for _, day in df.sort_values("touched_at").groupby("sess_date"):
        loss_exits = day[(day["pnl"] < -0.1) & (day["exit"] != "BE")]["exit_time"]
        if loss_exits.empty:
            continue
        sal_at = loss_exits.min()
        after = day[day["touched_at"] >= sal_at]
        assert after.empty


def test_annual_totals_sum_to_overall() -> None:
    df = _load("canonical_strict_executed.csv")
    yearly = _load("canonical_strict_yearly.csv")
    base_yearly = yearly[yearly["variant"] == "base_legacy_entrybar"]
    assert round(base_yearly["net"].sum(), 8) == round(df["pnl"].sum(), 8)
    assert int(base_yearly["n"].sum()) == len(df)


def test_costs_are_applied_to_every_trade() -> None:
    base = _load("canonical_strict_executed.csv")
    costs = _load("canonical_costs.csv")
    base_net = float(base["pnl"].sum())
    n = len(base)
    for _, row in costs.iterrows():
        expected = base_net - n * float(row["cost_pts"])
        assert round(float(row["net"]), 8) == round(expected, 8)
