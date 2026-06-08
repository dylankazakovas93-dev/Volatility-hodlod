"""Python port of `indicator/fracdiff_gate.pine` ("FracDiff Gate (5m, TREND-sense)").

Binomial fractional-differencing z-score gate. Per the user's indicator notes,
the *trend-sense* mapping is:
  - LONG fade  (buy the lower level) confirmed when z >=  band
  - SHORT fade (sell the upper level) confirmed when z <= -band
i.e. the gate fires fades in the direction the z-score's *sign* already argues
for — opposite of the indicator's raw "EC" up/down triangles, per the user.

All math mirrors the Pine source line-for-line:
  - weights: w[0] = 1.0, then w[k] = w[k-1] * (k-1-d)/k for k=1..N, stopping
    (without appending) the first time |w[k]| < thresh (1e-3 fast / 1e-6 slow)
  - fd[i] = sum_{k=0}^{effN} w[k] * src[i-k]   (defined once i >= effN)
  - z = (fd - SMA(fd, zlen)) / population_stdev(fd, zlen)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FracDiffParams:
    d: float = 0.45
    N: int = 100
    zlen: int = 100
    band: float = 1.0
    fast: bool = True
    price_col: str = "close"


def fracdiff_weights(d: float, N: int, fast: bool = True) -> np.ndarray:
    """Binomial fractional-difference weights, matching the Pine loop exactly:
    start at w[0]=1.0, then wk *= (k-1-d)/k; stop (without appending) the first
    time |wk| drops below the cutoff threshold."""
    thresh = 1e-3 if fast else 1e-6
    w = [1.0]
    wk = 1.0
    for k in range(1, N + 1):
        wk = wk * (k - 1 - d) / k
        if abs(wk) < thresh:
            break
        w.append(wk)
    return np.array(w, dtype=float)


def fracdiff_series(price: pd.Series, weights: np.ndarray) -> pd.Series:
    """fd[i] = sum_{k=0}^{effN} w[k] * price[i-k], defined only for i >= effN
    (matches Pine's `if bar_index >= effN`); earlier bars are NaN."""
    eff_n = len(weights) - 1
    values = price.to_numpy(dtype=float)
    # FIR filter y[n] = sum_{k=0}^{K} w[k] * x[n-k].
    # np.convolve(x, w, "full")[n] = sum_k w[k] * x_padded[n-k] (x zero-padded);
    # for n in [0, len(x)-1] this only ever touches valid x indices (k <= n),
    # so truncating to len(x) gives exactly the causal FIR sum we want, with
    # the n < eff_n entries (which Pine leaves undefined) overwritten as NaN.
    filtered = np.convolve(values, weights, mode="full")[: len(values)]
    filtered[:eff_n] = np.nan
    return pd.Series(filtered, index=price.index, name="fd")


def zscore(fd: pd.Series, zlen: int) -> pd.Series:
    """(fd - SMA(fd, zlen)) / population_stdev(fd, zlen) — Pine's ta.sma/ta.stdev
    use a population (ddof=0) standard deviation by default."""
    mean = fd.rolling(zlen).mean()
    std = fd.rolling(zlen).std(ddof=0)
    return (fd - mean) / std


def compute_gate(ohlcv: pd.DataFrame, params: FracDiffParams = FracDiffParams()) -> pd.DataFrame:
    """Returns a DataFrame indexed like `ohlcv` with columns:
    fd, z, long_ok (z >= band -> LONG-fade confirmed, buy lower level),
    short_ok (z <= -band -> SHORT-fade confirmed, sell upper level)."""
    weights = fracdiff_weights(params.d, params.N, fast=params.fast)
    fd = fracdiff_series(ohlcv[params.price_col], weights)
    z = zscore(fd, params.zlen)
    return pd.DataFrame(
        {
            "fd": fd,
            "z": z,
            "long_ok": z >= params.band,
            "short_ok": z <= -params.band,
        },
        index=ohlcv.index,
    )


def resample_ohlcv(ohlcv_1m: pd.DataFrame, rule: str = "5min") -> pd.DataFrame:
    """Aggregate 1-minute OHLCV bars into `rule`-period bars (e.g. 5-minute),
    using standard OHLC aggregation. Drops bars with no trades (NaN open)."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in ohlcv_1m.columns:
        agg["volume"] = "sum"
    out = ohlcv_1m.resample(rule, label="left", closed="left").agg(agg)
    return out.dropna(subset=["open"])
