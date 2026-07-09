"""
Orchestrator for tonight's scope: default parameters only, no optimization.
Builds a continuous NQ contract per year, runs the ported indicator engine,
generates candidate signals under both entry variants (formation-instant,
retest), fills them, and produces separate non-overlapping MAE/MFE ledgers
for 60min / 120min / EOS horizons.

Years, per explicit instruction: 2018, 2021, 2024, 2026 (each pulled from
whichever source zip actually contains that calendar year; 2026 is partial,
data ends 2026-06-07).
"""
import sys
import pandas as pd

sys.path.insert(0, "/home/user/Volatility-hodlod/research")
from data_pipeline import load_raw, build_continuous, year_slice
from engine import run_engine, session_prior_hilo_map
from backtest import run_all_horizons

SOURCES = {
    2018: "/tmp/claude-0/-home-user-Volatility-hodlod/1437021e-bbd2-5133-b8bb-a6bc8d373b45/scratchpad/data_check/nq2018/glbx-mdp3-20180101-20191230.ohlcv-1m.csv.zst",
    2021: "/tmp/claude-0/-home-user-Volatility-hodlod/1437021e-bbd2-5133-b8bb-a6bc8d373b45/scratchpad/data_check/nq2021/glbx-mdp3-20210101-20221230.ohlcv-1m.csv.zst",
    2024: "/tmp/claude-0/-home-user-Volatility-hodlod/1437021e-bbd2-5133-b8bb-a6bc8d373b45/scratchpad/data_check/nq2023/glbx-mdp3-20230101-20241230.ohlcv-1m.csv.zst",
    2026: "/tmp/claude-0/-home-user-Volatility-hodlod/1437021e-bbd2-5133-b8bb-a6bc8d373b45/scratchpad/data_check/nq2025/glbx-mdp3-20250101-20260607.ohlcv-1m.csv.zst",
}

OUT_DIR = "/home/user/Volatility-hodlod/research/output"


def process_year(year: int, path: str) -> pd.DataFrame:
    print(f"[{year}] loading raw...", flush=True)
    raw = load_raw(path)
    print(f"[{year}] {len(raw):,} outright rows, building continuous...", flush=True)
    cont = build_continuous(raw)
    sliced = year_slice(cont, year, warmup_days=5)
    target_only = sliced[sliced["in_target_year"]]
    n_target_sessions = target_only["session"].nunique()
    n_rolls = target_only.drop_duplicates("session")["roll"].sum()
    print(f"[{year}] {len(sliced):,} bars ({n_target_sessions} target sessions, "
          f"{n_rolls} roll sessions within the year)", flush=True)

    prior_hilo = session_prior_hilo_map(cont)  # built off the FULL continuous series,
    # not just the slice, so the first session of the slice still gets a real prior day
    # (only the absolute first session in the raw feed has no prior day at all).

    signals = run_engine(sliced, prior_hilo)
    print(f"[{year}] {len(signals)} raw candidate signals "
          f"({(signals['variant']=='formation').sum() if len(signals) else 0} formation, "
          f"{(signals['variant']=='retest').sum() if len(signals) else 0} retest)", flush=True)

    trades = run_all_horizons(signals, sliced)
    if trades.empty:
        return trades

    target_sessions = set(sliced.loc[sliced["in_target_year"], "session"])
    trades = trades[trades["entry_session"].isin(target_sessions)].copy()
    trades.insert(0, "year", year)
    return trades


def main():
    all_trades = []
    for year, path in SOURCES.items():
        t = process_year(year, path)
        if not t.empty:
            all_trades.append(t)
    if not all_trades:
        print("No trades generated at all.")
        return
    ledger = pd.concat(all_trades, ignore_index=True)
    ledger.to_csv(f"{OUT_DIR}/mae_mfe_ledger_raw.csv", index=False)
    print(f"\nWrote {len(ledger)} total trade rows to {OUT_DIR}/mae_mfe_ledger_raw.csv")

    for (variant, horizon), grp in ledger.groupby(["variant", "horizon"]):
        fname = f"{OUT_DIR}/ledger_{variant}_{horizon}.csv"
        grp.to_csv(fname, index=False)


if __name__ == "__main__":
    main()
