"""Permutation/randomization control: is the *specific* level placement the
indicator computes (sigma-implied move + IB extension + offset, all anchored
to that day's cash open) actually informative — or would any similarly-sized
offset from the open show the same subsequent-price-behavior pattern, simply
because GC trended hard over this window?

Method: keep each session's `cash_open` / `created_at` (so timing & context
stay real), but replace `upper_level - cash_open` and `lower_level - cash_open`
with an offset *resampled from the empirical distribution of real offsets,
shuffled across sessions*. This preserves "how far a level typically sits from
the open" (so touch rates stay comparable) while breaking the link between
that day's specific IB/sigma inputs and the level it produced. Re-run the
exact same touch + excursion measurement on these "fake" levels, many times,
to build a null distribution — then see where the real result falls in it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from volgen.reactions import evaluate_levels


def _net_bias_stats(ohlcv_1m: pd.DataFrame, levels: pd.DataFrame, horizon: int) -> dict:
    res = evaluate_levels(ohlcv_1m, levels, horizons_minutes=(horizon,))
    touched = res.dropna(subset=["touched_at"])
    ncol = f"net_bias_{horizon}m"
    out = {}
    for side in ("upper", "lower"):
        sub = touched[(touched["side"] == side)].dropna(subset=[ncol])
        out[f"{side}_n"] = len(sub)
        out[f"{side}_mean_net_bias"] = float(sub[ncol].mean()) if len(sub) else float("nan")
        out[f"{side}_median_net_bias"] = float(sub[ncol].median()) if len(sub) else float("nan")
        out[f"{side}_pct_reaction_wins"] = float((sub[ncol] > 0).mean()) if len(sub) else float("nan")
    return out


def run_permutation_test(
    ohlcv_1m: pd.DataFrame,
    levels: pd.DataFrame,
    horizon: int = 60,
    n_perm: int = 100,
    seed: int = 42,
) -> tuple[dict, pd.DataFrame]:
    """Returns (real_stats, null_distribution_df). null_distribution_df has
    one row per permutation with the same keys as real_stats."""
    rng = np.random.default_rng(seed)

    real_upper_offsets = (levels["upper_level"] - levels["cash_open"]).to_numpy()
    real_lower_offsets = (levels["lower_level"] - levels["cash_open"]).to_numpy()

    print(f"  [real]  computing observed statistics ...")
    real_stats = _net_bias_stats(ohlcv_1m, levels, horizon)

    null_rows = []
    for i in range(n_perm):
        fake = levels.copy()
        fake["upper_level"] = fake["cash_open"].to_numpy() + rng.permutation(real_upper_offsets)
        fake["lower_level"] = fake["cash_open"].to_numpy() + rng.permutation(real_lower_offsets)
        null_rows.append(_net_bias_stats(ohlcv_1m, fake, horizon))
        if (i + 1) % 10 == 0:
            print(f"  [null]  {i + 1}/{n_perm} permutations done")

    return real_stats, pd.DataFrame(null_rows)


def empirical_p_value(real_value: float, null_values: np.ndarray, alternative: str = "two-sided") -> float:
    """Fraction of null draws at least as extreme as the real value."""
    null_values = null_values[~np.isnan(null_values)]
    if len(null_values) == 0 or np.isnan(real_value):
        return float("nan")
    if alternative == "greater":
        return float((null_values >= real_value).mean())
    if alternative == "less":
        return float((null_values <= real_value).mean())
    # two-sided: how extreme is |real - median(null)|
    center = np.median(null_values)
    return float((np.abs(null_values - center) >= np.abs(real_value - center)).mean())
