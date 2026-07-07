"""Causality unit tests for the OG regime kill-switch mechanisms: appending
future trades to the sequence must never change an earlier trade's
kill-switch state. Same style/intent as tests/test_og_hmm_causality.py."""
import sys, os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.og_regime_killswitch import (
    rolling_pf_killswitch,
    cusum_killswitch,
    streak_killswitch,
    compute_nonwin_streaks,
)


def _synthetic_trades(n, seed=0):
    rng = np.random.default_rng(seed)
    cap = rng.uniform(2.0, 10.0, size=n)
    r = rng.normal(loc=0.05, scale=1.0, size=n)
    pnl = r * cap
    return pd.DataFrame({"pnl": pnl, "cap": cap})


def _assert_prefix_invariant(fn, n_prefix=60, n_total=200):
    df_full = _synthetic_trades(n_total, seed=1)
    df_prefix = df_full.iloc[:n_prefix].reset_index(drop=True)

    full_result = fn(df_full)
    prefix_result = fn(df_prefix)

    if isinstance(full_result, pd.DataFrame):
        full_flat = full_result["flat"] if "flat" in full_result.columns else full_result.iloc[:, 0]
        prefix_flat = prefix_result["flat"] if "flat" in prefix_result.columns else prefix_result.iloc[:, 0]
    else:
        full_flat = full_result
        prefix_flat = prefix_result

    assert (full_flat.iloc[:n_prefix].to_numpy() == prefix_flat.to_numpy()).all(), (
        f"{fn} is not causal: appending future trades changed earlier kill-switch state."
    )


def test_rolling_pf_killswitch_is_causal():
    _assert_prefix_invariant(lambda df: rolling_pf_killswitch(df, window=50, threshold=1.0))
    _assert_prefix_invariant(lambda df: rolling_pf_killswitch(df, window=50, threshold=1.0, reentry_threshold=1.1))


def test_cusum_killswitch_is_causal():
    _assert_prefix_invariant(
        lambda df: cusum_killswitch(df, target_mean=0.05, k=0.5, h=2.0, cooldown_trades=20)
    )


def test_streak_killswitch_is_causal():
    baseline = compute_nonwin_streaks(_synthetic_trades(500, seed=7))
    _assert_prefix_invariant(
        lambda df: streak_killswitch(df, baseline_streaks=baseline, percentile=90, resume_after_wins=3)
    )


def test_incremental_append_never_perturbs_history():
    """Stronger check: appending ONE trade at a time never changes any prior
    decision, for the rolling-PF mechanism (the cheapest to run per-step)."""
    df_full = _synthetic_trades(80, seed=3)
    running = rolling_pf_killswitch(df_full.iloc[:10].reset_index(drop=True), window=5, threshold=1.0)
    for extra in range(11, 80):
        extended = rolling_pf_killswitch(df_full.iloc[:extra].reset_index(drop=True), window=5, threshold=1.0)
        assert (extended.iloc[:10].to_numpy() == running.to_numpy()).all()


if __name__ == "__main__":
    test_rolling_pf_killswitch_is_causal()
    test_cusum_killswitch_is_causal()
    test_streak_killswitch_is_causal()
    test_incremental_append_never_perturbs_history()
    print("PASS: all regime kill-switch mechanisms are causal")
