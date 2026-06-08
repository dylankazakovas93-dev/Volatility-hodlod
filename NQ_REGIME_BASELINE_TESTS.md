# NQ regime baseline tests

This note tests the "maybe 2023-2024 were the wrong regime" hypothesis.

Common bracket/session settings:

- TP = 0.5x previous completed 60-minute high-low range.
- SL = TP / 0.75.
- Exit cutoff = 15:00 ET.
- Costs/slippage = none.

## 1. Dumb reversion baseline

The dumb baseline ignores the VDL levels and just fades an intraday move from
the RTH open:

- `pullback_long`: buy first low at/below open minus threshold.
- `rally_short`: sell first high at/above open plus threshold.
- `both`: take the first of either side.

The specific user-proposed 2% pullback test does **not** support a clean
"generic reversion fails in 2023-2024 and works in 2025-2026" story:

| Year | Dumb 2% pullback-long trades | Net pts | PF |
|---:|---:|---:|---:|
| 2023 | 3 | -27.5 | 0.65 |
| 2024 | 11 | -137.4 | 0.67 |
| 2025 | 14 | -272.9 | 0.67 |
| 2026YTD | 5 | +87.4 | 1.32 |

The samples are small, but this is not the same pattern as the VDL strategy.
At 1% pullbacks, the dumb long-fade is positive in 2023 and 2025, negative in
2024 and 2026YTD:

| Year | Dumb 1% pullback-long trades | Net pts | PF |
|---:|---:|---:|---:|
| 2023 | 54 | +588.4 | 1.57 |
| 2024 | 53 | -287.5 | 0.86 |
| 2025 | 72 | +1360.5 | 1.52 |
| 2026YTD | 24 | -274.4 | 0.79 |

Read: the dumb baseline does **not** prove that all mean reversion broadly flips
on/off in the same way as the level strategy. That weakens the "generic reversion
regime" explanation.

## 2. Prior VXN regime filter on the actual level strategy

This is more promising. The current candidate is:

- Default reversal.
- CPI continuation.
- Stop after first losing trade of the day.

Without a VXN filter:

| Year | Trades | Net pts | PF | Max DD |
|---:|---:|---:|---:|---:|
| 2023 | 169 | -79.9 | 0.97 | -550.1 |
| 2024 | 166 | -87.5 | 0.97 | -1185.8 |
| 2025 | 163 | +2363.1 | 1.76 | -325.0 |
| 2026YTD | 71 | +2481.2 | 3.76 | -166.8 |
| ALL | 569 | +4676.9 | 1.46 | -1185.8 |

With `prior_vxn >= 24`:

| Year | Trades | Net pts | PF | Max DD |
|---:|---:|---:|---:|---:|
| 2023 | 51 | -48.6 | 0.94 | -202.8 |
| 2024 | 8 | +5.4 | 1.03 | -62.2 |
| 2025 | 39 | +1115.7 | 2.24 | -199.0 |
| 2026YTD | 29 | +989.0 | 4.25 | -132.3 |
| ALL | 127 | +2061.6 | 1.93 | -276.8 |

With `prior_vxn >= 22`:

| Year | Trades | Net pts | PF | Max DD |
|---:|---:|---:|---:|---:|
| 2023 | 78 | +164.3 | 1.13 | -202.8 |
| 2024 | 26 | -818.3 | 0.32 | -998.6 |
| 2025 | 65 | +1213.0 | 1.76 | -284.4 |
| 2026YTD | 59 | +2283.8 | 4.42 | -132.3 |
| ALL | 228 | +2842.7 | 1.60 | -998.6 |

Read: `prior_vxn >= 24` is the cleaner version. It does not prove the strategy,
and 2024 has only 8 trades, but it is a real, simple, pre-trade regime filter:
it cuts the ugly 2023/2024 exposure hard, keeps the strong 2025/2026 behavior,
and reduces combined max drawdown from about `-1185.8` to `-276.8`.

## Current conclusion

We are not cooked, but the original unrestricted strategy is not validated.

The new leading hypothesis should be:

> The VDL NQ reversal/CPI-continuation setup is a high-volatility regime strategy,
> not an all-regime strategy.

The next validation pass should test `prior_vxn >= 24` as a locked regime filter,
not tune it endlessly. If Claude verifies these numbers, the clean candidate to
carry forward is:

- Prior-day VXN close >= 24.
- Default reversal.
- CPI continuation.
- Stop after first losing trade of the day.
- TP = 0.5x previous completed 1h range.
- SL = TP / 0.75.
- Entry window 19:00-15:00 ET.
