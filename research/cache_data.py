"""
Cache continuous bars + candidate signals per year to parquet so downstream
exit-formula experiments don't have to re-run the ~4min/year bar-by-bar
engine every time. Same 4 years, same defaults as run_mae_mfe.py.
"""
import os
import sys
import pandas as pd

sys.path.insert(0, "/home/user/Volatility-hodlod/research")
from data_pipeline import load_raw, build_continuous, year_slice
from engine import run_engine, session_prior_hilo_map

SOURCES = {
    2018: "/tmp/claude-0/-home-user-Volatility-hodlod/1437021e-bbd2-5133-b8bb-a6bc8d373b45/scratchpad/data_check/nq2018/glbx-mdp3-20180101-20191230.ohlcv-1m.csv.zst",
    2021: "/tmp/claude-0/-home-user-Volatility-hodlod/1437021e-bbd2-5133-b8bb-a6bc8d373b45/scratchpad/data_check/nq2021/glbx-mdp3-20210101-20221230.ohlcv-1m.csv.zst",
    2024: "/tmp/claude-0/-home-user-Volatility-hodlod/1437021e-bbd2-5133-b8bb-a6bc8d373b45/scratchpad/data_check/nq2023/glbx-mdp3-20230101-20241230.ohlcv-1m.csv.zst",
    2026: "/tmp/claude-0/-home-user-Volatility-hodlod/1437021e-bbd2-5133-b8bb-a6bc8d373b45/scratchpad/data_check/nq2025/glbx-mdp3-20250101-20260607.ohlcv-1m.csv.zst",
}

CACHE_DIR = "/home/user/Volatility-hodlod/research/cache"


def main():
    os.makedirs(CACHE_DIR, exist_ok=True)
    for year, path in SOURCES.items():
        bars_path = f"{CACHE_DIR}/{year}_bars.parquet"
        sig_path = f"{CACHE_DIR}/{year}_signals.parquet"
        if os.path.exists(bars_path) and os.path.exists(sig_path):
            print(f"[{year}] cache hit, skipping")
            continue
        print(f"[{year}] loading raw...", flush=True)
        raw = load_raw(path)
        cont = build_continuous(raw)
        sliced = year_slice(cont, year, warmup_days=5)
        prior_hilo = session_prior_hilo_map(cont)
        print(f"[{year}] running engine on {len(sliced):,} bars...", flush=True)
        signals = run_engine(sliced, prior_hilo)
        sliced.to_parquet(bars_path)
        signals.to_parquet(sig_path)
        print(f"[{year}] cached {len(sliced):,} bars, {len(signals):,} signals", flush=True)


if __name__ == "__main__":
    main()
