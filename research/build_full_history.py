"""
Build ONE continuous bar series spanning the full available history
(2018-01-01 through 2026-06-07) from all 5 source dumps, and run the engine
ONCE across the whole span -- not year-by-year. This matters: running the
engine per-year (as run_mae_mfe.py/cache_data.py did) resets cluster/zone
state at each artificial year boundary, which isn't how the indicator would
actually behave on a continuously running chart. A single continuous pass
also means any walk-forward slicing downstream is just a date-range slice
of one already-correct signal set, not five independently-seeded ones.
"""
import sys
import pandas as pd

sys.path.insert(0, "/home/user/Volatility-hodlod/research")
from data_pipeline import load_raw, build_continuous
from engine import run_engine, session_prior_hilo_map

SOURCE_FILES = [
    "/tmp/claude-0/-home-user-Volatility-hodlod/1437021e-bbd2-5133-b8bb-a6bc8d373b45/scratchpad/data_check/nq2018/glbx-mdp3-20180101-20191230.ohlcv-1m.csv.zst",
    "/tmp/claude-0/-home-user-Volatility-hodlod/1437021e-bbd2-5133-b8bb-a6bc8d373b45/scratchpad/data_check/nq2020/glbx-mdp3-20200101-20201230.ohlcv-1m.csv.zst",
    "/tmp/claude-0/-home-user-Volatility-hodlod/1437021e-bbd2-5133-b8bb-a6bc8d373b45/scratchpad/data_check/nq2021/glbx-mdp3-20210101-20221230.ohlcv-1m.csv.zst",
    "/tmp/claude-0/-home-user-Volatility-hodlod/1437021e-bbd2-5133-b8bb-a6bc8d373b45/scratchpad/data_check/nq2023/glbx-mdp3-20230101-20241230.ohlcv-1m.csv.zst",
    "/tmp/claude-0/-home-user-Volatility-hodlod/1437021e-bbd2-5133-b8bb-a6bc8d373b45/scratchpad/data_check/nq2025/glbx-mdp3-20250101-20260607.ohlcv-1m.csv.zst",
]

CACHE_DIR = "/home/user/Volatility-hodlod/research/cache"


def main():
    print("loading + concatenating all 5 source files...", flush=True)
    raws = []
    for p in SOURCE_FILES:
        df = load_raw(p)
        print(f"  {p.split('/')[-1]}: {len(df):,} outright rows", flush=True)
        raws.append(df)
    raw = pd.concat(raws, ignore_index=True).sort_values("ts_event").reset_index(drop=True)
    dupes = raw.duplicated(subset=["ts_event", "symbol"]).sum()
    print(f"combined: {len(raw):,} rows, {dupes} duplicate (ts_event,symbol) rows dropped", flush=True)
    if dupes:
        raw = raw.drop_duplicates(subset=["ts_event", "symbol"]).reset_index(drop=True)

    print("building continuous front-month series across full history...", flush=True)
    cont = build_continuous(raw)
    n_sessions = cont["session"].nunique()
    n_rolls = cont.drop_duplicates("session")["roll"].sum()
    print(f"continuous: {len(cont):,} bars, {n_sessions} sessions, {n_rolls} true rolls, "
          f"span {cont['session'].min()} -> {cont['session'].max()}", flush=True)

    prior_hilo = session_prior_hilo_map(cont)
    print("running engine once across the full span (this is the long step)...", flush=True)
    signals = run_engine(cont, prior_hilo)
    print(f"done: {len(signals):,} candidate signals "
          f"({(signals['variant']=='formation').sum()} formation, "
          f"{(signals['variant']=='retest').sum()} retest)", flush=True)

    cont.to_parquet(f"{CACHE_DIR}/full_bars.parquet")
    signals.to_parquet(f"{CACHE_DIR}/full_signals.parquet")
    print("cached to", CACHE_DIR)


if __name__ == "__main__":
    main()
