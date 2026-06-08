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

## Updated session-hold rule

The user clarified that the intended exit is not a fixed bar count:

- Enter on first touch.
- Hold until TP/SL or the futures-session cutoff at 15:00 ET.
- Do not enter between 15:00 and 19:00 ET.
- Resume entries at 19:00 ET; those evening trades belong to the next overnight/day session and can run until the next 15:00 ET cutoff.

`scripts/nq_event_mode_study.py` now supports this with:

```text
--exit-cutoff-time 15:00 --resume-time 19:00
```

On canonical NQ 1m data for 2025, two anchor configs under this rule:

```text
TP 0.5x prev 60m, RR 0.75:
always_reversal:          207 trades, +1512.505 pts, PF 1.322960
continue_tariff_headline: 207 trades, +2130.838 pts, PF 1.492118
skip_tariff_headline:     194 trades, +1861.088 pts, PF 1.518275

TP 0.75x prev 60m, RR 1.5:
always_reversal:          207 trades, +1071.110 pts, PF 1.211374
continue_tariff_headline: 207 trades, +1564.235 pts, PF 1.321191
skip_tariff_headline:     194 trades, +1248.485 pts, PF 1.307614
```

Simple post-filters on `TP 0.5x prev 60m, RR 0.75` under this session rule:

```text
continue_tariff_headline base:             207 trades, +2130.838 pts, PF 1.492, max DD -476.823
continue_tariff_headline max 2/day:        183 trades, +2044.070 pts, PF 1.565, max DD -374.747
continue_tariff_headline stop after loss:  165 trades, +2346.448 pts, PF 1.701, max DD -380.227
skip_tariff_headline base:                 194 trades, +1861.088 pts, PF 1.518, max DD -368.602
```
