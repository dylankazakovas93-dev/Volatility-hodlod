# NQ 2023-2026YTD validation

This is the first pass using the added Databento `NQ.FUT` 1-minute OHLCV pull for
2023-01-01 through 2024-12-30.

Common test settings:

- Levels: NQ params from the Pine port, using prior-day VXN close.
- Entry: first touch of level, filled at level price.
- Default logic: reversal only, lower = long fade, upper = short fade.
- CPI policy: CPI dates use continuation; all other dates remain default reversal.
- Bracket: TP = 0.5x previous completed 60-minute high-low range.
- Stop: SL = TP / 0.75.
- Session: entries from 19:00 ET through 15:00 ET, then paused until 19:00 ET.
- Costs/slippage: none.

## Selected year-by-year results

| Year | Policy | Variant | Trades | Net pts | PF | Max DD | Worst month | Negative months |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 2023 | always_reversal | base | 224 | -583.6 | 0.85 | -968.9 | -359.7 | 8 |
| 2023 | always_reversal | max_2_per_day | 197 | -263.0 | 0.92 | -589.0 | -277.6 | 7 |
| 2023 | always_reversal | stop_after_loss | 169 | +139.1 | 1.05 | -443.5 | -292.3 | 5 |
| 2023 | continue_cpi | base | 224 | -836.1 | 0.79 | -1245.8 | -330.5 | 9 |
| 2023 | continue_cpi | max_2_per_day | 197 | -552.3 | 0.84 | -965.0 | -254.6 | 8 |
| 2023 | continue_cpi | stop_after_loss | 169 | -79.9 | 0.97 | -550.1 | -269.3 | 6 |
| 2024 | always_reversal | base | 236 | -1602.7 | 0.72 | -1947.6 | -549.9 | 9 |
| 2024 | always_reversal | max_2_per_day | 198 | -1554.7 | 0.68 | -1940.7 | -565.0 | 8 |
| 2024 | always_reversal | stop_after_loss | 159 | -604.8 | 0.83 | -1121.1 | -448.3 | 7 |
| 2024 | continue_cpi | base | 236 | -641.6 | 0.88 | -1476.4 | -549.9 | 7 |
| 2024 | continue_cpi | max_2_per_day | 198 | -1116.8 | 0.76 | -1631.1 | -565.0 | 7 |
| 2024 | continue_cpi | stop_after_loss | 166 | -87.5 | 0.97 | -1185.8 | -448.3 | 6 |
| 2025 | always_reversal | base | 207 | +1512.5 | 1.32 | -790.9 | -422.5 | 3 |
| 2025 | always_reversal | max_2_per_day | 183 | +1644.5 | 1.43 | -528.2 | -114.8 | 4 |
| 2025 | always_reversal | stop_after_loss | 161 | +1716.6 | 1.50 | -455.8 | -82.5 | 4 |
| 2025 | continue_cpi | base | 207 | +2095.5 | 1.48 | -776.6 | -455.0 | 3 |
| 2025 | continue_cpi | max_2_per_day | 183 | +2260.1 | 1.64 | -427.4 | -114.8 | 2 |
| 2025 | continue_cpi | stop_after_loss | 164 | +2374.7 | 1.77 | -313.4 | -41.0 | 3 |
| 2026YTD | always_reversal | base | 82 | +2144.4 | 2.54 | -292.5 | -56.5 | 1 |
| 2026YTD | always_reversal | max_2_per_day | 78 | +2140.1 | 2.75 | -292.5 | +113.8 | 0 |
| 2026YTD | always_reversal | stop_after_loss | 69 | +1883.4 | 2.67 | -334.5 | +56.3 | 0 |
| 2026YTD | continue_cpi | base | 82 | +2638.4 | 3.31 | -189.5 | -56.5 | 1 |
| 2026YTD | continue_cpi | max_2_per_day | 78 | +2852.3 | 4.25 | -186.6 | +113.8 | 0 |
| 2026YTD | continue_cpi | stop_after_loss | 71 | +2481.2 | 3.76 | -166.8 | +56.3 | 0 |

## Combined 2023-2026YTD results

| Policy | Variant | Trades | Net pts | PF | Max DD | Worst month | Negative months |
|---|---|---:|---:|---:|---:|---:|---:|
| always_reversal | base | 749 | +1470.6 | 1.09 | -2528.4 | -549.9 | 21 |
| always_reversal | max_2_per_day | 656 | +1930.1 | 1.15 | -2160.4 | -565.0 | 19 |
| always_reversal | stop_after_loss | 559 | +3145.9 | 1.29 | -1121.1 | -448.3 | 16 |
| continue_cpi | base | 749 | +3256.1 | 1.22 | -1947.5 | -549.9 | 20 |
| continue_cpi | max_2_per_day | 656 | +3443.3 | 1.28 | -2128.1 | -565.0 | 17 |
| continue_cpi | stop_after_loss | 569 | +4676.9 | 1.46 | -1185.8 | -448.3 | 15 |

## CPI-only event split

| Year | Logic | Trades | Net pts | Win rate | PF |
|---:|---|---:|---:|---:|---:|
| 2023 | reversal | 13 | +110.1 | 61.5% | 1.57 |
| 2023 | continuation | 13 | -142.5 | 53.8% | 0.56 |
| 2024 | reversal | 19 | -361.3 | 31.6% | 0.35 |
| 2024 | continuation | 19 | +599.8 | 84.2% | 6.38 |
| 2025 | reversal | 14 | -200.8 | 57.1% | 0.51 |
| 2025 | continuation | 14 | +382.2 | 64.3% | 4.92 |
| 2026YTD | reversal | 4 | -217.5 | 25.0% | 0.37 |
| 2026YTD | continuation | 4 | +276.5 | 75.0% | 4.03 |

## Read

The positive read: CPI continuation is not just a 2025 artifact. It works in
2024, 2025, and 2026YTD, and the combined CPI event split is materially better
than fading CPI.

The negative read: 2023 rejects CPI continuation, and the all-level reversal
baseline is poor in both 2023 and 2024. The current candidate is not an
all-years-green strategy. The best combined version is `continue_cpi` with
`stop_after_loss`, but it still has 15 negative months and a -1185.8 point max
drawdown across 2023-2026YTD.

Practical conclusion: keep researching the levels, but do not lock this as a
finished strategy yet. The next useful step is not more event invention; it is
to explain the 2023/2024 regime failure and see whether a simple, pre-declared
regime filter can exclude those conditions without hurting 2025/2026.
