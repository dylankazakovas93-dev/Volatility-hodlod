"""
Walk-forward test: train on a 6-month window, freeze the selected exit
config (cutoff time, TP, SL, breakeven on/off), then trade it unchanged
across the following 2 years. Repeat across the whole 2018-2026 history so
every fold's "trade" period is genuinely out-of-sample relative to what
picked its config.

Fold boundaries (UTC-naive, so a few hours of fuzz right at the boundary --
irrelevant at 6-month/2-year granularity):
  Fold 1: train 2018-01-01 -> 2018-06-30 | trade 2018-07-01 -> 2020-06-30
  Fold 2: train 2020-07-01 -> 2020-12-31 | trade 2021-01-01 -> 2022-12-31
  Fold 3: train 2023-01-01 -> 2023-06-30 | trade 2023-07-01 -> 2025-06-30
  Fold 4: train 2025-07-01 -> 2025-12-31 | trade 2026-01-01 -> 2026-06-07 (truncated: data ends there)

Populations (unchanged from prior work): premium (zone grade, both variants),
retest (variant), formation (variant). Entry/signal generation is completely
frozen -- only the exit config is fit per fold.
"""
import csv
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Volatility-hodlod/research")
from tpsl import fit_config, simulate_tpsl, trade_metrics

CACHE_DIR = "/home/user/Volatility-hodlod/research/cache"
OUT_DIR = "/home/user/Volatility-hodlod/research/output"

FOLDS = [
    dict(fold=1, train=("2018-01-01", "2018-06-30"), trade=("2018-07-01", "2020-06-30")),
    dict(fold=2, train=("2020-07-01", "2020-12-31"), trade=("2021-01-01", "2022-12-31")),
    dict(fold=3, train=("2023-01-01", "2023-06-30"), trade=("2023-07-01", "2025-06-30")),
    dict(fold=4, train=("2025-07-01", "2025-12-31"), trade=("2026-01-01", "2026-06-07")),
]

POPULATIONS = {
    "premium": lambda sig: sig[sig["premium"] == True],   # noqa: E712
    "retest": lambda sig: sig[sig["variant"] == "retest"],
    "formation": lambda sig: sig[sig["variant"] == "formation"],
}


def session_span_years(bars: pd.DataFrame, start, end) -> float:
    mask = (bars["session"] >= pd.Timestamp(start).date()) & (bars["session"] <= pd.Timestamp(end).date())
    n_sessions = bars.loc[mask, "session"].nunique()
    return n_sessions / 259.0


def slice_signals(signals: pd.DataFrame, bars: pd.DataFrame, start, end) -> pd.DataFrame:
    ts = bars["ts_event"].dt.tz_convert(None)
    entry_bar = signals["bar_index"] + 1
    valid = entry_bar < len(bars)
    entry_time = pd.Series(pd.NaT, index=signals.index)
    entry_time[valid] = ts.to_numpy()[entry_bar[valid].to_numpy()]
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1)
    mask = (entry_time >= start_ts) & (entry_time < end_ts)
    return signals[mask]


def append_row(path, row):
    """Append one result row to a per-population CSV immediately, so a
    container restart or crash mid-run only loses the in-progress fold,
    never the folds already completed."""
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header:
            w.writeheader()
        w.writerow(row)


def main(pop_names):
    bars = pd.read_parquet(f"{CACHE_DIR}/full_bars.parquet")
    signals = pd.read_parquet(f"{CACHE_DIR}/full_signals.parquet")
    print(f"loaded {len(bars):,} bars, {len(signals):,} signals "
          f"({bars['session'].min()} -> {bars['session'].max()})", flush=True)

    for pop_name in pop_names:
        filt = POPULATIONS[pop_name]
        pop_signals = filt(signals)
        results_path = f"{OUT_DIR}/walk_forward_results_{pop_name}.csv"
        done_folds = set()
        if os.path.exists(results_path):
            done_folds = set(pd.read_csv(results_path)["fold"].tolist())

        for fold in FOLDS:
            if fold["fold"] in done_folds:
                print(f"[{pop_name}][fold {fold['fold']}] already done, skipping", flush=True)
                continue
            train_sig = slice_signals(pop_signals, bars, *fold["train"])
            trade_sig = slice_signals(pop_signals, bars, *fold["trade"])
            train_years = (pd.Timestamp(fold["train"][1]) - pd.Timestamp(fold["train"][0])).days / 365.25
            trade_years = session_span_years(bars, *fold["trade"])

            grid, best = fit_config(train_sig, bars, span_years=train_years)
            row = dict(population=pop_name, fold=fold["fold"],
                       train_start=fold["train"][0], train_end=fold["train"][1],
                       trade_start=fold["trade"][0], trade_end=fold["trade"][1],
                       train_n_candidates=len(train_sig), trade_n_candidates=len(trade_sig))
            if not best:
                row.update(status="insufficient train data")
                append_row(results_path, row)
                print(f"[{pop_name}][fold {fold['fold']}] insufficient train data "
                      f"(n_candidates={len(train_sig)})", flush=True)
                continue

            oos_trades = simulate_tpsl(trade_sig, bars, best["tp"], best["sl"],
                                        best["cutoff"], best["breakeven_frac"])
            oos = trade_metrics(oos_trades, trade_years)

            row.update(status="ok", cutoff=best["cutoff"], tp=best["tp"], sl=best["sl"],
                       breakeven_frac=best["breakeven_frac"],
                       train_sharpe=best["sharpe_annual"], train_n=best["n"],
                       **{f"oos_{k}": v for k, v in oos.items()})
            append_row(results_path, row)
            oos_trades.to_csv(f"{OUT_DIR}/wf_trades_{pop_name}_fold{fold['fold']}.csv", index=False)
            print(f"[{pop_name}][fold {fold['fold']}] train-picked TP={best['tp']:.1f} "
                  f"SL={best['sl']:.1f} cutoff={best['cutoff']} be={best['breakeven_frac']} "
                  f"(train n={best['n']}, train Sharpe={best['sharpe_annual']:.2f}) -> "
                  f"OOS n={oos.get('n',0)} win_rate={oos.get('win_rate',float('nan')):.1f}% "
                  f"PF={oos.get('profit_factor',float('nan')):.2f} "
                  f"Sharpe={oos.get('sharpe_annual',float('nan')):.2f}", flush=True)

    print(f"\n[{','.join(pop_names)}] done")


if __name__ == "__main__":
    requested = sys.argv[1:] or list(POPULATIONS.keys())
    main(requested)
