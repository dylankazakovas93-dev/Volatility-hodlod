# OG_PRIMARY_150R Build Results (Candidate B, BE45, target 1.50R)

Status: `PRIMARY_RESEARCH_CONFIG__RETROSPECTIVE_BUILD_PASS__NOT_VALIDATED`.
Config: `configs/OG_PRIMARY_150R.yaml`. Ledger:
`outputs/og_build_years/final_buildoff_B_build_years_trades.csv`. Every
number below was recomputed in this session directly from that ledger
(and cross-checked against `outputs/og_build_years/final_buildoff_be45.csv`,
row `candidate == "B"`) — none was copied from a prior doc without
recomputation.

## Ledger hash

```
sha256sum outputs/og_build_years/final_buildoff_B_build_years_trades.csv
426c42fe0f3d3f674f7b738bbfd6ae843a4b24c7c4abef09153692f472e5a655
```

This matches `expected_build_ledger.sha256` in `configs/OG_PRIMARY_150R.yaml`
exactly — **confirmed equal**.

## Build years used

2018 (full), 2020 (full), 2023 (full), 2026 (partial, through 2026-06-07).
404 total rows in the ledger.

## Per-year metrics

| year | n_trades | net_pts | PF_pts | PF_R | cap_norm_R_total | avg_R/trade | win_rate | avg_winner_pts | avg_loser_pts | payoff | max_dd_pts | max_dd_R | TP | SL | BE | cutoff | hold_mean_min | hold_median_min | prof_days | lose_days | BE_days | avg_daily_pnl | median_daily_pnl | longest_no-win_run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2018 | 113 | 620.93 | 1.6764 | 1.5656 | 20.1915 | 0.1787 | 0.3363 | 40.497 | -25.499 | 1.588 | -154.69 | -5.0000 | 37 | 35 | 39 | 2 | 167.0 | 88.0 | 37 | 31 | 22 | 6.899 | 0.000 | 7 |
| 2020 | 137 | 1401.01 | 1.5454 | 1.0569 | 2.7241 | 0.0199 | 0.2701 | 107.292 | -49.400 | 2.172 | -713.25 | -8.5015 | 30 | 46 | 48 | 13 | 193.2 | 81.0 | 35 | 46 | 24 | 13.343 | 0.000 | 10 |
| 2023 | 99 | 645.14 | 1.3628 | 1.4879 | 14.3272 | 0.1447 | 0.3232 | 75.727 | -55.566 | 1.363 | -407.06 | -5.6204 | 28 | 28 | 35 | 8 | 165.9 | 75.0 | 31 | 28 | 27 | 7.502 | 0.000 | 7 |
| 2026 (partial) | 55 | 1932.07 | 2.2112 | 1.5926 | 10.2309 | 0.1860 | 0.3636 | 176.363 | -88.622 | 1.990 | -571.12 | -7.3423 | 18 | 16 | 17 | 4 | 207.7 | 103.0 | 20 | 15 | 12 | 41.108 | 0.000 | 7 |

## Completed years pooled (2018+2020+2023)

n=349, net_pts=2667.08, PF_pts=1.5066, PF_R=1.3299, cap_norm_R_total=37.2428,
avg_R/trade=0.1067, win_rate=0.3066, avg_winner=74.130, avg_loser=-43.874,
payoff=1.690, max_dd_pts=-713.25, max_dd_R=-8.5015, TP=95, SL=109, BE=122,
cutoff=23, hold_mean=176.9min, hold_median=82.0min, profitable_days=103,
losing_days=105, BE_days=73, avg_daily_pnl=9.491, median_daily_pnl=0.000,
longest_no-win_run=10.

## All build years pooled (+2026 partial) — explicit

n=404, net_pts=4599.14, PF_pts=1.6704, PF_R=1.3647, cap_norm_R_total=47.4737,
avg_R/trade=0.1175, win_rate=0.3144, avg_winner=90.230, avg_loser=-49.711,
payoff=1.815, max_dd_pts=-713.25, max_dd_R=-8.5015, TP=113, SL=125, BE=139,
cutoff=27, hold_mean=181.1min, hold_median=86.5min, profitable_days=123,
losing_days=120, BE_days=85, avg_daily_pnl=14.022, median_daily_pnl=0.000,
longest_no-win_run=10.

## Result excluding 2026

Identical to the "completed years pooled" row above (2026 is simply not
included): n=349, avg_R/trade=0.1067, PF_R=1.3299, net_pts=2667.08.

## Result excluding the single best day (completed years only)

Best single day (completed years): 2020-03-20, +300.00 pts. Excluding it:
n=348, avg_R/trade=0.1027 (down from 0.1067). The edge over
`OG_OPERATIONAL_100R` (which drops from 0.0709 to 0.0682 on the same
exclusion) is preserved.

## Result excluding the single best year (completed years only)

Best completed year: 2020, net_pts=1401.01. Excluding it (i.e. pooling
2018+2023 only): n=212, avg_R/trade=0.1628 (up from 0.1067 — 2020 is
actually this config's *weakest* year on a per-trade basis, so removing it
raises, not lowers, the pooled average).

## Day-level metrics

Reused from `outputs/og_build_years/final_buildoff_daily_metrics.csv`
(candidate == "B", one row per `session_date` with >=1 trade; "a trading
day" is any `session_date` with executed trades; profitable/losing days
are net-P&L > 0 / < 0 for that day; breakeven days net to ~0; zero-trade
calendar days are excluded from all day tables). Completed years:
103 profitable / 105 losing / 73 breakeven days (49.5% of non-BE days
profitable). All build years incl. 2026: 123 profitable / 120 losing / 85
breakeven. Median daily P&L is 0.0 pts in both scopes (breakeven days are
common and the daily P&L distribution is right-skewed, not symmetric —
mean > median throughout).

## Exit-reason mix

Completed years: TP 95 / SL 109 / BE 122 / cutoff 23 (out of 349). All
build years: TP 113 / SL 125 / BE 139 / cutoff 27 (out of 404). BE is the
single largest exit category in both scopes, a direct mechanical
consequence of BE45 arming combined with the harder-to-reach 1.50R target
(see `docs/OG_100R_VS_150R_MECHANICS.md`).

## Holding time

Completed years: mean 176.9 min, median 82.0 min. All build years: mean
181.1 min, median 86.5 min.
