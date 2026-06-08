# Codex / Claude Sync Notes

## Reconciled mismatch

The large discrepancy between Codex's earlier NQ event-study numbers and Claude's reproduction was not the continuous futures builder or a bad Databento source.

It was the input timeframe plus `--max-bars` interpretation:

- Codex earlier quoted results from 5-minute bars with `--max-bars 24`, i.e. a 120-minute max hold.
- Claude reproduced results from 1-minute bars with `--max-bars 24`, i.e. a 24-minute max hold.

Running Codex's `scripts/nq_event_mode_study.py` on the local canonical continuous 1-minute file with `--max-bars 24` reproduces Claude's table:

```text
TP 0.5x prev 60m, RR 0.75, 1m input, max-bars 24:
always_reversal:          235 trades, +1487.611 pts, PF 1.396966
continue_tariff_headline: 235 trades, +1836.111 pts, PF 1.522833
skip_tariff_headline:     221 trades, +1711.591 pts, PF 1.607567

TP 0.75x prev 60m, RR 1.5, 1m input, max-bars 24:
always_reversal:          235 trades, +1745.834 pts, PF 1.485300
skip_tariff_headline:     221 trades, +1798.313 pts, PF 1.647299
```

## Current recommended standard

Use the canonical Databento NQ continuous 1-minute file:

```text
data/nq_1m/nq_continuous_1m.csv
```

or its equivalent local path/name, then be explicit about max hold in minutes. If using 1-minute input, `--max-bars 24` means 24 minutes. If using 5-minute input, `--max-bars 24` means 120 minutes.

Future scripts should ideally accept `--max-minutes` and convert to bars internally to remove this ambiguity.

## Still unresolved

- The event calendar's `tariff_headline` bucket is manual and must be treated as exploratory.
- ATR study results are currently an ATR-eligible subset, not the full 232/235-trade universe.
- Need risk-first ranking: max drawdown, worst month, one-trade/day, max-two-trades/day, and combined ATR/event filters.
