"""
Fit an exit formula (TP/SL, no other parameters) for three populations:
  - premium  : zone grade == Premium, both entry variants pooled
  - retest   : retest-variant signals, any zone grade
  - formation: formation-variant signals, any zone grade

Exit is TP/SL bracket or a hard time cutoff (15:00 or 16:00 ET), whichever
comes first; unresolved trades are closed at cutoff mark-to-market, win or
loss, always counted. All 4 development years (2018/2021/2024/2026) pooled.
Entry mechanics, zone tolerance, cluster rules etc. are all unchanged
defaults -- nothing new is tunable except the TP/SL levels being fit here,
and those come from the population's own empirical MFE/MAE percentiles.
"""
import sys
import pandas as pd

sys.path.insert(0, "/home/user/Volatility-hodlod/research")
from tpsl import grid_search_pooled, best_trades_pooled

CACHE_DIR = "/home/user/Volatility-hodlod/research/cache"
OUT_DIR = "/home/user/Volatility-hodlod/research/output"
YEARS = [2018, 2021, 2024, 2026]
CUTOFFS = ["15:00", "16:00"]

POPULATIONS = {
    "premium": lambda sig: sig[sig["premium"] == True],   # noqa: E712
    "retest": lambda sig: sig[sig["variant"] == "retest"],
    "formation": lambda sig: sig[sig["variant"] == "formation"],
}


def load_year_data():
    data = {}
    for y in YEARS:
        bars = pd.read_parquet(f"{CACHE_DIR}/{y}_bars.parquet")
        signals = pd.read_parquet(f"{CACHE_DIR}/{y}_signals.parquet")
        data[y] = (bars, signals)
    return data


def main():
    all_year_data = load_year_data()
    summary_rows = []

    for pop_name, filt in POPULATIONS.items():
        for cutoff in CUTOFFS:
            year_data = {y: (filt(sig), bars) for y, (bars, sig) in all_year_data.items()}
            grid, best = grid_search_pooled(year_data, cutoff)
            if grid.empty:
                print(f"[{pop_name}][{cutoff}] no trades produced")
                continue
            grid.to_csv(f"{OUT_DIR}/tpsl_grid_{pop_name}_{cutoff.replace(':','')}.csv", index=False)

            best_trades = best_trades_pooled(year_data, cutoff, best["tp"], best["sl"])
            best_trades.to_csv(f"{OUT_DIR}/tpsl_best_trades_{pop_name}_{cutoff.replace(':','')}.csv", index=False)

            print(f"[{pop_name}][{cutoff}] best TP={best['tp']:.2f} SL={best['sl']:.2f} "
                  f"n={int(best['n'])} win_rate={best['win_rate']:.1f}% "
                  f"mean_pnl={best['mean_pnl']:.2f} total_pnl={best['total_pnl']:.1f}", flush=True)

            summary_rows.append(dict(population=pop_name, cutoff=cutoff, **{
                k: v for k, v in best.items()
            }))

    pd.DataFrame(summary_rows).to_csv(f"{OUT_DIR}/tpsl_fit_summary.csv", index=False)
    print("\nWrote fit summary to", f"{OUT_DIR}/tpsl_fit_summary.csv")


if __name__ == "__main__":
    main()
